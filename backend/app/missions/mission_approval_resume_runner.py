from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.missions.commit_runner import (
    MissionCommitError,
    commit_mission_changes_safe,
)
from app.missions.implementation_runner import (
    MissionImplementationError,
    apply_mission_implementation_patch_safe,
)
from app.missions.mission_cycle_runner import (
    MissionCycleRunnerError,
    run_mission_cycle_safe,
)
from app.missions.mission_orchestrator import (
    MissionOrchestratorError,
    determine_mission_stage,
)
from app.missions.models import (
    MissionApprovalDecision,
    MissionApprovalResumeRequest,
    MissionCommitRequest,
    MissionPatchApplyRequest,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    approve_mission,
    get_mission,
)


class MissionApprovalResumeError(Exception):
    """Mission承認操作・再開処理の失敗。"""


MISSION_APPROVAL_RESUME_VERSION = (
    "mission-approval-resume-v0.1"
)

ACTION_STAGE_MAP = {
    "APPROVE_MISSION": (
        "WAIT_MISSION_APPROVAL"
    ),
    "APPLY_PATCH": (
        "WAIT_PATCH_APPLY_APPROVAL"
    ),
    "COMMIT_CHANGES": (
        "WAIT_COMMIT_APPROVAL"
    ),
}


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


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    tasks = mission.get("tasks")

    if not isinstance(tasks, list):
        raise MissionApprovalResumeError(
            "Mission Task情報が不正です。"
        )

    for task in tasks:
        if (
            isinstance(task, dict)
            and task.get("task_type")
            == task_type
        ):
            return task

    raise MissionApprovalResumeError(
        f"{task_type} Taskが見つかりません。"
    )


