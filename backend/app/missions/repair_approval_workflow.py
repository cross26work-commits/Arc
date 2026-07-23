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
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairApprovalError(Exception):
    """Repair承認処理失敗時の例外。"""


REPAIR_APPROVAL_WORKFLOW_VERSION = (
    "mission-repair-approval-workflow-v0.1"
)

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


def _load_json(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise MissionRepairApprovalError(
            f"JSON読込に失敗しました: {path}"
        ) from error

    if not isinstance(data, dict):
        raise MissionRepairApprovalError(
            f"JSON形式が不正です: {path}"
        )

    return data


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
        ) + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def _repair_edit_draft(
    mission_id: int,
) -> dict[str, Any]:
    path = (
        _mission_directory(mission_id)
        / "repair-edit-draft.json"
    )

    draft = _load_json(path)

    if not isinstance(draft, dict):
        raise MissionRepairApprovalError(
            "Repair Edit Draftが存在しません。"
        )

    if draft.get("status") != "EDIT_READY":
        raise MissionRepairApprovalError(
            (
                "Repair Edit Draftは承認可能な"
                "状態ではありません。"
                f" status={draft.get('status')}"
            )
        )

    draft_id = draft.get("draft_id")

    if not isinstance(draft_id, str):
        raise MissionRepairApprovalError(
            "Repair Edit Draft IDが不正です。"
        )

    return draft


def _policy_evaluation(
    *,
    mission_id: int,
    draft: dict[str, Any],
) -> dict[str, Any]:
    path = (
        _mission_directory(mission_id)
        / "repair-execution-policy-history.json"
    )

    history = _load_json(path)

    if not isinstance(history, dict):
        raise MissionRepairApprovalError(
            "Repair Execution Policy履歴がありません。"
        )

    evaluation = history.get(
        "latest_evaluation"
    )

    if not isinstance(evaluation, dict):
        raise MissionRepairApprovalError(
            "最新Policy評価がありません。"
        )

    if (
        evaluation.get("draft_id")
        != draft.get("draft_id")
    ):
        raise MissionRepairApprovalError(
            (
                "Policy評価と最新Draftが一致しません。"
                " 再評価してください。"
            )
        )

    if (
        evaluation.get("decision")
        != "APPROVAL_REQUIRED"
    ):
        raise MissionRepairApprovalError(
            (
                "明示承認が必要なPolicy評価ではありません。"
                f" decision={evaluation.get('decision')}"
            )
        )

    evaluation_id = evaluation.get(
        "evaluation_id"
    )

    if not isinstance(
        evaluation_id,
        str,
    ):
        raise MissionRepairApprovalError(
            "Policy Evaluation IDが不正です。"
        )

    return evaluation


def _current_approval(
    mission_id: int,
) -> dict[str, Any] | None:
    return _load_json(
        _mission_directory(mission_id)
        / "repair-approval.json"
    )


def _approval_matches(
    *,
    approval: dict[str, Any] | None,
    draft: dict[str, Any],
    evaluation: dict[str, Any],
) -> bool:
    if not isinstance(approval, dict):
        return False

    return (
        approval.get("draft_id")
        == draft.get("draft_id")
        and approval.get("evaluation_id")
        == evaluation.get("evaluation_id")
    )


def _load_history(
    mission_id: int,
) -> list[dict[str, Any]]:
    data = _load_json(
        _mission_directory(mission_id)
        / "repair-approval-history.json"
    )

    if not isinstance(data, dict):
        return []

    approvals = data.get("approvals")

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
    mission_directory = _mission_directory(
        mission_id
    )

    current_path = (
        mission_directory
        / "repair-approval.json"
    )

    history_path = (
        mission_directory
        / "repair-approval-history.json"
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
            "workflow_version": (
                REPAIR_APPROVAL_WORKFLOW_VERSION
            ),
            "mission_id": mission_id,
            "latest_approval": approval,
            "approval_count": len(history),
            "approvals": history,
            "updated_at": _now(),
        },
    )

    return (
        current_path,
        history_path,
    )


