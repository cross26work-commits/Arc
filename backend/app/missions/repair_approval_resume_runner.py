from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.models import (
    MissionApprovalDecision,
    MissionRepairApproveAndResumeRequest,
    MissionRepairResumeRequest,
)
from app.missions.repair_approval_workflow import (
    MissionRepairApprovalError,
    approve_repair_safe,
    get_repair_approval_safe,
)
from app.missions.repair_context_builder import (
    REPAIR_PLAN_ROOT,
)
from app.missions.repair_cycle_orchestrator import (
    MissionRepairCycleOrchestratorError,
    run_repair_cycle_step_safe,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairApprovalResumeError(Exception):
    """Repair承認後再開処理失敗時の例外。"""


REPAIR_APPROVAL_RESUME_VERSION = (
    "mission-repair-approval-resume-v0.1"
)

MAX_RESUME_HISTORY = 100


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
        raise MissionRepairApprovalResumeError(
            f"JSON読込に失敗しました: {path}"
        ) from error

    if not isinstance(data, dict):
        raise MissionRepairApprovalResumeError(
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


def _load_history(
    mission_id: int,
) -> list[dict[str, Any]]:
    data = _load_json(
        _mission_directory(mission_id)
        / "repair-approval-resume-history.json"
    )

    if not isinstance(data, dict):
        return []

    records = data.get("resumes")

    if not isinstance(records, list):
        return []

    return [
        item
        for item in records
        if isinstance(item, dict)
    ]


def _save_resume(
    *,
    mission_id: int,
    record: dict[str, Any],
) -> tuple[Path, Path]:
    mission_directory = _mission_directory(
        mission_id
    )

    current_path = (
        mission_directory
        / "repair-approval-resume.json"
    )

    history_path = (
        mission_directory
        / "repair-approval-resume-history.json"
    )

    history = _load_history(
        mission_id
    )

    history.append(record)

    history = history[
        -MAX_RESUME_HISTORY:
    ]

    _write_json_atomic(
        current_path,
        record,
    )

    _write_json_atomic(
        history_path,
        {
            "resume_version": (
                REPAIR_APPROVAL_RESUME_VERSION
            ),
            "mission_id": mission_id,
            "latest_resume": record,
            "resume_count": len(history),
            "resumes": history,
            "updated_at": _now(),
        },
    )

    return (
        current_path,
        history_path,
    )


def _current_draft(
    mission_id: int,
) -> dict[str, Any]:
    draft = _load_json(
        _mission_directory(mission_id)
        / "repair-edit-draft.json"
    )

    if not isinstance(draft, dict):
        raise MissionRepairApprovalResumeError(
            "Repair Edit Draftが存在しません。"
        )

    if draft.get("status") != "EDIT_READY":
        raise MissionRepairApprovalResumeError(
            (
                "Repair Edit Draftは再開可能な"
                "状態ではありません。"
                f" status={draft.get('status')}"
            )
        )

    return draft


def _current_evaluation(
    mission_id: int,
) -> dict[str, Any]:
    history = _load_json(
        _mission_directory(mission_id)
        / "repair-execution-policy-history.json"
    )

    if not isinstance(history, dict):
        raise MissionRepairApprovalResumeError(
            "Repair Execution Policy履歴がありません。"
        )

    evaluation = history.get(
        "latest_evaluation"
    )

    if not isinstance(evaluation, dict):
        raise MissionRepairApprovalResumeError(
            "最新Policy評価がありません。"
        )

    return evaluation


def _validated_approval(
    mission_id: int,
) -> dict[str, Any]:
    result = get_repair_approval_safe(
        mission_id
    )

    approval = result.get("approval")

    if not isinstance(approval, dict):
        raise MissionRepairApprovalResumeError(
            "Repair承認が存在しません。"
        )

    decision = str(
        approval.get(
            "decision",
            "",
        )
    ).strip().upper()

    if decision == "REJECTED":
        raise MissionRepairApprovalResumeError(
            "却下済みRepairは再開できません。"
        )

    if decision != "APPROVED":
        raise MissionRepairApprovalResumeError(
            (
                "Repair承認状態が不正です。"
                f" decision={decision}"
            )
        )

    draft = _current_draft(
        mission_id
    )

    evaluation = _current_evaluation(
        mission_id
    )

    if (
        approval.get("draft_id")
        != draft.get("draft_id")
    ):
        raise MissionRepairApprovalResumeError(
            (
                "承認対象と最新Draftが一致しません。"
                " 再承認が必要です。"
            )
        )

    if (
        approval.get("evaluation_id")
        != evaluation.get("evaluation_id")
    ):
        raise MissionRepairApprovalResumeError(
            (
                "承認対象と最新Policy評価が一致しません。"
                " 再承認が必要です。"
            )
        )

    if (
        evaluation.get("draft_id")
        != draft.get("draft_id")
    ):
        raise MissionRepairApprovalResumeError(
            "最新Policy評価とDraftが一致しません。"
        )

    if (
        evaluation.get("decision")
        != "APPROVAL_REQUIRED"
    ):
        raise MissionRepairApprovalResumeError(
            (
                "明示承認対象のPolicy評価ではありません。"
                f" decision={evaluation.get('decision')}"
            )
        )

    return approval


def _latest_matching_resume(
    *,
    mission_id: int,
    approval: dict[str, Any],
) -> dict[str, Any] | None:
    history = _load_history(
        mission_id
    )

    approval_id = approval.get(
        "approval_id"
    )

    draft_id = approval.get(
        "draft_id"
    )

    evaluation_id = approval.get(
        "evaluation_id"
    )

    for record in reversed(history):
        if (
            record.get("approval_id")
            == approval_id
            and record.get("draft_id")
            == draft_id
            and record.get("evaluation_id")
            == evaluation_id
            and record.get("outcome")
            == "RESUMED"
        ):
            return record

    return None


def resume_repair(
    *,
    mission_id: int,
    payload: MissionRepairResumeRequest,
) -> dict[str, Any]:
    mission_before = get_mission(
        mission_id
    )

    approval = _validated_approval(
        mission_id
    )

    duplicate = _latest_matching_resume(
        mission_id=mission_id,
        approval=approval,
    )

    if isinstance(duplicate, dict):
        return {
            "mission": mission_before,
            "resume_version": (
                REPAIR_APPROVAL_RESUME_VERSION
            ),
            **duplicate,
            "duplicate": True,
            "changed": False,
            "single_stage_only": True,
            "auto_apply": False,
        }

    requested_by = (
        payload.requested_by.strip()
    )

    if not requested_by:
        raise MissionRepairApprovalResumeError(
            "requested_byは必須です。"
        )

    step = run_repair_cycle_step_safe(
        mission_id
    )

    stage = str(
        step.get(
            "stage",
            "",
        )
    ).strip().upper()

    executed = step.get(
        "executed"
    )

    if stage != "CONNECT_EDIT":
        raise MissionRepairApprovalResumeError(
            (
                "承認後の再開Stageが不正です。"
                " expected=CONNECT_EDIT"
                f" actual={stage}"
            )
        )

    if executed is not True:
        raise MissionRepairApprovalResumeError(
            (
                "CONNECT_EDITが実行されませんでした。"
                f" executed={executed}"
            )
        )

    note = (
        payload.note.strip()
        if payload.note
        and payload.note.strip()
        else None
    )

    seed = {
        "mission_id": mission_id,
        "approval_id": approval.get(
            "approval_id"
        ),
        "draft_id": approval.get(
            "draft_id"
        ),
        "evaluation_id": approval.get(
            "evaluation_id"
        ),
        "step_id": step.get(
            "step_id"
        ),
        "requested_by": requested_by,
    }

    record = {
        "resume_id": (
            "repair-resume-"
            + _sha256_json(seed)[:20]
        ),
        "resume_version": (
            REPAIR_APPROVAL_RESUME_VERSION
        ),
        **seed,
        "created_at": _now(),
        "stage": stage,
        "executed": True,
        "outcome": "RESUMED",
        "requested_by": requested_by,
        "note": note,
        "single_stage_only": True,
        "auto_apply": False,
        "patch_apply_executed": False,
        "orchestrator_result": step,
    }

    current_path, history_path = (
        _save_resume(
            mission_id=mission_id,
            record=record,
        )
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_REPAIR_APPROVAL_RESUMED"
        ),
        message=(
            "承認済みRepair Cycleを"
            "CONNECT_EDITから再開しました。"
        ),
        metadata={
            "resume_version": (
                REPAIR_APPROVAL_RESUME_VERSION
            ),
            "resume_id": record[
                "resume_id"
            ],
            "approval_id": record[
                "approval_id"
            ],
            "draft_id": record[
                "draft_id"
            ],
            "evaluation_id": record[
                "evaluation_id"
            ],
            "stage": stage,
            "requested_by": requested_by,
            "single_stage_only": True,
            "auto_apply": False,
        },
    )

    return {
        "mission": get_mission(
            mission_id
        ),
        **record,
        "duplicate": False,
        "changed": True,
        "resume_path": str(
            current_path
        ),
        "history_path": str(
            history_path
        ),
        "next_action": (
            "RUN_REPAIR_CYCLE"
        ),
    }


def approve_and_resume_repair(
    *,
    mission_id: int,
    payload: MissionRepairApproveAndResumeRequest,
) -> dict[str, Any]:
    approval_result = approve_repair_safe(
        mission_id=mission_id,
        payload=MissionApprovalDecision(
            reason=payload.reason,
            decided_by=payload.decided_by,
        ),
    )

    resume_result = resume_repair(
        mission_id=mission_id,
        payload=MissionRepairResumeRequest(
            requested_by=payload.decided_by,
            note=payload.note,
        ),
    )

    return {
        "mission": resume_result.get(
            "mission"
        ),
        "resume_version": (
            REPAIR_APPROVAL_RESUME_VERSION
        ),
        "approval": approval_result,
        "resume": resume_result,
        "approved": True,
        "resumed": True,
        "single_stage_only": True,
        "auto_apply": False,
        "next_action": (
            "RUN_REPAIR_CYCLE"
        ),
    }


def resume_repair_safe(
    *,
    mission_id: int,
    payload: MissionRepairResumeRequest,
) -> dict[str, Any]:
    try:
        return resume_repair(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalResumeError,
        MissionRepairApprovalError,
        MissionRepairCycleOrchestratorError,
        MissionError,
    ):
        raise
    except Exception as error:
        raise MissionRepairApprovalResumeError(
            (
                "Repair承認後再開中に"
                "予期しないエラーが発生しました。"
            )
        ) from error


def approve_and_resume_repair_safe(
    *,
    mission_id: int,
    payload: MissionRepairApproveAndResumeRequest,
) -> dict[str, Any]:
    try:
        return approve_and_resume_repair(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalResumeError,
        MissionRepairApprovalError,
        MissionRepairCycleOrchestratorError,
        MissionError,
    ):
        raise
    except Exception as error:
        raise MissionRepairApprovalResumeError(
            (
                "Repair承認・再開中に"
                "予期しないエラーが発生しました。"
            )
        ) from error
