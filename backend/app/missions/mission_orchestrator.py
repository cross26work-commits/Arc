from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from app.missions.analysis_runner import (
    MissionAnalysisError,
    run_mission_analysis,
)
from app.missions.analysis_reporting_runner import (
    MissionAnalysisReportingError,
    run_mission_analysis_reporting_safe,
)
from app.missions.code_generation_runner import (
    MissionCodeGenerationError,
    run_mission_code_generation_safe,
)
from app.missions.implementation_runner import (
    MissionImplementationError,
    create_mission_implementation_backup_safe,
    run_mission_implementation_safe,
)
from app.missions.planner_runner import (
    MissionPlannerError,
    run_mission_planner,
)
from app.missions.reporting_runner import (
    MissionReportingError,
    run_mission_reporting_safe,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)
from app.missions.verification_runner import (
    MissionVerificationError,
    run_mission_verification_safe,
)


class MissionOrchestratorError(Exception):
    """Mission全体のStage判定・単一Stage実行失敗。"""


MISSION_ORCHESTRATOR_VERSION = (
    "mission-orchestrator-v0.2"
)

AUTOMATIC_EXECUTION_STAGES = {
    "RUN_ANALYSIS",
    "RUN_PLANNING",
    "RUN_ANALYSIS_REPORTING",
    "RUN_IMPLEMENTATION_DRY_RUN",
    "RUN_IMPLEMENTATION_BACKUP",
    "RUN_CODE_GENERATION",
    "RUN_VERIFICATION",
    "RUN_REPORTING",
}

MASTER_ACTION_STAGES = {
    "WAIT_MISSION_APPROVAL",
    "WAIT_PATCH_APPLY_APPROVAL",
    "WAIT_COMMIT_APPROVAL",
}

TERMINAL_STAGES = {
    "MISSION_COMPLETED",
    "MISSION_FAILED",
    "MISSION_CANCELLED",
}

BLOCKED_STAGES = {
    "REPAIR_REQUIRED",
    "STATE_BLOCKED",
}


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _sha256_json(
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


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any] | None:
    return next(
        (
            task
            for task in mission.get("tasks", [])
            if task.get("task_type") == task_type
        ),
        None,
    )


def _load_task_result(
    task: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return None

    raw = task.get("result")

    if not raw:
        return None

    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str):
        return None

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(value, dict):
        return None

    return value


def _task_status(
    mission: dict[str, Any],
    task_type: str,
) -> str | None:
    task = _task_by_type(
        mission,
        task_type,
    )

    if task is None:
        return None

    value = task.get("status")

    if value is None:
        return None

    return str(value).strip().upper()


def _decision(
    *,
    stage: str,
    reason: str,
    recommended_action: str,
    requires_master_action: bool,
    executable: bool,
    severity: str,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "reason": reason,
        "recommended_action": (
            recommended_action
        ),
        "requires_master_action": (
            requires_master_action
        ),
        "executable": executable,
        "severity": severity,
    }


