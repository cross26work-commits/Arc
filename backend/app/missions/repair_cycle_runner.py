from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


class MissionRepairCycleRunnerError(Exception):
    """Repair Cycle連続実行失敗時の例外。"""


REPAIR_CYCLE_RUNNER_VERSION = (
    "mission-repair-cycle-runner-v0.1"
)

DEFAULT_MAX_STEPS = 8
MIN_MAX_STEPS = 1
MAX_MAX_STEPS = 20
MAX_RUN_HISTORY = 50

TERMINAL_STAGES = {
    "CYCLE_COMPLETED",
}

BLOCKED_STAGES = {
    "STATE_BLOCKED",
}

WAITING_STAGES = {
    "WAIT_APPROVAL",
}

TERMINAL_OUTCOMES = {
    "COMPLETED",
}

BLOCKED_OUTCOMES = {
    "BLOCKED",
}

WAITING_OUTCOMES = {
    "WAITING_APPROVAL",
}

STOP_REASONS = {
    "CYCLE_COMPLETED",
    "STATE_BLOCKED",
    "WAIT_APPROVAL",
    "DUPLICATE_STEP",
    "NO_PROGRESS",
    "REPEATED_STATE",
    "MAX_STEPS_REACHED",
    "STEP_ERROR",
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
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def _mission_directory(
    mission_id: int,
) -> Path:
    return (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
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
    ):
        return None

    if not isinstance(value, dict):
        return None

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
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def _validate_max_steps(
    max_steps: int | None,
) -> int:
    if max_steps is None:
        return DEFAULT_MAX_STEPS

    if isinstance(max_steps, bool):
        raise MissionRepairCycleRunnerError(
            "max_stepsは整数で指定してください。"
        )

    if not isinstance(max_steps, int):
        raise MissionRepairCycleRunnerError(
            "max_stepsは整数で指定してください。"
        )

    if max_steps < MIN_MAX_STEPS:
        raise MissionRepairCycleRunnerError(
            "max_stepsは1以上で指定してください。"
        )

    if max_steps > MAX_MAX_STEPS:
        raise MissionRepairCycleRunnerError(
            (
                "max_stepsが安全上限を超えています。"
                f" maximum={MAX_MAX_STEPS}"
            )
        )

    return max_steps


def _step_state_fingerprint(
    step: dict[str, Any],
) -> str:
    value = {
        "stage": step.get("stage"),
        "outcome": step.get("outcome"),
        "executed": step.get("executed"),
        "duplicate": step.get("duplicate"),
        "request_status_before": (
            step.get(
                "request_status_before"
            )
        ),
        "request_status_after": (
            step.get(
                "request_status_after"
            )
        ),
        "next_stage": step.get(
            "next_stage"
        ),
    }

    return _sha256_json(value)


def _determine_stop_reason(
    step: dict[str, Any],
) -> str | None:
    stage = step.get("stage")
    outcome = step.get("outcome")
    executed = step.get("executed")
    duplicate = step.get("duplicate")

    if stage in TERMINAL_STAGES:
        return "CYCLE_COMPLETED"

    if outcome in TERMINAL_OUTCOMES:
        if stage == "CYCLE_COMPLETED":
            return "CYCLE_COMPLETED"

    if stage in WAITING_STAGES:
        return "WAIT_APPROVAL"

    if outcome in WAITING_OUTCOMES:
        return "WAIT_APPROVAL"

    if stage in BLOCKED_STAGES:
        return "STATE_BLOCKED"

    if outcome in BLOCKED_OUTCOMES:
        return "STATE_BLOCKED"

    if duplicate is True:
        return "DUPLICATE_STEP"

    if executed is False:
        return "NO_PROGRESS"

    return None


def _load_run_history(
    mission_id: int,
) -> list[dict[str, Any]]:
    data = _load_json(
        _mission_directory(mission_id)
        / "repair-cycle-run-history.json"
    )

    if not isinstance(data, dict):
        return []

    history = data.get("runs")

    if not isinstance(history, list):
        return []

    return [
        item
        for item in history
        if isinstance(item, dict)
    ][-MAX_RUN_HISTORY:]


def _save_run_history(
    *,
    mission_id: int,
    run_record: dict[str, Any],
) -> Path:
    mission_dir = _mission_directory(
        mission_id
    )

    path = (
        mission_dir
        / "repair-cycle-run-history.json"
    )

    history = _load_run_history(
        mission_id
    )

    history.append(run_record)

    history = history[
        -MAX_RUN_HISTORY:
    ]

    payload = {
        "runner_version": (
            REPAIR_CYCLE_RUNNER_VERSION
        ),
        "mission_id": mission_id,
        "updated_at": _now(),
        "latest_run": run_record,
        "runs": history,
    }

    _write_json_atomic(
        path,
        payload,
    )

    return path


def run_repair_cycle(
    *,
    mission_id: int,
    max_steps: int | None = None,
) -> dict[str, Any]:
    safe_max_steps = _validate_max_steps(
        max_steps
    )

    mission = get_mission(
        mission_id
    )

    started_at = _now()

    run_seed = {
        "mission_id": mission_id,
        "started_at": started_at,
        "max_steps": safe_max_steps,
        "runner_version": (
            REPAIR_CYCLE_RUNNER_VERSION
        ),
    }

    run_id = (
        "repair-cycle-run-"
        + _sha256_json(run_seed)[:16]
    )

    steps: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()

    stop_reason: str | None = None
    error_detail: str | None = None

    for index in range(
        1,
        safe_max_steps + 1,
    ):
        try:
            step = (
                run_repair_cycle_step_safe(
                    mission_id
                )
            )
        except (
            MissionRepairCycleOrchestratorError,
            MissionError,
        ) as error:
            stop_reason = "STEP_ERROR"
            error_detail = str(error)

            steps.append(
                {
                    "step_number": index,
                    "stage": "STEP_ERROR",
                    "executed": False,
                    "duplicate": False,
                    "outcome": "ERROR",
                    "reason": str(error),
                }
            )

            break

        if not isinstance(step, dict):
            stop_reason = "STEP_ERROR"
            error_detail = (
                "Repair Cycle Stepの戻り値が"
                "辞書ではありません。"
            )

            steps.append(
                {
                    "step_number": index,
                    "stage": "STEP_ERROR",
                    "executed": False,
                    "duplicate": False,
                    "outcome": "ERROR",
                    "reason": error_detail,
                }
            )

            break

        step_record = {
            "step_number": index,
            "stage": step.get("stage"),
            "executed": step.get(
                "executed"
            ),
            "duplicate": step.get(
                "duplicate"
            ),
            "outcome": step.get(
                "outcome"
            ),
            "reason": step.get(
                "reason"
            ),
            "request_status_before": (
                step.get(
                    "request_status_before"
                )
            ),
            "request_status_after": (
                step.get(
                    "request_status_after"
                )
            ),
            "next_stage": step.get(
                "next_stage"
            ),
            "step_id": step.get(
                "step_id"
            ),
        }

        fingerprint = (
            _step_state_fingerprint(
                step
            )
        )

        step_record[
            "state_fingerprint"
        ] = fingerprint

        steps.append(step_record)

        immediate_stop = (
            _determine_stop_reason(
                step
            )
        )

        if immediate_stop is not None:
            stop_reason = immediate_stop
            break

        if fingerprint in seen_fingerprints:
            stop_reason = (
                "REPEATED_STATE"
            )
            break

        seen_fingerprints.add(
            fingerprint
        )

    if stop_reason is None:
        stop_reason = (
            "MAX_STEPS_REACHED"
        )

    if stop_reason not in STOP_REASONS:
        raise MissionRepairCycleRunnerError(
            (
                "不明なRunner停止理由です。"
                f" stop_reason={stop_reason}"
            )
        )

    completed_at = _now()

    executed_step_count = sum(
        1
        for step in steps
        if step.get("executed") is True
    )

    blocked = stop_reason in {
        "STATE_BLOCKED",
        "STEP_ERROR",
        "REPEATED_STATE",
        "NO_PROGRESS",
    }

    completed = (
        stop_reason
        == "CYCLE_COMPLETED"
    )

    waiting_approval = (
        stop_reason
        == "WAIT_APPROVAL"
    )

    bounded = (
        len(steps)
        <= safe_max_steps
    )

    run_record = {
        "run_id": run_id,
        "runner_version": (
            REPAIR_CYCLE_RUNNER_VERSION
        ),
        "mission_id": mission_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "max_steps": safe_max_steps,
        "step_count": len(steps),
        "executed_step_count": (
            executed_step_count
        ),
        "stop_reason": stop_reason,
        "completed": completed,
        "blocked": blocked,
        "waiting_approval": (
            waiting_approval
        ),
        "bounded": bounded,
        "error_detail": error_detail,
        "steps": steps,
        "safety": {
            "single_stage_orchestrator": True,
            "bounded_loop": True,
            "max_steps_enforced": True,
            "auto_apply_override": False,
            "retry_override": False,
            "stop_on_blocked": True,
            "stop_on_waiting_approval": True,
            "stop_on_duplicate": True,
            "stop_on_repeated_state": True,
        },
    }

    history_path = _save_run_history(
        mission_id=mission_id,
        run_record=run_record,
    )

    log_level = (
        "WARNING"
        if blocked
        else "INFO"
    )

    event_type = (
        "MISSION_REPAIR_CYCLE_RUN_BLOCKED"
        if blocked
        else (
            (
                "MISSION_REPAIR_CYCLE_RUN_"
                "WAITING_APPROVAL"
            )
            if waiting_approval
            else (
                "MISSION_REPAIR_CYCLE_RUN_COMPLETED"
            )
        )
    )

    add_mission_log(
        mission_id=mission_id,
        level=log_level,
        event_type=event_type,
        message=(
            "Repair Cycle Runnerを終了しました。"
            f" stop_reason={stop_reason}"
        ),
        metadata={
            "runner_version": (
                REPAIR_CYCLE_RUNNER_VERSION
            ),
            "run_id": run_id,
            "max_steps": safe_max_steps,
            "step_count": len(steps),
            "executed_step_count": (
                executed_step_count
            ),
            "stop_reason": stop_reason,
            "completed": completed,
            "blocked": blocked,
            "bounded": bounded,
            "auto_apply_override": False,
        },
    )

    return {
        "mission": mission,
        **run_record,
        "history_path": str(
            history_path
        ),
    }


def run_repair_cycle_safe(
    *,
    mission_id: int,
    max_steps: int | None = None,
) -> dict[str, Any]:
    try:
        return run_repair_cycle(
            mission_id=mission_id,
            max_steps=max_steps,
        )
    except (
        MissionRepairCycleRunnerError,
        MissionRepairCycleOrchestratorError,
        MissionError,
    ):
        raise
