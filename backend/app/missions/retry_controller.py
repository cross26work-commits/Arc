from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.repair_policy import (
    get_repair_policy,
)
from app.missions.repair_request_builder import (
    REPAIR_PLAN_ROOT,
    _latest_request_path,
    _load_existing_request,
    _write_json_atomic,
)
from app.missions.self_repair_planner import (
    ARC_ROOT,
    MissionSelfRepairPlannerError,
    run_self_repair_planner_safe,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRetryControllerError(Exception):
    """Repair Retry制御に失敗した場合の例外。"""


RETRY_CONTROLLER_VERSION = (
    "mission-retry-controller-v0.1"
)

DEFAULT_MAX_RETRIES = 3
MAX_ALLOWED_RETRIES = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        raise MissionRetryControllerError(
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


def _normalize_retry_count(
    value: Any,
) -> int:
    if isinstance(value, bool):
        return 0

    try:
        count = int(value)
    except (
        TypeError,
        ValueError,
    ):
        return 0

    return max(count, 0)


def _normalize_max_retries(
    value: Any,
) -> int:
    if value is None:
        return DEFAULT_MAX_RETRIES

    if isinstance(value, bool):
        raise MissionRetryControllerError(
            "max_retriesの形式が不正です。"
        )

    try:
        maximum = int(value)
    except (
        TypeError,
        ValueError,
    ) as error:
        raise MissionRetryControllerError(
            "max_retriesは整数で指定してください。"
        ) from error

    if maximum < 1:
        raise MissionRetryControllerError(
            "max_retriesは1以上で指定してください。"
        )

    if maximum > MAX_ALLOWED_RETRIES:
        raise MissionRetryControllerError(
            "max_retriesは10以下にしてください。"
        )

    return maximum


def _policy_retry_limit(
    repair_request: dict[str, Any],
) -> int:
    embedded_policy = repair_request.get(
        "repair_policy"
    )

    if isinstance(embedded_policy, dict):
        embedded_limit = embedded_policy.get(
            "max_retries"
        )

        if embedded_limit is not None:
            return _normalize_max_retries(
                embedded_limit
            )

    failure_category = repair_request.get(
        "failure_category"
    )

    return _normalize_max_retries(
        get_repair_policy(
            failure_category
        ).max_retries
    )


def _resolve_retry_limit(
    *,
    repair_request: dict[str, Any],
    requested_max_retries: int | None,
) -> int:
    policy_limit = _policy_retry_limit(
        repair_request
    )

    candidate = (
        requested_max_retries
        if requested_max_retries is not None
        else repair_request.get("max_retries")
    )

    if candidate is None:
        return policy_limit

    requested_limit = _normalize_max_retries(
        candidate
    )

    return min(
        requested_limit,
        policy_limit,
    )


def _validate_mission_state(
    mission: dict[str, Any],
) -> None:
    if mission["status"] != "APPROVED":
        raise MissionRetryControllerError(
            "Verification失敗後にRollback済みの"
            "APPROVED MissionのみRetry準備できます。"
        )

    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    if implementation_task["status"] != "READY":
        raise MissionRetryControllerError(
            "IMPLEMENTATION TaskがREADYではありません。"
        )

    if verification_task["status"] != "PENDING":
        raise MissionRetryControllerError(
            "VERIFICATION TaskがPENDINGではありません。"
        )

    if not verification_task.get("result"):
        raise MissionRetryControllerError(
            "最新Verification失敗結果がありません。"
        )


def _validate_repair_request(
    *,
    mission_id: int,
    repair_request: dict[str, Any],
) -> None:
    if repair_request.get("mission_id") != mission_id:
        raise MissionRetryControllerError(
            "Repair RequestのMission IDが一致しません。"
        )

    if repair_request.get("status") == (
        "RETRY_EXHAUSTED"
    ):
        return

    if repair_request.get("status") == (
        "AWAITING_REPAIR_REQUEST"
    ):
        return

    if repair_request.get("status") != (
        "REPAIR_FAILED"
    ):
        raise MissionRetryControllerError(
            "REPAIR_FAILED状態からのみ"
            "Retry準備を開始できます。"
        )

    if (
        repair_request.get(
            "repair_verification_passed"
        )
        is not False
    ):
        raise MissionRetryControllerError(
            "Repair Verification失敗状態を"
            "確認できません。"
        )

    if (
        repair_request.get(
            "repair_patch_rolled_back"
        )
        is not True
    ):
        raise MissionRetryControllerError(
            "Repair PatchのRollback完了を"
            "確認できません。"
        )

    if repair_request.get("auto_apply") is not False:
        raise MissionRetryControllerError(
            "Repair Requestのauto_applyが"
            "安全状態ではありません。"
        )


def _save_retry_request(
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


def prepare_repair_retry(
    *,
    mission_id: int,
    max_retries: int | None = None,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    repair_request = _load_existing_request(
        mission_id
    )

    if repair_request is None:
        raise MissionRetryControllerError(
            "Repair Requestが存在しません。"
        )

    _validate_repair_request(
        mission_id=mission_id,
        repair_request=repair_request,
    )

    retry_limit = _resolve_retry_limit(
        repair_request=repair_request,
        requested_max_retries=max_retries,
    )

    current_status = repair_request.get(
        "status"
    )

    if current_status == "AWAITING_REPAIR_REQUEST":
        return {
            "mission": mission,
            "repair_request": repair_request,
            "retry": {
                "prepared": True,
                "duplicate": True,
                "retry_count": (
                    repair_request.get(
                        "retry_count",
                        0,
                    )
                ),
                "max_retries": (
                    retry_limit
                ),
            },
        }

    if current_status == "RETRY_EXHAUSTED":
        return {
            "mission": mission,
            "repair_request": repair_request,
            "retry": {
                "prepared": False,
                "exhausted": True,
                "duplicate": True,
                "retry_count": (
                    repair_request.get(
                        "retry_count",
                        0,
                    )
                ),
                "max_retries": (
                    retry_limit
                ),
            },
        }

    _validate_mission_state(
        mission
    )

    retry_count = _normalize_retry_count(
        repair_request.get("retry_count")
    )

    request_id = str(
        repair_request.get("request_id")
        or ""
    ).strip()

    history = repair_request.get(
        "retry_history"
    )

    if not isinstance(history, list):
        history = []

    if retry_count >= retry_limit:
        exhausted_at = _now()

        exhausted_request = {
            **repair_request,
            "retry_controller_version": (
                RETRY_CONTROLLER_VERSION
            ),
            "status": "RETRY_EXHAUSTED",
            "retry_count": retry_count,
            "max_retries": retry_limit,
            "retry_started": False,
            "retry_completed": False,
            "retry_exhausted": True,
            "auto_apply": False,
            "exhausted_at": exhausted_at,
            "next_stage": (
                "人間による原因確認または"
                "AI Repair Editorの改善が必要"
            ),
        }

        storage = _save_retry_request(
            mission_id=mission_id,
            request_id=request_id,
            suffix="retry-exhausted",
            repair_request=exhausted_request,
        )

        add_mission_log(
            mission_id=mission_id,
            level="ERROR",
            event_type=(
                "MISSION_REPAIR_RETRY_EXHAUSTED"
            ),
            message=(
                "Repair Retry回数が上限へ"
                "到達したため自動処理を停止しました。"
            ),
            metadata={
                "retry_controller_version": (
                    RETRY_CONTROLLER_VERSION
                ),
                "request_id": request_id,
                "retry_count": retry_count,
                "max_retries": retry_limit,
                "retry_exhausted": True,
                "latest_path": (
                    storage["latest_path"]
                ),
            },
        )

        return {
            "mission": get_mission(
                mission_id
            ),
            "repair_request": (
                exhausted_request
            ),
            "retry": {
                "prepared": False,
                "exhausted": True,
                "duplicate": False,
                "retry_count": retry_count,
                "max_retries": retry_limit,
            },
            "storage": storage,
        }

    next_retry_count = retry_count + 1
    prepared_at = _now()

    try:
        planner_result = (
            run_self_repair_planner_safe(
                mission_id
            )
        )
    except MissionSelfRepairPlannerError as error:
        raise MissionRetryControllerError(
            "Retry用Repair Plan生成に"
            f"失敗しました: {error}"
        ) from error

    repair_plan = planner_result.get(
        "repair_plan"
    )

    if not isinstance(repair_plan, dict):
        raise MissionRetryControllerError(
            "Retry用Repair Plan結果が不正です。"
        )

    repair_plan_id = str(
        repair_plan.get("repair_plan_id")
        or ""
    ).strip()

    if not repair_plan_id:
        raise MissionRetryControllerError(
            "Retry用Repair Plan IDがありません。"
        )

    history_entry = {
        "retry_number": next_retry_count,
        "prepared_at": prepared_at,
        "previous_request_id": request_id,
        "previous_failure_category": (
            repair_request.get(
                "verification_result",
                {},
            ).get("failure_category")
        ),
        "previous_status": (
            repair_request.get("status")
        ),
        "repair_plan_id": repair_plan_id,
        "repair_plan_duplicate": (
            planner_result.get(
                "storage",
                {},
            ).get("duplicate", False)
        ),
        "result": (
            "AWAITING_REPAIR_REQUEST"
        ),
    }

    prepared_request = {
        **repair_request,
        "retry_controller_version": (
            RETRY_CONTROLLER_VERSION
        ),
        "status": (
            "AWAITING_REPAIR_REQUEST"
        ),
        "retry_count": next_retry_count,
        "max_retries": retry_limit,
        "retry_started": True,
        "retry_completed": False,
        "retry_exhausted": False,
        "retry_prepared_at": prepared_at,
        "retry_repair_plan_id": (
            repair_plan_id
        ),
        "retry_history": [
            *history,
            history_entry,
        ],
        "patch_generated": False,
        "patch_checked": False,
        "patch_applied": False,
        "repair_verification_passed": None,
        "repair_patch_rolled_back": False,
        "auto_apply": False,
        "next_stage": (
            "新しいRepair Editを指定して"
            "repair-requestを生成する"
        ),
    }

    storage = _save_retry_request(
        mission_id=mission_id,
        request_id=request_id,
        suffix=(
            f"retry-{next_retry_count}-prepared"
        ),
        repair_request=prepared_request,
    )

    add_mission_log(
        mission_id=mission_id,
        level="WARNING",
        event_type=(
            "MISSION_REPAIR_RETRY_PREPARED"
        ),
        message=(
            f"Repair Retry {next_retry_count}/"
            f"{retry_limit}を準備しました。"
            "新しい修正Editの生成待ちです。"
        ),
        metadata={
            "retry_controller_version": (
                RETRY_CONTROLLER_VERSION
            ),
            "previous_request_id": (
                request_id
            ),
            "repair_plan_id": (
                repair_plan_id
            ),
            "retry_count": (
                next_retry_count
            ),
            "max_retries": retry_limit,
            "retry_started": True,
            "auto_apply": False,
            "next_stage": (
                "REPAIR_REQUEST"
            ),
            "latest_path": (
                storage["latest_path"]
            ),
        },
    )

    return {
        "mission": get_mission(
            mission_id
        ),
        "repair_request": (
            prepared_request
        ),
        "repair_plan": repair_plan,
        "retry": {
            "prepared": True,
            "exhausted": False,
            "duplicate": False,
            "retry_count": (
                next_retry_count
            ),
            "max_retries": retry_limit,
        },
        "storage": storage,
    }


def prepare_repair_retry_safe(
    *,
    mission_id: int,
    max_retries: int | None = None,
) -> dict[str, Any]:
    try:
        return prepare_repair_retry(
            mission_id=mission_id,
            max_retries=max_retries,
        )
    except (
        MissionRetryControllerError,
        MissionError,
    ):
        raise