def determine_mission_stage(
    mission: dict[str, Any],
) -> dict[str, Any]:
    mission_status = str(
        mission.get("status")
        or ""
    ).strip().upper()

    mission_type = str(
        mission.get("mission_type")
        or "IMPLEMENTATION"
    ).strip().upper()

    if mission_type not in {
        "IMPLEMENTATION",
        "ANALYSIS",
    }:
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "????Mission Type??: "
                f"{mission_type or 'NONE'}"
            ),
            recommended_action=(
                "REPAIR_MISSION_TYPE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if mission_status == "COMPLETED":
        return _decision(
            stage="MISSION_COMPLETED",
            reason=(
                "Missionは既に完了しています。"
            ),
            recommended_action=(
                "REVIEW_FINAL_REPORT"
            ),
            requires_master_action=False,
            executable=False,
            severity="INFO",
        )

    if mission_status == "FAILED":
        return _decision(
            stage="MISSION_FAILED",
            reason=(
                "Missionは失敗状態です。"
            ),
            recommended_action=(
                "INSPECT_MISSION_FAILURE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if mission_status == "CANCELLED":
        return _decision(
            stage="MISSION_CANCELLED",
            reason=(
                "Missionは中止されています。"
            ),
            recommended_action=(
                "NO_ACTION"
            ),
            requires_master_action=False,
            executable=False,
            severity="INFO",
        )

    requirements_status = _task_status(
        mission,
        "REQUIREMENTS",
    )
    analysis_status = _task_status(
        mission,
        "ANALYSIS",
    )
    planning_status = _task_status(
        mission,
        "PLANNING",
    )
    approval_status = _task_status(
        mission,
        "APPROVAL",
    )
    implementation_status = _task_status(
        mission,
        "IMPLEMENTATION",
    )
    verification_status = _task_status(
        mission,
        "VERIFICATION",
    )
    reporting_status = _task_status(
        mission,
        "REPORTING",
    )
    analysis_reporting_status = _task_status(
        mission,
        "ANALYSIS_REPORTING",
    )

    if mission_type == "ANALYSIS":
        required_tasks = {
            "REQUIREMENTS": requirements_status,
            "ANALYSIS": analysis_status,
            "PLANNING": planning_status,
            "ANALYSIS_REPORTING": (
                analysis_reporting_status
            ),
        }
    else:
        required_tasks = {
            "REQUIREMENTS": requirements_status,
            "ANALYSIS": analysis_status,
            "PLANNING": planning_status,
            "APPROVAL": approval_status,
            "IMPLEMENTATION": implementation_status,
            "VERIFICATION": verification_status,
            "REPORTING": reporting_status,
        }

    missing = [
        task_type
        for task_type, status
        in required_tasks.items()
        if status is None
    ]

    if missing:
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "必須Mission Taskが"
                f"見つかりません: {missing}"
            ),
            recommended_action=(
                "REPAIR_MISSION_TASK_STRUCTURE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if requirements_status != "COMPLETED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "REQUIREMENTS Taskが"
                "完了していません。"
            ),
            recommended_action=(
                "COMPLETE_REQUIREMENTS"
            ),
            requires_master_action=True,
            executable=False,
            severity="WARNING",
        )

    if analysis_status in {
        "READY",
        "RUNNING",
    }:
        return _decision(
            stage="RUN_ANALYSIS",
            reason=(
                "ANALYSIS Taskが"
                "実行可能状態です。"
            ),
            recommended_action=(
                "RUN_ANALYSIS"
            ),
            requires_master_action=False,
            executable=True,
            severity="INFO",
        )

    if analysis_status == "FAILED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "ANALYSIS Taskが"
                "失敗しています。"
            ),
            recommended_action=(
                "RETRY_OR_INSPECT_ANALYSIS"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if analysis_status != "COMPLETED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "ANALYSIS Task状態が"
                f"未対応です: {analysis_status}"
            ),
            recommended_action=(
                "INSPECT_ANALYSIS_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if planning_status in {
        "READY",
        "RUNNING",
    }:
        return _decision(
            stage="RUN_PLANNING",
            reason=(
                "PLANNING Taskが"
                "実行可能状態です。"
            ),
            recommended_action=(
                "RUN_PLANNING"
            ),
            requires_master_action=False,
            executable=True,
            severity="INFO",
        )

    if planning_status == "FAILED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "PLANNING Taskが"
                "失敗しています。"
            ),
            recommended_action=(
                "RETRY_OR_INSPECT_PLANNING"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if planning_status != "COMPLETED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "PLANNING Task状態が"
                f"未対応です: {planning_status}"
            ),
            recommended_action=(
                "INSPECT_PLANNING_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if mission_type == "ANALYSIS":
        if analysis_reporting_status in {
            "READY",
            "RUNNING",
        }:
            return _decision(
                stage="RUN_ANALYSIS_REPORTING",
                reason=(
                    "ANALYSIS_REPORTING Task?????"
                    "?????????????"
                    "?????????????"
                ),
                recommended_action=(
                    "RUN_ANALYSIS_REPORTING"
                ),
                requires_master_action=False,
                executable=True,
                severity="INFO",
            )

        if analysis_reporting_status == "COMPLETED":
            return _decision(
                stage="MISSION_COMPLETED",
                reason=(
                    "ANALYSIS Mission?"
                    "?Task?????????"
                ),
                recommended_action=(
                    "REVIEW_ANALYSIS_REPORT"
                ),
                requires_master_action=False,
                executable=False,
                severity="INFO",
            )

        if analysis_reporting_status == "FAILED":
            return _decision(
                stage="STATE_BLOCKED",
                reason=(
                    "ANALYSIS_REPORTING Task?"
                    "????????"
                ),
                recommended_action=(
                    "RETRY_OR_INSPECT_ANALYSIS_REPORTING"
                ),
                requires_master_action=True,
                executable=False,
                severity="ERROR",
            )

        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "ANALYSIS_REPORTING Task???"
                "?????: "
                f"{analysis_reporting_status}"
            ),
            recommended_action=(
                "INSPECT_ANALYSIS_REPORTING_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if approval_status == "READY":
        return _decision(
            stage="WAIT_MISSION_APPROVAL",
            reason=(
                "実装計画に対する"
                "マスター承認が必要です。"
            ),
            recommended_action=(
                "APPROVE_OR_REJECT_MISSION"
            ),
            requires_master_action=True,
            executable=False,
            severity="WARNING",
        )

    if approval_status == "FAILED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "APPROVAL Taskが"
                "失敗状態です。"
            ),
            recommended_action=(
                "REVIEW_MISSION_REJECTION"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if approval_status != "COMPLETED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "APPROVAL Task状態が"
                f"未対応です: {approval_status}"
            ),
            recommended_action=(
                "INSPECT_APPROVAL_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    implementation = _load_task_result(
        implementation_task
    )
    implementation_mode = str(
        (
            implementation
            or {}
        ).get("mode")
        or ""
    ).strip().upper()

    if implementation_status == "READY":
        return _decision(
            stage=(
                "RUN_IMPLEMENTATION_DRY_RUN"
            ),
            reason=(
                "承認済みMissionの"
                "Implementation Dry Runを"
                "開始できます。"
            ),
            recommended_action=(
                "RUN_IMPLEMENTATION_DRY_RUN"
            ),
            requires_master_action=False,
            executable=True,
            severity="INFO",
        )

    if implementation_status == "RUNNING":
        if implementation_mode == "":
            return _decision(
                stage=(
                    "RUN_IMPLEMENTATION_DRY_RUN"
                ),
                reason=(
                    "Implementation Dry Runを"
                    "安全に再実行できます。"
                ),
                recommended_action=(
                    "RUN_IMPLEMENTATION_DRY_RUN"
                ),
                requires_master_action=False,
                executable=True,                severity="INFO",
            )

        if implementation_mode == "DRY_RUN":
            return _decision(
                stage="RUN_IMPLEMENTATION_BACKUP",
                reason=(
                    "Implementation Dry Run is complete. "
                    "The Backup Engine can now run."
                ),
                recommended_action=(
                    "RUN_IMPLEMENTATION_BACKUP"
                ),
                requires_master_action=False,
                executable=True,
                severity="INFO",
            )

        if implementation_mode == "BACKUP_READY":
            return _decision(
                stage="RUN_CODE_GENERATION",
                reason=(
                    "Implementation Backup is complete. "
                    "Code Generation can now run."
                ),
                recommended_action=(
                    "RUN_CODE_GENERATION"
                ),
                requires_master_action=False,
                executable=True,
                severity="INFO",
            )

        if implementation_mode == "PATCH_READY":
            return _decision(
                stage=(
                    "WAIT_PATCH_CHECK"
                ),
                reason=(
                    "Implementation Patchの"
                    "検証処理が必要です。"
                    "v0.1では自動Patch Checkを"
                    "実行しません。"
                ),
                recommended_action=(
                    "RUN_PATCH_CHECK"
                ),
                requires_master_action=True,
                executable=False,
                severity="WARNING",
            )

        if implementation_mode == "PATCH_CHECKED":
            return _decision(
                stage=(
                    "WAIT_PATCH_APPLY_APPROVAL"
                ),
                reason=(
                    "Patch検証は完了しています。"
                    "実適用には明示承認が必要です。"
                ),
                recommended_action=(
                    "REVIEW_AND_APPLY_PATCH"
                ),
                requires_master_action=True,
                executable=False,
                severity="WARNING",
            )

        if implementation_mode == "ROLLED_BACK":
            return _decision(
                stage="REPAIR_REQUIRED",
                reason=(
                    "Implementationは"
                    "Rollbackされています。"
                ),
                recommended_action=(
                    "RUN_REPAIR_SUPERVISOR"
                ),
                requires_master_action=False,
                executable=False,
                severity="ERROR",
            )

        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "IMPLEMENTATION RUNNINGで"
                "未対応のmodeです:"
                f" {implementation_mode or 'NONE'}"
            ),
            recommended_action=(
                "INSPECT_IMPLEMENTATION_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if implementation_status == "FAILED":
        return _decision(
            stage="REPAIR_REQUIRED",
            reason=(
                "IMPLEMENTATION Taskが"
                "失敗しています。"
            ),
            recommended_action=(
                "RUN_REPAIR_SUPERVISOR"
            ),
            requires_master_action=False,
            executable=False,
            severity="ERROR",
        )

    if implementation_status != "COMPLETED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "IMPLEMENTATION Task状態が"
                f"未対応です: {implementation_status}"
            ),
            recommended_action=(
                "INSPECT_IMPLEMENTATION_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if implementation_mode == "COMMITTED":
        if reporting_status in {
            "READY",
            "RUNNING",
        }:
            return _decision(
                stage="RUN_REPORTING",
                reason=(
                    "Commit済み変更の"
                    "最終報告を実行できます。"
                ),
                recommended_action=(
                    "RUN_REPORTING"
                ),
                requires_master_action=False,
                executable=True,
                severity="INFO",
            )

        if reporting_status == "COMPLETED":
            return _decision(
                stage="MISSION_COMPLETED",
                reason=(
                    "CommitとReportingが"
                    "完了しています。"
                ),
                recommended_action=(
                    "REVIEW_FINAL_REPORT"
                ),
                requires_master_action=False,
                executable=False,
                severity="INFO",
            )

        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "Commit済みですがREPORTING Taskが"
                f"実行可能ではありません: {reporting_status}"
            ),
            recommended_action=(
                "INSPECT_REPORTING_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if implementation_mode == "ROLLED_BACK":
        return _decision(
            stage="REPAIR_REQUIRED",
            reason=(
                "Implementationは"
                "Verification失敗後に"
                "Rollbackされています。"
            ),
            recommended_action=(
                "RUN_REPAIR_SUPERVISOR"
            ),
            requires_master_action=False,
            executable=False,
            severity="ERROR",
        )

    if implementation_mode != "PATCH_APPLIED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "完了済みIMPLEMENTATIONのmodeが"
                "PATCH_APPLIEDまたはCOMMITTEDでは"
                f"ありません: {implementation_mode or 'NONE'}"
            ),
            recommended_action=(
                "INSPECT_IMPLEMENTATION_RESULT"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )
    verification = _load_task_result(
        verification_task
    )
    verification_passed = (
        verification or {}
    ).get("passed")

    if verification_status in {
        "READY",
        "RUNNING",
    }:
        return _decision(
            stage="RUN_VERIFICATION",
            reason=(
                "適用済みPatchの"
                "Verificationを実行できます。"
            ),
            recommended_action=(
                "RUN_VERIFICATION"
            ),
            requires_master_action=False,
            executable=True,
            severity="INFO",
        )

    if verification_status == "PENDING":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "IMPLEMENTATION完了後ですが"
                "VERIFICATION TaskがPENDINGです。"
            ),
            recommended_action=(
                "REFRESH_MISSION_TASK_STATE"
            ),
            requires_master_action=False,
            executable=False,
            severity="WARNING",
        )

    if verification_status == "FAILED":
        return _decision(
            stage="REPAIR_REQUIRED",
            reason=(
                "Verificationに失敗しました。"
                "Repair経路が必要です。"
            ),
            recommended_action=(
                "RUN_REPAIR_SUPERVISOR"
            ),
            requires_master_action=False,
            executable=False,
            severity="ERROR",
        )

    if verification_status != "COMPLETED":
        return _decision(
            stage="STATE_BLOCKED",
            reason=(
                "VERIFICATION Task状態が"
                f"未対応です: {verification_status}"
            ),
            recommended_action=(
                "INSPECT_VERIFICATION_STATE"
            ),
            requires_master_action=True,
            executable=False,
            severity="ERROR",
        )

    if verification_passed is not True:
        return _decision(
            stage="REPAIR_REQUIRED",
            reason=(
                "VERIFICATION Taskは完了していますが"
                "passed=Trueではありません。"
            ),
            recommended_action=(
                "RUN_REPAIR_SUPERVISOR"
            ),
            requires_master_action=False,
            executable=False,
            severity="ERROR",
        )

    if reporting_status == "COMPLETED":
        return _decision(
            stage="MISSION_COMPLETED",
            reason=(
                "REPORTING Taskまで"
                "完了しています。"
            ),
            recommended_action=(
                "REVIEW_FINAL_REPORT"
            ),
            requires_master_action=False,
            executable=False,
            severity="INFO",
        )

    return _decision(
        stage="WAIT_COMMIT_APPROVAL",
        reason=(
            "ImplementationとVerificationが"
            "成功しています。"
            "Commitには明示確認が必要です。"
        ),
        recommended_action=(
            "REVIEW_AND_COMMIT"
        ),
        requires_master_action=True,
        executable=False,
        severity="WARNING",
    )


