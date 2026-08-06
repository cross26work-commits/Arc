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
)
from app.missions.repair_cycle_runner import (
    MissionRepairCycleRunnerError,
    run_repair_cycle_safe,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairSupervisorError(Exception):
    """Repair Supervisor処理失敗時の例外。"""


REPAIR_SUPERVISOR_VERSION = (
    "mission-repair-supervisor-v0.1"
)

MAX_SUPERVISION_HISTORY = 100

SUPPORTED_STOP_REASONS = {
    "CYCLE_COMPLETED",
    "WAIT_APPROVAL",
    "STATE_BLOCKED",
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
        raise MissionRepairSupervisorError(
            f"JSON読込に失敗しました: {path}"
        ) from error

    if not isinstance(value, dict):
        raise MissionRepairSupervisorError(
            f"JSON形式が不正です: {path}"
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
        ) + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def _load_history(
    mission_id: int,
) -> list[dict[str, Any]]:
    data = _load_json(
        _mission_directory(mission_id)
        / "repair-supervisor-history.json"
    )

    if not isinstance(data, dict):
        return []

    records = data.get(
        "supervisions"
    )

    if not isinstance(records, list):
        return []

    return [
        item
        for item in records
        if isinstance(item, dict)
    ][-MAX_SUPERVISION_HISTORY:]


def _save_supervision(
    *,
    mission_id: int,
    record: dict[str, Any],
) -> tuple[Path, Path]:
    mission_directory = _mission_directory(
        mission_id
    )

    current_path = (
        mission_directory
        / "repair-supervisor.json"
    )

    history_path = (
        mission_directory
        / "repair-supervisor-history.json"
    )

    history = _load_history(
        mission_id
    )

    history.append(record)

    history = history[
        -MAX_SUPERVISION_HISTORY:
    ]

    _write_json_atomic(
        current_path,
        record,
    )

    _write_json_atomic(
        history_path,
        {
            "supervisor_version": (
                REPAIR_SUPERVISOR_VERSION
            ),
            "mission_id": mission_id,
            "updated_at": _now(),
            "supervision_count": len(history),
            "latest_supervision": record,
            "supervisions": history,
        },
    )

    return (
        current_path,
        history_path,
    )


def _decision_for_run(
    cycle: dict[str, Any],
) -> dict[str, Any]:
    stop_reason = str(
        cycle.get(
            "stop_reason",
            "",
        )
    ).strip().upper()

    if stop_reason not in SUPPORTED_STOP_REASONS:
        raise MissionRepairSupervisorError(
            (
                "未対応のRepair Cycle停止理由です。"
                f" stop_reason={stop_reason}"
            )
        )

    if stop_reason == "CYCLE_COMPLETED":
        return {
            "supervisor_status": (
                "REPAIR_COMPLETED"
            ),
            "decision": (
                "READY_FOR_COMMIT_REVIEW"
            ),
            "recommended_action": (
                "REVIEW_AND_COMMIT"
            ),
            "requires_master_action": True,
            "can_continue": False,
            "severity": "INFO",
            "reason": (
                "Repair Cycleが完了しました。"
                " Commit前レビューが必要です。"
            ),
        }

    if stop_reason == "WAIT_APPROVAL":
        return {
            "supervisor_status": (
                "WAITING_MASTER_APPROVAL"
            ),
            "decision": (
                "MASTER_APPROVAL_REQUIRED"
            ),
            "recommended_action": (
                "REVIEW_REPAIR_APPROVAL"
            ),
            "requires_master_action": True,
            "can_continue": False,
            "severity": "WARNING",
            "reason": (
                "Execution Policyによる"
                "マスター承認待ちです。"
            ),
        }

    if stop_reason == "STATE_BLOCKED":
        latest_step = cycle.get(
            "latest_step"
        )

        if not isinstance(
            latest_step,
            dict,
        ):
            steps = cycle.get("steps")

            if (
                isinstance(steps, list)
                and steps
                and isinstance(
                    steps[-1],
                    dict,
                )
            ):
                latest_step = steps[-1]

        repair_action = (
            latest_step.get(
                "repair_action"
            )
            if isinstance(
                latest_step,
                dict,
            )
            else None
        )

        resume_stage = (
            latest_step.get(
                "resume_stage"
            )
            if isinstance(
                latest_step,
                dict,
            )
            else None
        )

        if (
            repair_action
            == "STOP_AND_INSPECT"
            or resume_stage == "STOPPED"
        ):
            return {
                "supervisor_status": (
                    "REVIEW_REQUIRED"
                ),
                "decision": (
                    "REPAIR_POLICY_INSPECTION_REQUIRED"
                ),
                "recommended_action": (
                    "INSPECT_FAILURE_AND_POLICY"
                ),
                "requires_master_action": True,
                "can_continue": False,
                "severity": "WARNING",
                "reason": (
                    "Repair Policy???"
                    "??????????????"
                ),
            }

    if stop_reason == "MAX_STEPS_REACHED":
        return {
            "supervisor_status": (
                "CONTINUATION_AVAILABLE"
            ),
            "decision": (
                "SAFE_CONTINUATION_AVAILABLE"
            ),
            "recommended_action": (
                "RUN_REPAIR_SUPERVISOR_AGAIN"
            ),
            "requires_master_action": False,
            "can_continue": True,
            "severity": "INFO",
            "reason": (
                "安全Step上限へ到達しました。"
                " 状態を更新後、再監督できます。"
            ),
        }

    if stop_reason == "DUPLICATE_STEP":
        return {
            "supervisor_status": (
                "STATE_REFRESH_REQUIRED"
            ),
            "decision": (
                "DUPLICATE_EXECUTION_STOPPED"
            ),
            "recommended_action": (
                "REFRESH_REPAIR_STATE"
            ),
            "requires_master_action": False,
            "can_continue": False,
            "severity": "WARNING",
            "reason": (
                "同一Stageの重複実行を停止しました。"
            ),
        }

    if stop_reason == "NO_PROGRESS":
        return {
            "supervisor_status": (
                "REVIEW_REQUIRED"
            ),
            "decision": (
                "NO_PROGRESS_DETECTED"
            ),
            "recommended_action": (
                "INSPECT_REPAIR_STATE"
            ),
            "requires_master_action": True,
            "can_continue": False,
            "severity": "WARNING",
            "reason": (
                "Repair Cycleに進捗がありません。"
            ),
        }

    if stop_reason == "REPEATED_STATE":
        return {
            "supervisor_status": (
                "REVIEW_REQUIRED"
            ),
            "decision": (
                "REPEATED_STATE_DETECTED"
            ),
            "recommended_action": (
                "INSPECT_STATE_LOOP"
            ),
            "requires_master_action": True,
            "can_continue": False,
            "severity": "ERROR",
            "reason": (
                "Repair Cycleの状態ループを検出しました。"
            ),
        }

    if stop_reason == "STEP_ERROR":
        return {
            "supervisor_status": (
                "REVIEW_REQUIRED"
            ),
            "decision": (
                "STEP_ERROR_DETECTED"
            ),
            "recommended_action": (
                "INSPECT_STEP_ERROR"
            ),
            "requires_master_action": True,
            "can_continue": False,
            "severity": "ERROR",
            "reason": (
                "Repair Cycle Stageで"
                "エラーが発生しました。"
            ),
        }

    if stop_reason == "STATE_BLOCKED":
        return {
            "supervisor_status": (
                "REPAIR_BLOCKED"
            ),
            "decision": (
                "HUMAN_OR_AI_REVIEW_REQUIRED"
            ),
            "recommended_action": (
                "REVIEW_BLOCKED_REPAIR"
            ),
            "requires_master_action": True,
            "can_continue": False,
            "severity": "ERROR",
            "reason": (
                "Repair Cycleが安全上の理由で"
                "ブロックされました。"
            ),
        }

    raise MissionRepairSupervisorError(
        (
            "Repair Supervisor判定に"
            "到達できませんでした。"
        )
    )


def supervise_repair(
    *,
    mission_id: int,
    max_steps: int | None = None,
) -> dict[str, Any]:
    mission_before = get_mission(
        mission_id
    )

    cycle = run_repair_cycle_safe(
        mission_id=mission_id,
        max_steps=max_steps,
    )

    if not isinstance(cycle, dict):
        raise MissionRepairSupervisorError(
            "Repair Cycle結果が辞書ではありません。"
        )

    decision = _decision_for_run(
        cycle
    )

    created_at = _now()

    seed = {
        "mission_id": mission_id,
        "cycle_run_id": cycle.get(
            "run_id"
        ),
        "stop_reason": cycle.get(
            "stop_reason"
        ),
        "decision": decision.get(
            "decision"
        ),
        "created_at": created_at,
    }

    record = {
        "supervision_id": (
            "repair-supervision-"
            + _sha256_json(seed)[:20]
        ),
        "supervisor_version": (
            REPAIR_SUPERVISOR_VERSION
        ),
        "mission_id": mission_id,
        "created_at": created_at,
        "cycle_run_id": cycle.get(
            "run_id"
        ),
        "cycle_runner_version": cycle.get(
            "runner_version"
        ),
        "cycle_stop_reason": cycle.get(
            "stop_reason"
        ),
        "cycle_step_count": cycle.get(
            "step_count"
        ),
        "cycle_executed_step_count": (
            cycle.get(
                "executed_step_count"
            )
        ),
        "cycle_completed": cycle.get(
            "completed"
        ),
        "cycle_blocked": cycle.get(
            "blocked"
        ),
        "cycle_waiting_approval": cycle.get(
            "waiting_approval"
        ),
        **decision,
        "safety": {
            "bounded_cycle_execution": True,
            "master_approval_override": False,
            "automatic_commit": False,
            "automatic_reporting": False,
            "automatic_approval": False,
            "force_apply": False,
            "skip_verification": False,
        },
    }

    current_path, history_path = (
        _save_supervision(
            mission_id=mission_id,
            record=record,
        )
    )

    level = str(
        decision.get(
            "severity",
            "INFO",
        )
    ).upper()

    event_type = {
        "REPAIR_COMPLETED": (
            "MISSION_REPAIR_SUPERVISOR_COMPLETED"
        ),
        "WAITING_MASTER_APPROVAL": (
            "MISSION_REPAIR_SUPERVISOR_WAITING_APPROVAL"
        ),
        "CONTINUATION_AVAILABLE": (
            "MISSION_REPAIR_SUPERVISOR_CONTINUATION_AVAILABLE"
        ),
        "STATE_REFRESH_REQUIRED": (
            "MISSION_REPAIR_SUPERVISOR_REFRESH_REQUIRED"
        ),
        "REPAIR_BLOCKED": (
            "MISSION_REPAIR_SUPERVISOR_BLOCKED"
        ),
        "REVIEW_REQUIRED": (
            "MISSION_REPAIR_SUPERVISOR_REVIEW_REQUIRED"
        ),
    }.get(
        decision["supervisor_status"],
        "MISSION_REPAIR_SUPERVISOR_RECORDED",
    )

    add_mission_log(
        mission_id=mission_id,
        level=level,
        event_type=event_type,
        message=decision["reason"],
        metadata={
            "supervisor_version": (
                REPAIR_SUPERVISOR_VERSION
            ),
            "supervision_id": record[
                "supervision_id"
            ],
            "cycle_run_id": record[
                "cycle_run_id"
            ],
            "cycle_stop_reason": record[
                "cycle_stop_reason"
            ],
            "decision": record[
                "decision"
            ],
            "recommended_action": record[
                "recommended_action"
            ],
            "requires_master_action": record[
                "requires_master_action"
            ],
            "automatic_commit": False,
            "automatic_reporting": False,
            "automatic_approval": False,
        },
    )

    return {
        "mission_before": mission_before,
        "mission": get_mission(
            mission_id
        ),
        **record,
        "cycle": cycle,
        "state_path": str(
            current_path
        ),
        "history_path": str(
            history_path
        ),
    }


def supervise_repair_safe(
    *,
    mission_id: int,
    max_steps: int | None = None,
) -> dict[str, Any]:
    try:
        return supervise_repair(
            mission_id=mission_id,
            max_steps=max_steps,
        )
    except (
        MissionRepairSupervisorError,
        MissionRepairCycleRunnerError,
        MissionRepairCycleOrchestratorError,
        MissionError,
    ):
        raise
    except Exception as error:
        raise MissionRepairSupervisorError(
            (
                "Repair Supervisorで"
                "予期しないエラーが発生しました。"
            )
        ) from error
