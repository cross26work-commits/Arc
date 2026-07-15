from __future__ import annotations

from pathlib import Path
from typing import Any

from app.missions.repair_request_builder import (
    REPAIR_PLAN_ROOT,
    _latest_request_path,
    _load_existing_request,
    _write_json_atomic,
)
from app.missions.self_repair_planner import ARC_ROOT
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)
from app.missions.verification_runner import (
    MissionVerificationError,
    run_mission_verification_safe,
)


class MissionRepairVerificationError(Exception):
    """Repair後Verificationの実行失敗時に使用する例外。"""


REPAIR_VERIFICATION_VERSION = (
    "mission-repair-verification-v0.4"
)


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in mission.get("tasks", [])
            if item.get("task_type") == task_type
        ),
        None,
    )

    if task is None:
        raise MissionRepairVerificationError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _relative_to_arc(path: Path) -> str:
    resolved = path.resolve()

    try:
        return (
            resolved
            .relative_to(ARC_ROOT)
            .as_posix()
        )
    except ValueError:
        return resolved.as_posix()


def _validate_repair_request(
    *,
    mission_id: int,
    repair_request: dict[str, Any],
) -> None:
    if repair_request.get("mission_id") != mission_id:
        raise MissionRepairVerificationError(
            "Repair RequestのMission IDが一致しません。"
        )

    if (
        repair_request.get("status")
        == "REPAIR_VERIFIED"
        and repair_request.get(
            "repair_verification_passed"
        )
        is True
    ):
        return

    if repair_request.get("status") != "PATCH_APPLIED":
        raise MissionRepairVerificationError(
            "Patch適用済みRepair Requestのみ"
            "再Verificationできます。"
        )

    if repair_request.get("patch_generated") is not True:
        raise MissionRepairVerificationError(
            "Repair Patchが生成されていません。"
        )

    if repair_request.get("patch_checked") is not True:
        raise MissionRepairVerificationError(
            "Repair Patch Checkが完了していません。"
        )

    if repair_request.get("patch_applied") is not True:
        raise MissionRepairVerificationError(
            "Repair Patchが適用されていません。"
        )

    if repair_request.get("auto_apply") is not False:
        raise MissionRepairVerificationError(
            "Repair Requestのauto_applyが"
            "安全状態ではありません。"
        )

    apply_result = repair_request.get(
        "apply_result"
    )

    if not isinstance(apply_result, dict):
        raise MissionRepairVerificationError(
            "Repair Patch Apply結果がありません。"
        )

    if (
        apply_result.get("implementation_mode")
        != "PATCH_APPLIED"
    ):
        raise MissionRepairVerificationError(
            "Repair Request内のImplementation状態が"
            "PATCH_APPLIEDではありません。"
        )

    if apply_result.get("rolled_back") is True:
        raise MissionRepairVerificationError(
            "Rollback済みRepair Patchは"
            "再Verificationできません。"
        )


def _validate_mission_state(
    mission: dict[str, Any],
) -> None:
    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
        "VERIFYING",
    }:
        raise MissionRepairVerificationError(
            "Repair Verificationを実行できない"
            "Mission状態です。"
        )

    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    if implementation_task["status"] != "COMPLETED":
        raise MissionRepairVerificationError(
            "IMPLEMENTATION Taskが"
            "完了していません。"
        )

    if verification_task["status"] not in {
        "READY",
        "PENDING",
        "RUNNING",
    }:
        raise MissionRepairVerificationError(
            "VERIFICATION Taskが"
            "再実行可能状態ではありません。"
        )


def _verification_summary(
    verification: dict[str, Any],
) -> dict[str, Any]:
    results = verification.get("results")

    if not isinstance(results, list):
        results = []

    return {
        "verification_version": (
            verification.get(
                "verification_version"
            )
        ),
        "passed": verification.get("passed"),
        "failure_category": (
            verification.get(
                "failure_category"
            )
        ),
        "requested_command_count": (
            verification.get(
                "requested_command_count"
            )
        ),
        "executed_command_count": (
            verification.get(
                "executed_command_count"
            )
        ),
        "result_count": len(results),
        "failed_results": [
            {
                "name": item.get("name"),
                "category": item.get("category"),
                "failure_category": (
                    item.get(
                        "failure_category"
                    )
                ),
                "returncode": (
                    item.get("returncode")
                ),
                "timed_out": (
                    item.get("timed_out")
                ),
            }
            for item in results
            if isinstance(item, dict)
            and item.get("passed") is not True
        ],
    }


def _save_updated_request(
    *,
    mission_id: int,
    request_id: str,
    suffix: str,
    repair_request: dict[str, Any],
) -> dict[str, str]:
    latest_path = _latest_request_path(
        mission_id
    )

    archive_path = (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
        / (
            "patch-request-"
            f"{request_id or 'unknown'}"
            f"-{suffix}.json"
        )
    )

    _write_json_atomic(
        archive_path,
        repair_request,
    )
    _write_json_atomic(
        latest_path,
        repair_request,
    )

    return {
        "latest_path": (
            _relative_to_arc(latest_path)
        ),
        "archive_path": (
            _relative_to_arc(archive_path)
        ),
    }