def _execute_stage(
    *,
    mission_id: int,
    stage: str,
) -> dict[str, Any]:
    handlers: dict[
        str,
        Callable[[], dict[str, Any]],
    ] = {
        "RUN_ANALYSIS": (
            lambda: run_mission_analysis(
                mission_id
            )
        ),
        "RUN_PLANNING": (
            lambda: run_mission_planner(
                mission_id
            )
        ),
        "RUN_IMPLEMENTATION_DRY_RUN": (
            lambda: (
                run_mission_implementation_safe(
                    mission_id
                )
            )
        ),
        "RUN_IMPLEMENTATION_BACKUP": (
            lambda: (
                create_mission_implementation_backup_safe(
                    mission_id
                )
            )
        ),
        "RUN_CODE_GENERATION": (
            lambda: (
                run_mission_code_generation_safe(
                    mission_id
                )
            )
        ),
        "RUN_VERIFICATION": (
            lambda: (
                run_mission_verification_safe(
                    mission_id
                )
            )
        ),
        "RUN_REPORTING": (
            lambda: (
                run_mission_reporting_safe(
                    mission_id
                )
            )
        ),
        "RUN_ANALYSIS_REPORTING": (
            lambda: (
                run_mission_analysis_reporting_safe(
                    mission_id
                )
            )
        ),
    }

    handler = handlers.get(stage)

    if handler is None:
        raise MissionOrchestratorError(
            "自動実行が許可されていない"
            f"Stageです: {stage}"
        )

    return handler()


