from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.missions.mission_orchestrator import (
    MissionOrchestratorError,
    orchestrate_mission_step_safe,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionCycleRunnerError(Exception):
    """Mission Cycle Runnerの実行失敗。"""


MISSION_CYCLE_RUNNER_VERSION = (
    "mission-cycle-runner-v0.1"
)

DEFAULT_MAX_STEPS = 10
MAX_ALLOWED_STEPS = 50

TERMINAL_STAGES = {
    "MISSION_COMPLETED",
    "MISSION_FAILED",
    "MISSION_CANCELLED",
}

MASTER_WAIT_STAGES = {
    "WAIT_MISSION_APPROVAL",
    "WAIT_PATCH_CHECK",
    "WAIT_PATCH_APPLY_APPROVAL",
    "WAIT_COMMIT_APPROVAL",
}

REPAIR_OR_BLOCKED_STAGES = {
    "REPAIR_REQUIRED",
    "STATE_BLOCKED",
}

STOP_REASONS = {
    "MISSION_COMPLETED",
    "MISSION_FAILED",
    "MISSION_CANCELLED",
    "MASTER_ACTION_REQUIRED",
    "REPAIR_REQUIRED",
    "STATE_BLOCKED",
    "EXECUTION_DISABLED",
    "STAGE_NOT_EXECUTED",
    "NO_PROGRESS_DETECTED",
    "REPEATED_STATE_DETECTED",
    "MAX_STEPS_REACHED",
    "STEP_ERROR",
}


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _json_hash(
    value: Any,
) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _task_state_summary(
    mission: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks = mission.get("tasks", [])

    if not isinstance(tasks, list):
        return []

    return [
        {
            "task_type": task.get(
                "task_type"
            ),
            "status": task.get("status"),
        }
        for task in tasks
        if isinstance(task, dict)
    ]


def _mission_state(
    mission: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": mission.get("status"),
        "progress": mission.get("progress"),
        "next_action": mission.get(
            "next_action"
        ),
        "tasks": _task_state_summary(
            mission
        ),
    }


def _state_fingerprint(
    *,
    mission: dict[str, Any],
    stage: str,
) -> str:
    return _json_hash(
        {
            "mission": _mission_state(
                mission
            ),
            "stage": stage,
        }
    )


def _validate_max_steps(
    max_steps: int,
) -> int:
    if isinstance(max_steps, bool):
        raise MissionCycleRunnerError(
            "max_stepsは整数で指定してください。"
        )

    if not isinstance(max_steps, int):
        raise MissionCycleRunnerError(
            "max_stepsは整数で指定してください。"
        )

    if max_steps < 1:
        raise MissionCycleRunnerError(
            "max_stepsは1以上で指定してください。"
        )

    if max_steps > MAX_ALLOWED_STEPS:
        raise MissionCycleRunnerError(
            "max_stepsは"
            f"{MAX_ALLOWED_STEPS}以下で"
            "指定してください。"
        )

    return max_steps


def _stop_reason_for_stage(
    *,
    stage: str,
    requires_master_action: bool,
) -> str | None:
    if stage == "MISSION_COMPLETED":
        return "MISSION_COMPLETED"

    if stage == "MISSION_FAILED":
        return "MISSION_FAILED"

    if stage == "MISSION_CANCELLED":
        return "MISSION_CANCELLED"

    if stage == "REPAIR_REQUIRED":
        return "REPAIR_REQUIRED"

    if stage == "STATE_BLOCKED":
        return "STATE_BLOCKED"

    if (
        stage in MASTER_WAIT_STAGES
        or requires_master_action
    ):
        return "MASTER_ACTION_REQUIRED"

    return None


def _build_cycle_summary(
    *,
    mission_id: int,
    execute: bool,
    max_steps: int,
    started_at: str,
    completed_at: str,
    steps: list[dict[str, Any]],
    stop_reason: str,
    mission_before: dict[str, Any],
    mission_after: dict[str, Any],
    error: str | None,
) -> dict[str, Any]:
    seed = {
        "mission_id": mission_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "stop_reason": stop_reason,
        "step_count": len(steps),
    }

    return {
        "cycle_id": (
            "mission-cycle-"
            + _json_hash(seed)[:20]
        ),
        "cycle_runner_version": (
            MISSION_CYCLE_RUNNER_VERSION
        ),
        "mission_id": mission_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "execute_requested": execute,
        "max_steps": max_steps,
        "step_count": len(steps),
        "executed_step_count": sum(
            1
            for step in steps
            if step.get("executed") is True
        ),
        "stop_reason": stop_reason,
        "completed": (
            stop_reason
            == "MISSION_COMPLETED"
        ),
        "requires_master_action": (
            stop_reason
            == "MASTER_ACTION_REQUIRED"
        ),
        "repair_required": (
            stop_reason
            == "REPAIR_REQUIRED"
        ),
        "blocked": stop_reason in {
            "STATE_BLOCKED",
            "NO_PROGRESS_DETECTED",
            "REPEATED_STATE_DETECTED",
            "STEP_ERROR",
        },
        "error": error,
        "steps": steps,
        "mission_before": _mission_state(
            mission_before
        ),
        "mission_after": _mission_state(
            mission_after
        ),
        "safety": {
            "single_stage_per_orchestration": True,
            "automatic_mission_approval": False,
            "automatic_patch_apply": False,
            "automatic_commit": False,
            "automatic_repair_approval": False,
            "skip_verification": False,
            "maximum_step_limit": (
                MAX_ALLOWED_STEPS
            ),
        },
    }


def run_mission_cycle(
    *,
    mission_id: int,
    execute: bool = False,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    max_steps = _validate_max_steps(
        max_steps
    )

    started_at = _now()
    mission_before = get_mission(
        mission_id
    )

    steps: list[dict[str, Any]] = []
    fingerprints: set[str] = set()

    stop_reason = "MAX_STEPS_REACHED"
    cycle_error: str | None = None

    for index in range(
        1,
        max_steps + 1,
    ):
        try:
            result = (
                orchestrate_mission_step_safe(
                    mission_id=mission_id,
                    execute=execute,
                )
            )
        except (
            MissionOrchestratorError,
            MissionError,
        ) as error:
            stop_reason = "STEP_ERROR"
            cycle_error = str(error)

            steps.append(
                {
                    "step": index,
                    "stage": None,
                    "next_stage": None,
                    "executed": False,
                    "requires_master_action": False,
                    "error": str(error),
                }
            )
            break

        orchestration = result.get(
            "orchestration"
        )

        if not isinstance(
            orchestration,
            dict,
        ):
            stop_reason = "STEP_ERROR"
            cycle_error = (
                "Orchestrator結果に"
                "orchestrationがありません。"
            )
            break

        stage = str(
            orchestration.get("stage")
            or ""
        )
        next_stage = str(
            orchestration.get("next_stage")
            or ""
        )
        executed = (
            orchestration.get("executed")
            is True
        )

        decision = orchestration.get(
            "decision"
        )

        if not isinstance(decision, dict):
            decision = {}

        requires_master_action = (
            decision.get(
                "requires_master_action"
            )
            is True
        )

        mission_after_step = result.get(
            "mission"
        )

        if not isinstance(
            mission_after_step,
            dict,
        ):
            mission_after_step = get_mission(
                mission_id
            )

        fingerprint = _state_fingerprint(
            mission=mission_after_step,
            stage=next_stage or stage,
        )

        step_record = {
            "step": index,
            "orchestration_id": (
                orchestration.get(
                    "orchestration_id"
                )
            ),
            "stage": stage,
            "next_stage": next_stage,
            "executed": executed,
            "requires_master_action": (
                requires_master_action
            ),
            "recommended_action": (
                decision.get(
                    "recommended_action"
                )
            ),
            "reason": decision.get(
                "reason"
            ),
            "execution_error": (
                orchestration.get(
                    "execution_error"
                )
            ),
            "mission_after": (
                _mission_state(
                    mission_after_step
                )
            ),
            "state_fingerprint": (
                fingerprint
            ),
        }

        steps.append(step_record)

        stage_stop_reason = (
            _stop_reason_for_stage(
                stage=stage,
                requires_master_action=(
                    requires_master_action
                ),
            )
        )

        if stage_stop_reason is not None:
            stop_reason = stage_stop_reason
            break

        next_stage_stop_reason = (
            _stop_reason_for_stage(
                stage=next_stage,
                requires_master_action=(
                    orchestration.get(
                        "next_decision",
                        {},
                    ).get(
                        "requires_master_action"
                    )
                    is True
                    if isinstance(
                        orchestration.get(
                            "next_decision"
                        ),
                        dict,
                    )
                    else False
                ),
            )
        )

        if next_stage_stop_reason is not None:
            stop_reason = (
                next_stage_stop_reason
            )
            break

        if execute is False:
            stop_reason = "EXECUTION_DISABLED"
            break

        if executed is not True:
            stop_reason = "STAGE_NOT_EXECUTED"
            break

        if fingerprint in fingerprints:
            stop_reason = (
                "REPEATED_STATE_DETECTED"
            )
            break

        fingerprints.add(fingerprint)

        before_state = orchestration.get(
            "mission_before"
        )
        after_state = orchestration.get(
            "mission_after"
        )

        if (
            isinstance(before_state, dict)
            and isinstance(
                after_state,
                dict,
            )
            and before_state == after_state
            and stage == next_stage
        ):
            stop_reason = (
                "NO_PROGRESS_DETECTED"
            )
            break

        if index == max_steps:
            stop_reason = (
                "MAX_STEPS_REACHED"
            )

    mission_after = get_mission(
        mission_id
    )
    completed_at = _now()

    if stop_reason not in STOP_REASONS:
        raise MissionCycleRunnerError(
            "未定義の停止理由です: "
            f"{stop_reason}"
        )

    cycle = _build_cycle_summary(
        mission_id=mission_id,
        execute=execute,
        max_steps=max_steps,
        started_at=started_at,
        completed_at=completed_at,
        steps=steps,
        stop_reason=stop_reason,
        mission_before=mission_before,
        mission_after=mission_after,
        error=cycle_error,
    )

    if stop_reason == "MISSION_COMPLETED":
        level = "INFO"
        event_type = (
            "MISSION_CYCLE_COMPLETED"
        )
        message = (
            "Mission Cycle Runnerが"
            "Mission完了を確認しました。"
        )
    elif stop_reason == (
        "MASTER_ACTION_REQUIRED"
    ):
        level = "WARNING"
        event_type = (
            "MISSION_CYCLE_WAITING_MASTER"
        )
        message = (
            "Mission Cycle Runnerは"
            "マスター操作待ちで停止しました。"
        )
    elif stop_reason == "REPAIR_REQUIRED":
        level = "WARNING"
        event_type = (
            "MISSION_CYCLE_REPAIR_REQUIRED"
        )
        message = (
            "Mission Cycle Runnerは"
            "Repair必要状態で停止しました。"
        )
    elif stop_reason in {
        "STATE_BLOCKED",
        "NO_PROGRESS_DETECTED",
        "REPEATED_STATE_DETECTED",
        "STEP_ERROR",
    }:
        level = "ERROR"
        event_type = (
            "MISSION_CYCLE_BLOCKED"
        )
        message = (
            "Mission Cycle Runnerが"
            f"{stop_reason}で安全停止しました。"
        )
    else:
        level = "INFO"
        event_type = (
            "MISSION_CYCLE_STOPPED"
        )
        message = (
            "Mission Cycle Runnerが"
            f"{stop_reason}で停止しました。"
        )

    add_mission_log(
        mission_id=mission_id,
        level=level,
        event_type=event_type,
        message=message,
        metadata={
            "cycle_id": cycle["cycle_id"],
            "cycle_runner_version": (
                MISSION_CYCLE_RUNNER_VERSION
            ),
            "stop_reason": stop_reason,
            "step_count": len(steps),
            "executed_step_count": (
                cycle[
                    "executed_step_count"
                ]
            ),
            "requires_master_action": (
                cycle[
                    "requires_master_action"
                ]
            ),
            "repair_required": (
                cycle["repair_required"]
            ),
            "automatic_patch_apply": False,
            "automatic_commit": False,
        },
    )

    return {
        "mission": mission_after,
        "cycle": cycle,
    }


def run_mission_cycle_safe(
    *,
    mission_id: int,
    execute: bool = False,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    try:
        return run_mission_cycle(
            mission_id=mission_id,
            execute=execute,
            max_steps=max_steps,
        )
    except MissionCycleRunnerError:
        raise
    except (
        MissionOrchestratorError,
        MissionError,
    ) as error:
        raise MissionCycleRunnerError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionCycleRunnerError(
            "Mission Cycle Runnerで"
            "予期しないエラーが発生しました: "
            f"{error}"
        ) from error
