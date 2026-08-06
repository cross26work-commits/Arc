from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.models import (
    MissionApprovalDecision,
)
from app.missions.repair_context_builder import (
    REPAIR_PLAN_ROOT,
)
from app.missions.repair_request_builder import (
    _load_existing_request,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairPolicyApprovalError(Exception):
    """Repair Category Policy承認処理の例外。"""


REPAIR_POLICY_APPROVAL_VERSION = (
    "mission-repair-policy-approval-v0.1"
)

APPROVAL_TYPE = "REPAIR_CATEGORY_POLICY"

DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"

VALID_DECISIONS = {
    DECISION_APPROVED,
    DECISION_REJECTED,
}

MAX_APPROVAL_HISTORY = 100


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _sha256_json(
    value: dict[str, Any],
) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def _mission_directory(
    mission_id: int,
) -> Path:
    path = (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
    )

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def _current_path(
    mission_id: int,
) -> Path:
    return (
        _mission_directory(mission_id)
        / "repair-policy-approval.json"
    )


def _history_path(
    mission_id: int,
) -> Path:
    return (
        _mission_directory(mission_id)
        / "repair-policy-approval-history.json"
    )


def _load_json(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise MissionRepairPolicyApprovalError(
            f"Policy Approval JSON読込に失敗しました: {path}"
        ) from error

    if not isinstance(value, dict):
        raise MissionRepairPolicyApprovalError(
            "Policy Approval JSON形式が不正です。"
        )

    return value


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary.replace(path)


def _load_history(
    mission_id: int,
) -> list[dict[str, Any]]:
    value = _load_json(
        _history_path(mission_id)
    )

    if not isinstance(value, dict):
        return []

    approvals = value.get("approvals")

    if not isinstance(approvals, list):
        return []

    return [
        item
        for item in approvals
        if isinstance(item, dict)
    ]


def _save_approval(
    *,
    mission_id: int,
    approval: dict[str, Any],
) -> tuple[Path, Path]:
    current_path = _current_path(
        mission_id
    )
    history_path = _history_path(
        mission_id
    )

    history = _load_history(
        mission_id
    )
    history.append(approval)
    history = history[
        -MAX_APPROVAL_HISTORY:
    ]

    _write_json_atomic(
        current_path,
        approval,
    )

    _write_json_atomic(
        history_path,
        {
            "approval_version": (
                REPAIR_POLICY_APPROVAL_VERSION
            ),
            "approval_type": APPROVAL_TYPE,
            "mission_id": mission_id,
            "approval_count": len(history),
            "latest_approval": approval,
            "approvals": history,
            "updated_at": _now(),
        },
    )

    return current_path, history_path


def _validate_request_policy(
    repair_request: dict[str, Any],
) -> dict[str, Any]:
    repair_policy = repair_request.get(
        "repair_policy"
    )

    if not isinstance(
        repair_policy,
        dict,
    ):
        raise MissionRepairPolicyApprovalError(
            "Repair RequestにRepair Policyがありません。"
        )

    if (
        repair_policy.get(
            "repair_action"
        )
        != "REQUIRE_APPROVAL"
    ):
        raise MissionRepairPolicyApprovalError(
            "Category Policy承認対象ではありません。"
        )

    if (
        repair_policy.get(
            "resume_stage"
        )
        != "WAIT_REPAIR_APPROVAL"
    ):
        raise MissionRepairPolicyApprovalError(
            "Repair Policyの承認待機Stageが不正です。"
        )

    if (
        repair_policy.get(
            "requires_approval"
        )
        is not True
    ):
        raise MissionRepairPolicyApprovalError(
            "Repair Policyが承認必須ではありません。"
        )

    return repair_policy


def get_repair_policy_approval(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    repair_request = _load_existing_request(
        mission_id
    )

    if repair_request is None:
        raise MissionRepairPolicyApprovalError(
            "Repair Requestが存在しません。"
        )

    repair_policy = _validate_request_policy(
        repair_request
    )

    approval = _load_json(
        _current_path(mission_id)
    )

    matches_current_request = (
        isinstance(approval, dict)
        and approval.get("request_id")
        == repair_request.get("request_id")
    )

    return {
        "mission": mission,
        "approval_version": (
            REPAIR_POLICY_APPROVAL_VERSION
        ),
        "approval_type": APPROVAL_TYPE,
        "repair_request": {
            "request_id": repair_request.get(
                "request_id"
            ),
            "failure_category": (
                repair_policy.get(
                    "failure_category"
                )
            ),
            "repair_action": (
                repair_policy.get(
                    "repair_action"
                )
            ),
            "resume_stage": (
                repair_policy.get(
                    "resume_stage"
                )
            ),
        },
        "approval": (
            approval
            if matches_current_request
            else None
        ),
        "approval_required": True,
        "matches_current_request": (
            matches_current_request
        ),
    }


def _decide_policy_repair(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
    decision: str,
) -> dict[str, Any]:
    if decision not in VALID_DECISIONS:
        raise MissionRepairPolicyApprovalError(
            f"不正なPolicy承認Decisionです: {decision}"
        )

    mission = get_mission(mission_id)

    repair_request = _load_existing_request(
        mission_id
    )

    if repair_request is None:
        raise MissionRepairPolicyApprovalError(
            "Repair Requestが存在しません。"
        )

    repair_policy = _validate_request_policy(
        repair_request
    )

    request_id = str(
        repair_request.get(
            "request_id"
        )
        or ""
    ).strip()

    if not request_id:
        raise MissionRepairPolicyApprovalError(
            "Repair Request IDがありません。"
        )

    decided_by = payload.decided_by.strip()

    if not decided_by:
        raise MissionRepairPolicyApprovalError(
            "decided_byは必須です。"
        )

    existing = _load_json(
        _current_path(mission_id)
    )

    if (
        isinstance(existing, dict)
        and existing.get("request_id")
        == request_id
        and existing.get("decision")
        == decision
    ):
        return {
            "mission": mission,
            "approval_version": (
                REPAIR_POLICY_APPROVAL_VERSION
            ),
            **existing,
            "duplicate": True,
            "changed": False,
        }

    decided_at = _now()

    seed = {
        "mission_id": mission_id,
        "request_id": request_id,
        "decision": decision,
        "decided_by": decided_by,
        "decided_at": decided_at,
    }

    approval = {
        "approval_id": (
            "repair-policy-approval-"
            + _sha256_json(seed)[:20]
        ),
        "approval_version": (
            REPAIR_POLICY_APPROVAL_VERSION
        ),
        "approval_type": APPROVAL_TYPE,
        "mission_id": mission_id,
        "request_id": request_id,
        "request_signature": (
            repair_request.get(
                "request_signature"
            )
        ),
        "failure_category": (
            repair_policy.get(
                "failure_category"
            )
        ),
        "repair_action": (
            repair_policy.get(
                "repair_action"
            )
        ),
        "resume_stage": (
            repair_policy.get(
                "resume_stage"
            )
        ),
        "decision": decision,
        "decided_by": decided_by,
        "reason": (
            payload.reason.strip()
            if payload.reason
            and payload.reason.strip()
            else None
        ),
        "decided_at": decided_at,
        "auto_apply": False,
        "automatic_approval": False,
    }

    current_path, history_path = (
        _save_approval(
            mission_id=mission_id,
            approval=approval,
        )
    )

    event_type = (
        "MISSION_REPAIR_POLICY_APPROVED"
        if decision == DECISION_APPROVED
        else "MISSION_REPAIR_POLICY_REJECTED"
    )

    add_mission_log(
        mission_id=mission_id,
        level=(
            "INFO"
            if decision == DECISION_APPROVED
            else "WARNING"
        ),
        event_type=event_type,
        message=(
            "Repair Category Policyの"
            f"{decision}を記録しました。"
        ),
        metadata={
            "approval_id": approval[
                "approval_id"
            ],
            "request_id": request_id,
            "failure_category": approval[
                "failure_category"
            ],
            "decision": decision,
            "decided_by": decided_by,
            "auto_apply": False,
        },
    )

    return {
        "mission": mission,
        **approval,
        "duplicate": False,
        "changed": True,
        "current_path": str(
            current_path
        ),
        "history_path": str(
            history_path
        ),
    }


def approve_repair_policy(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    return _decide_policy_repair(
        mission_id=mission_id,
        payload=payload,
        decision=DECISION_APPROVED,
    )


def reject_repair_policy(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    return _decide_policy_repair(
        mission_id=mission_id,
        payload=payload,
        decision=DECISION_REJECTED,
    )


def get_repair_policy_approval_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return get_repair_policy_approval(
            mission_id
        )
    except (
        MissionRepairPolicyApprovalError,
        MissionError,
    ):
        raise


def approve_repair_policy_safe(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    try:
        return approve_repair_policy(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairPolicyApprovalError,
        MissionError,
    ):
        raise


def reject_repair_policy_safe(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    try:
        return reject_repair_policy(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairPolicyApprovalError,
        MissionError,
    ):
        raise