def orchestrate_mission_step(
    *,
    mission_id: int,
    execute: bool = False,
) -> dict[str, Any]:
    mission_before = get_mission(
        mission_id
    )

    decision = determine_mission_stage(
        mission_before
    )

    stage = decision["stage"]
    executed = False
    execution_result = None
    execution_error = None

    if execute:
        if stage not in (
            AUTOMATIC_EXECUTION_STAGES
        ):
            execution_error = (
                "Stageは自動実行対象ではありません。"
            )
        elif decision["executable"] is not True:
            execution_error = (
                "Stageは実行可能状態ではありません。"
            )
        else:
            try:
                execution_result = _execute_stage(
                    mission_id=mission_id,
                    stage=stage,
                )
                executed = True
            except (
                MissionAnalysisError,
                MissionAnalysisReportingError,
                MissionPlannerError,
                MissionImplementationError,
                MissionCodeGenerationError,
                MissionVerificationError,
                MissionReportingError,
                MissionError,
            ) as error:
                raise MissionOrchestratorError(
                    str(error)
                ) from error

    mission_after = get_mission(
        mission_id
    )

    next_decision = determine_mission_stage(
        mission_after
    )

    created_at = _now()

    seed = {
        "mission_id": mission_id,
        "stage": stage,
        "execute_requested": execute,
        "executed": executed,
        "created_at": created_at,
    }

    record = {
        "orchestration_id": (
            "mission-orchestration-"
            + _sha256_json(seed)[:20]
        ),
        "orchestrator_version": (
            MISSION_ORCHESTRATOR_VERSION
        ),
        "mission_id": mission_id,
        "created_at": created_at,
        "execute_requested": execute,
        "executed": executed,
        "stage": stage,
        "decision": decision,
        "execution_error": execution_error,
        "execution_result_summary": (
            {
                "keys": sorted(
                    execution_result.keys()
                )
            }
            if isinstance(
                execution_result,
                dict,
            )
            else None
        ),
        "next_stage": next_decision["stage"],
        "next_decision": next_decision,
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
            "single_stage_only": True,
            "automatic_mission_approval": False,
            "automatic_patch_apply": False,
            "automatic_commit": False,
            "automatic_repair_approval": False,
            "skip_verification": False,
            "force_apply": False,
            "force_commit": False,
        },
    }

    if executed:
        level = "INFO"
        event_type = (
            "MISSION_ORCHESTRATOR_STEP_EXECUTED"
        )
        message = (
            f"Mission Orchestratorが{stage}を"
            "1Stageだけ実行しました。"
        )
    elif decision["requires_master_action"]:
        level = "WARNING"
        event_type = (
            "MISSION_ORCHESTRATOR_WAITING_MASTER"
        )
        message = (
            "Mission Orchestratorは"
            f"{stage}でマスター操作を待機しています。"
        )
    elif stage in BLOCKED_STAGES:
        level = "ERROR"
        event_type = (
            "MISSION_ORCHESTRATOR_BLOCKED"
        )
        message = (
            "Mission Orchestratorは"
            f"{stage}で安全停止しました。"
        )
    elif stage in TERMINAL_STAGES:
        level = "INFO"
        event_type = (
            "MISSION_ORCHESTRATOR_TERMINAL"
        )
        message = (
            "Mission Orchestratorが"
            f"{stage}を確認しました。"
        )
    else:
        level = "INFO"
        event_type = (
            "MISSION_ORCHESTRATOR_INSPECTED"
        )
        message = (
            "Mission Orchestratorが"
            f"{stage}を判定しました。"
        )

    add_mission_log(
        mission_id=mission_id,
        level=level,
        event_type=event_type,
        message=message,
        metadata={
            "orchestration_id": (
                record["orchestration_id"]
            ),
            "orchestrator_version": (
                MISSION_ORCHESTRATOR_VERSION
            ),
            "stage": stage,
            "executed": executed,
            "next_stage": (
                next_decision["stage"]
            ),
            "requires_master_action": (
                decision[
                    "requires_master_action"
                ]
            ),
            "single_stage_only": True,
            "automatic_patch_apply": False,
            "automatic_commit": False,
        },
    )

    return {
        "mission": mission_after,
        "orchestration": record,
        "execution_result": (
            execution_result
            if executed
            else None
        ),
    }


def orchestrate_mission_step_safe(
    *,
    mission_id: int,
    execute: bool = False,
) -> dict[str, Any]:
    try:
        return orchestrate_mission_step(
            mission_id=mission_id,
            execute=execute,
        )
    except MissionOrchestratorError:
        raise
    except MissionError as error:
        raise MissionOrchestratorError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionOrchestratorError(
            "Mission Orchestratorで"
            "予期しないエラーが発生しました: "
            f"{error}"
        ) from error