def run_repair_verification(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    repair_request = _load_existing_request(
        mission_id
    )

    if repair_request is None:
        raise MissionRepairVerificationError(
            "Repair Requestが存在しません。"
        )

    if (
        repair_request.get("status")
        == "REPAIR_VERIFIED"
        and repair_request.get(
            "repair_verification_passed"
        )
        is True
    ):
        return {
            "mission": mission,
            "repair_request": repair_request,
            "duplicate": True,
        }

    _validate_repair_request(
        mission_id=mission_id,
        repair_request=repair_request,
    )

    _validate_mission_state(
        mission
    )

    request_id = str(
        repair_request.get("request_id")
        or ""
    ).strip()

    try:
        result = run_mission_verification_safe(
            mission_id
        )
    except MissionVerificationError as error:
        failed_request = {
            **repair_request,
            "repair_verification_version": (
                REPAIR_VERIFICATION_VERSION
            ),
            "status": (
                "REPAIR_VERIFICATION_ERROR"
            ),
            "repair_verification_passed": False,
            "verification_error": str(error),
            "patch_applied": True,
            "auto_apply": False,
            "next_stage": (
                "Verification実行エラーを解析する"
            ),
        }

        storage = _save_updated_request(
            mission_id=mission_id,
            request_id=request_id,
            suffix="verification-error",
            repair_request=failed_request,
        )

        add_mission_log(
            mission_id=mission_id,
            level="ERROR",
            event_type=(
                "MISSION_REPAIR_VERIFICATION_ERROR"
            ),
            message=(
                "Repair Patch適用後のVerificationで"
                "実行エラーが発生しました。"
            ),
            metadata={
                "repair_verification_version": (
                    REPAIR_VERIFICATION_VERSION
                ),
                "request_id": request_id,
                "error": str(error),
                "repair_verification_passed": False,
                "retry_started": False,
                "latest_path": (
                    storage["latest_path"]
                ),
            },
        )

        raise MissionRepairVerificationError(
            str(error)
        ) from error

    verification = result.get(
        "verification"
    )

    if not isinstance(verification, dict):
        raise MissionRepairVerificationError(
            "Verification結果が不正です。"
        )

    summary = _verification_summary(
        verification
    )

    passed = verification.get(
        "passed"
    )

    if passed is True:
        updated_request = {
            **repair_request,
            "repair_verification_version": (
                REPAIR_VERIFICATION_VERSION
            ),
            "status": "REPAIR_VERIFIED",
            "repair_verification_passed": True,
            "verification_error": None,
            "verification_result": summary,
            "patch_generated": True,
            "patch_checked": True,
            "patch_applied": True,
            "auto_apply": False,
            "retry_started": False,
            "next_stage": (
                "Commit Runnerを実行可能"
            ),
        }

        storage = _save_updated_request(
            mission_id=mission_id,
            request_id=request_id,
            suffix="verified",
            repair_request=updated_request,
        )

        add_mission_log(
            mission_id=mission_id,
            level="INFO",
            event_type=(
                "MISSION_REPAIR_VERIFICATION_COMPLETED"
            ),
            message=(
                "Repair Patch適用後のVerificationに"
                "成功しました。Retryは実行していません。"
            ),
            metadata={
                "repair_verification_version": (
                    REPAIR_VERIFICATION_VERSION
                ),
                "request_id": request_id,
                "passed": True,
                "failure_category": None,
                "executed_command_count": (
                    summary[
                        "executed_command_count"
                    ]
                ),
                "retry_started": False,
                "latest_path": (
                    storage["latest_path"]
                ),
            },
        )

        return {
            "mission": result["mission"],
            "repair_request": updated_request,
            "verification": verification,
            "storage": {
                **storage,
                "duplicate": False,
            },
        }

    if passed is False:
        updated_request = {
            **repair_request,
            "repair_verification_version": (
                REPAIR_VERIFICATION_VERSION
            ),
            "status": "REPAIR_FAILED",
            "repair_verification_passed": False,
            "verification_error": None,
            "verification_result": summary,
            "patch_generated": True,
            "patch_checked": True,
            "patch_applied": False,
            "repair_patch_rolled_back": True,
            "auto_apply": False,
            "retry_started": False,
            "next_stage": (
                "新しいRepair Planを生成する"
            ),
        }

        storage = _save_updated_request(
            mission_id=mission_id,
            request_id=request_id,
            suffix="failed",
            repair_request=updated_request,
        )

        add_mission_log(
            mission_id=mission_id,
            level="WARNING",
            event_type=(
                "MISSION_REPAIR_VERIFICATION_FAILED"
            ),
            message=(
                "Repair Patch適用後のVerificationに"
                "失敗し、既存Verification Runnerにより"
                "変更前状態へRollbackされました。"
                "Retryはまだ実行していません。"
            ),
            metadata={
                "repair_verification_version": (
                    REPAIR_VERIFICATION_VERSION
                ),
                "request_id": request_id,
                "passed": False,
                "failure_category": (
                    summary["failure_category"]
                ),
                "executed_command_count": (
                    summary[
                        "executed_command_count"
                    ]
                ),
                "repair_patch_rolled_back": True,
                "retry_started": False,
                "latest_path": (
                    storage["latest_path"]
                ),
            },
        )

        return {
            "mission": result["mission"],
            "repair_request": updated_request,
            "verification": verification,
            "rollback": result.get("rollback"),
            "implementation": result.get(
                "implementation"
            ),
            "storage": {
                **storage,
                "duplicate": False,
            },
        }

    raise MissionRepairVerificationError(
        "Verificationのpassed状態が不正です。"
    )


def run_repair_verification_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_repair_verification(
            mission_id
        )
    except (
        MissionRepairVerificationError,
        MissionError,
    ):
        raise