def _decide_repair(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
    decision: str,
) -> dict[str, Any]:
    if decision not in VALID_DECISIONS:
        raise MissionRepairApprovalError(
            f"不正な承認判定です: {decision}"
        )

    mission = get_mission(mission_id)

    draft = _repair_edit_draft(
        mission_id
    )

    evaluation = _policy_evaluation(
        mission_id=mission_id,
        draft=draft,
    )

    existing = _current_approval(
        mission_id
    )

    if _approval_matches(
        approval=existing,
        draft=draft,
        evaluation=evaluation,
    ):
        existing_decision = (
            str(
                existing.get(
                    "decision",
                    "",
                )
            )
            .strip()
            .upper()
        )

        if existing_decision == decision:
            return {
                "mission": mission,
                "workflow_version": (
                    REPAIR_APPROVAL_WORKFLOW_VERSION
                ),
                **existing,
                "duplicate": True,
                "changed": False,
                "approval_path": str(
                    _mission_directory(
                        mission_id
                    )
                    / "repair-approval.json"
                ),
            }

        raise MissionRepairApprovalError(
            (
                "同じRepair Draftには既に"
                f"{existing_decision}判定があります。"
                " 判定の上書きは禁止されています。"
            )
        )

    decided_by = payload.decided_by.strip()

    if not decided_by:
        raise MissionRepairApprovalError(
            "decided_byは必須です。"
        )

    reason = (
        payload.reason.strip()
        if payload.reason
        and payload.reason.strip()
        else None
    )

    approval_seed = {
        "mission_id": mission_id,
        "draft_id": draft["draft_id"],
        "evaluation_id": evaluation[
            "evaluation_id"
        ],
        "decision": decision,
        "decided_by": decided_by,
        "reason": reason,
    }

    approval = {
        "approval_id": (
            "repair-approval-"
            + _sha256_json(
                approval_seed
            )[:20]
        ),
        "workflow_version": (
            REPAIR_APPROVAL_WORKFLOW_VERSION
        ),
        **approval_seed,
        "risk_level": evaluation.get(
            "risk_level"
        ),
        "policy_decision": evaluation.get(
            "decision"
        ),
        "decided_at": _now(),
        "immutable": True,
        "auto_approved": False,
        "auto_apply": False,
    }

    approval_path, history_path = (
        _save_approval(
            mission_id=mission_id,
            approval=approval,
        )
    )

    event_type = (
        "MISSION_REPAIR_APPROVED"
        if decision == DECISION_APPROVED
        else "MISSION_REPAIR_REJECTED"
    )

    log_level = (
        "INFO"
        if decision == DECISION_APPROVED
        else "WARNING"
    )

    message = (
        "Repair Edit Draftを承認しました。"
        if decision == DECISION_APPROVED
        else "Repair Edit Draftを却下しました。"
    )

    add_mission_log(
        mission_id=mission_id,
        level=log_level,
        event_type=event_type,
        message=message,
        metadata={
            "workflow_version": (
                REPAIR_APPROVAL_WORKFLOW_VERSION
            ),
            "approval_id": approval[
                "approval_id"
            ],
            "draft_id": approval[
                "draft_id"
            ],
            "evaluation_id": approval[
                "evaluation_id"
            ],
            "decision": decision,
            "decided_by": decided_by,
            "reason": reason,
            "risk_level": approval.get(
                "risk_level"
            ),
            "auto_apply": False,
        },
    )

    return {
        "mission": mission,
        **approval,
        "duplicate": False,
        "changed": True,
        "approval_path": str(
            approval_path
        ),
        "history_path": str(
            history_path
        ),
        "next_action": (
            "RUN_REPAIR_CYCLE"
            if decision == DECISION_APPROVED
            else "REPAIR_CYCLE_BLOCKED"
        ),
    }


def approve_repair(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    return _decide_repair(
        mission_id=mission_id,
        payload=payload,
        decision=DECISION_APPROVED,
    )


def reject_repair(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    return _decide_repair(
        mission_id=mission_id,
        payload=payload,
        decision=DECISION_REJECTED,
    )


def get_repair_approval(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    approval = _current_approval(
        mission_id
    )

    return {
        "mission": mission,
        "workflow_version": (
            REPAIR_APPROVAL_WORKFLOW_VERSION
        ),
        "approval": approval,
        "approval_exists": isinstance(
            approval,
            dict,
        ),
        "approval_path": str(
            _mission_directory(
                mission_id
            )
            / "repair-approval.json"
        ),
    }


def approve_repair_safe(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    try:
        return approve_repair(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalError,
        MissionError,
    ):
        raise
    except Exception as error:
        raise MissionRepairApprovalError(
            (
                "Repair承認処理中に"
                "予期しないエラーが発生しました。"
            )
        ) from error


def reject_repair_safe(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    try:
        return reject_repair(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalError,
        MissionError,
    ):
        raise
    except Exception as error:
        raise MissionRepairApprovalError(
            (
                "Repair却下処理中に"
                "予期しないエラーが発生しました。"
            )
        ) from error


def get_repair_approval_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return get_repair_approval(
            mission_id
        )
    except (
        MissionRepairApprovalError,
        MissionError,
    ):
        raise
    except Exception as error:
        raise MissionRepairApprovalError(
            (
                "Repair承認状態の取得中に"
                "予期しないエラーが発生しました。"
            )
        ) from error