def _load_task_result(
    task: dict[str, Any],
) -> dict[str, Any]:
    raw = task.get("result")

    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str):
        raise MissionApprovalResumeError(
            "Task Resultが存在しません。"
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MissionApprovalResumeError(
            "Task Result JSONが不正です。"
        ) from error

    if not isinstance(result, dict):
        raise MissionApprovalResumeError(
            "Task Result形式が不正です。"
        )

    return result


def _normalize_optional(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip()

    return normalized or None


def _current_stage(
    mission: dict[str, Any],
) -> dict[str, Any]:
    decision = determine_mission_stage(
        mission
    )

    if not isinstance(decision, dict):
        raise MissionApprovalResumeError(
            "Mission Stage判定結果が不正です。"
        )

    return decision


def _validate_action_stage(
    *,
    action: str,
    stage: str,
) -> None:
    expected_stage = ACTION_STAGE_MAP.get(
        action
    )

    if expected_stage is None:
        raise MissionApprovalResumeError(
            f"未対応Actionです: {action}"
        )

    if stage != expected_stage:
        raise MissionApprovalResumeError(
            "現在Stageでは指定Actionを"
            "実行できません。"
            f" action={action}"
            f" expected_stage={expected_stage}"
            f" actual_stage={stage}"
        )


def _stored_patch_sha256(
    mission: dict[str, Any],
) -> str:
    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )

    implementation = _load_task_result(
        implementation_task
    )

    if (
        implementation.get("mode")
        != "PATCH_CHECKED"
    ):
        raise MissionApprovalResumeError(
            "Implementationは"
            "PATCH_CHECKEDではありません。"
        )

    patch = implementation.get("patch")

    if not isinstance(patch, dict):
        raise MissionApprovalResumeError(
            "Patch情報が存在しません。"
        )

    if patch.get("applicable") is not True:
        raise MissionApprovalResumeError(
            "適用可能と判定されていないPatchです。"
        )

    if patch.get("applied") is True:
        raise MissionApprovalResumeError(
            "Patchは既に適用済みです。"
        )

    patch_sha256 = patch.get("sha256")

    if (
        not isinstance(patch_sha256, str)
        or len(patch_sha256) != 64
    ):
        raise MissionApprovalResumeError(
            "保存済みPatch Hashが不正です。"
        )

    return patch_sha256


def preview_mission_approval_resume(
    *,
    mission_id: int,
    payload: MissionApprovalResumeRequest,
) -> dict[str, Any]:
    mission = get_mission(
        mission_id
    )

    decision = _current_stage(
        mission
    )

    stage = str(
        decision.get("stage")
        or ""
    ).strip().upper()

    action = payload.action.strip().upper()

    _validate_action_stage(
        action=action,
        stage=stage,
    )

    expected_patch_sha256 = None

    if action == "APPLY_PATCH":
        stored_hash = _stored_patch_sha256(
            mission
        )

        supplied_hash = _normalize_optional(
            payload.expected_patch_sha256
        )

        if supplied_hash is None:
            raise MissionApprovalResumeError(
                "APPLY_PATCHには"
                "expected_patch_sha256が必要です。"
            )

        if supplied_hash != stored_hash:
            raise MissionApprovalResumeError(
                "指定Patch Hashが"
                "保存済みHashと一致しません。"
            )

        expected_patch_sha256 = stored_hash

    if action == "COMMIT_CHANGES":
        message = _normalize_optional(
            payload.commit_message
        )

        if message is None:
            raise MissionApprovalResumeError(
                "COMMIT_CHANGESには"
                "commit_messageが必要です。"
            )

        if "\n" in message:
            raise MissionApprovalResumeError(
                "Commit Messageは"
                "1行で指定してください。"
            )

    return {
        "preview_version": (
            MISSION_APPROVAL_RESUME_VERSION
        ),
        "mission_id": mission_id,
        "action": action,
        "stage": stage,
        "stage_reason": decision.get(
            "reason"
        ),
        "expected_stage": (
            ACTION_STAGE_MAP[action]
        ),
        "valid": True,
        "requires_explicit_request": True,
        "continue_cycle": (
            payload.continue_cycle
        ),
        "max_steps": payload.max_steps,
        "expected_patch_sha256": (
            expected_patch_sha256
        ),
        "safety": {
            "preview_only": True,
            "mission_changed": False,
            "patch_apply_executed": False,
            "commit_executed": False,
            "single_dangerous_action_only": True,
            "automatic_mission_approval": False,
            "automatic_patch_apply": False,
            "automatic_commit": False,
        },
    }


def _execute_explicit_action(
    *,
    mission_id: int,
    payload: MissionApprovalResumeRequest,
) -> dict[str, Any]:
    action = payload.action.strip().upper()

    if action == "APPROVE_MISSION":
        result = approve_mission(
            mission_id=mission_id,
            payload=MissionApprovalDecision(
                reason=payload.reason,
                decided_by=payload.decided_by,
            ),
        )

        return {
            "action": action,
            "executed": True,
            "result": {
                "mission_status": result.get(
                    "status"
                ),
                "mission_progress": result.get(
                    "progress"
                ),
            },
        }

    if action == "APPLY_PATCH":
        expected_patch_sha256 = (
            _normalize_optional(
                payload.expected_patch_sha256
            )
        )

        if expected_patch_sha256 is None:
            raise MissionApprovalResumeError(
                "expected_patch_sha256が"
                "指定されていません。"
            )

        result = (
            apply_mission_implementation_patch_safe(
                mission_id=mission_id,
                payload=MissionPatchApplyRequest(
                    confirmation="APPLY_PATCH",
                    expected_patch_sha256=(
                        expected_patch_sha256
                    ),
                    decided_by=(
                        payload.decided_by
                    ),
                    note=payload.note,
                ),
            )
        )

        patch_apply = result.get(
            "patch_apply"
        )

        return {
            "action": action,
            "executed": True,
            "result": {
                "applied": (
                    patch_apply.get("applied")
                    if isinstance(
                        patch_apply,
                        dict,
                    )
                    else None
                ),
                "changed_file_count": (
                    patch_apply.get(
                        "changed_file_count"
                    )
                    if isinstance(
                        patch_apply,
                        dict,
                    )
                    else None
                ),
                "changed_files": (
                    patch_apply.get(
                        "changed_files"
                    )
                    if isinstance(
                        patch_apply,
                        dict,
                    )
                    else None
                ),
            },
        }

    if action == "COMMIT_CHANGES":
        message = _normalize_optional(
            payload.commit_message
        )

        if message is None:
            raise MissionApprovalResumeError(
                "commit_messageが"
                "指定されていません。"
            )

        result = commit_mission_changes_safe(
            mission_id=mission_id,
            payload=MissionCommitRequest(
                confirmation="COMMIT_CHANGES",
                message=message,
                committed_by=(
                    payload.decided_by
                ),
            ),
        )

        commit = result.get("commit")

        return {
            "action": action,
            "executed": True,
            "result": {
                "committed": (
                    commit.get("committed")
                    if isinstance(commit, dict)
                    else None
                ),
                "commit_hash": (
                    commit.get("commit_hash")
                    if isinstance(commit, dict)
                    else None
                ),
                "commit_subject": (
                    commit.get(
                        "commit_subject"
                    )
                    if isinstance(commit, dict)
                    else None
                ),
            },
        }

    raise MissionApprovalResumeError(
        f"未対応Actionです: {action}"
    )


def approve_and_resume_mission(
    *,
    mission_id: int,
    payload: MissionApprovalResumeRequest,
) -> dict[str, Any]:
    preview = preview_mission_approval_resume(
        mission_id=mission_id,
        payload=payload,
    )

    mission_before = get_mission(
        mission_id
    )

    action_result = _execute_explicit_action(
        mission_id=mission_id,
        payload=payload,
    )

    mission_after_action = get_mission(
        mission_id
    )

    cycle_result = None

    if payload.continue_cycle:
        cycle_result = run_mission_cycle_safe(
            mission_id=mission_id,
            execute=True,
            max_steps=payload.max_steps,
        )

    mission_after = get_mission(
        mission_id
    )

    created_at = _now()

    seed = {
        "mission_id": mission_id,
        "action": payload.action,
        "stage": preview["stage"],
        "created_at": created_at,
        "decided_by": (
            payload.decided_by.strip()
        ),
    }

    record = {
        "resume_id": (
            "mission-approval-resume-"
            + _sha256_json(seed)[:20]
        ),
        "resume_version": (
            MISSION_APPROVAL_RESUME_VERSION
        ),
        "mission_id": mission_id,
        "created_at": created_at,
        "action": payload.action,
        "approved_or_confirmed_by": (
            payload.decided_by.strip()
        ),
        "reason": _normalize_optional(
            payload.reason
        ),
        "note": _normalize_optional(
            payload.note
        ),
        "explicit_action": action_result,
        "cycle_started": (
            payload.continue_cycle
        ),
        "cycle": (
            cycle_result.get("cycle")
            if isinstance(
                cycle_result,
                dict,
            )
            else None
        ),
        "mission_before": {
            "status": mission_before.get(
                "status"
            ),
            "progress": mission_before.get(
                "progress"
            ),
            "next_action": mission_before.get(
                "next_action"
            ),
        },
        "mission_after_action": {
            "status": (
                mission_after_action.get(
                    "status"
                )
            ),
            "progress": (
                mission_after_action.get(
                    "progress"
                )
            ),
            "next_action": (
                mission_after_action.get(
                    "next_action"
                )
            ),
        },
        "mission_after": {
            "status": mission_after.get(
                "status"
            ),
            "progress": mission_after.get(
                "progress"
            ),
            "next_action": mission_after.get(
                "next_action"
            ),
        },
        "safety": {
            "explicit_action_required": True,
            "single_dangerous_action_only": True,
            "cycle_executes_safe_stages_only": True,
            "automatic_mission_approval": False,
            "automatic_patch_apply": False,
            "automatic_commit": False,
            "skip_verification": False,
        },
    }

    cycle = record.get("cycle")

    if isinstance(cycle, dict):
        next_action = cycle.get(
            "stop_reason"
        )
    else:
        next_decision = _current_stage(
            mission_after
        )
        next_action = next_decision.get(
            "stage"
        )

    record["next_action"] = next_action

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_APPROVAL_RESUMED"
        ),
        message=(
            f"{payload.action}を明示実行し、"
            "Mission Cycleを安全に再開しました。"
            if payload.continue_cycle
            else (
                f"{payload.action}を"
                "明示実行しました。"
            )
        ),
        metadata={
            "resume_id": record["resume_id"],
            "resume_version": (
                MISSION_APPROVAL_RESUME_VERSION
            ),
            "action": payload.action,
            "decided_by": (
                payload.decided_by.strip()
            ),
            "cycle_started": (
                payload.continue_cycle
            ),
            "next_action": next_action,
            "single_dangerous_action_only": True,
            "automatic_patch_apply": False,
            "automatic_commit": False,
        },
    )

    return {
        "mission": mission_after,
        "resume": record,
    }


def preview_mission_approval_resume_safe(
    *,
    mission_id: int,
    payload: MissionApprovalResumeRequest,
) -> dict[str, Any]:
    try:
        return preview_mission_approval_resume(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionApprovalResumeError:
        raise
    except (
        MissionOrchestratorError,
        MissionError,
    ) as error:
        raise MissionApprovalResumeError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionApprovalResumeError(
            "Approval Resume Previewで"
            "予期しないエラーが発生しました: "
            f"{error}"
        ) from error


def approve_and_resume_mission_safe(
    *,
    mission_id: int,
    payload: MissionApprovalResumeRequest,
) -> dict[str, Any]:
    try:
        return approve_and_resume_mission(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionApprovalResumeError:
        raise
    except (
        MissionImplementationError,
        MissionCommitError,
        MissionCycleRunnerError,
        MissionOrchestratorError,
        MissionError,
    ) as error:
        raise MissionApprovalResumeError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionApprovalResumeError(
            "Mission承認・再開中に"
            "予期しないエラーが発生しました: "
            f"{error}"
        ) from error
