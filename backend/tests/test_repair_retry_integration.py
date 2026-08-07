from unittest.mock import patch

from app.missions.retry_controller import (
    prepare_repair_retry,
)


MISSION_ID = 36


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "Fixture",
        "title": "Repair Retry Integration",
        "objective": "Prepare next repair retry",
        "status": "APPROVED",
        "progress": 80,
        "tasks": [
            {
                "task_type": "APPROVAL",
                "status": "COMPLETED",
            },
            {
                "task_type": "IMPLEMENTATION",
                "status": "READY",
            },
            {
                "task_type": "VERIFICATION",
                "status": "PENDING",
                "result": {
                    "passed": False,
                    "failure_category": "TEST",
                },
            },
        ],
    }


def _failed_request(
    *,
    retry_count: int = 0,
    max_retries: int = 3,
):
    return {
        "mission_id": MISSION_ID,
        "request_id": "request-retry-1",
        "repair_plan_id": "plan-original-1",
        "status": "REPAIR_FAILED",
        "failure_source": "IMPLEMENTATION_PATCH",
        "failure_category": "PATCH",
        "repair_verification_passed": False,
        "repair_patch_rolled_back": True,
        "patch_generated": True,
        "patch_checked": True,
        "patch_applied": False,
        "auto_apply": False,
        "retry_started": False,
        "retry_completed": False,
        "retry_exhausted": False,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "retry_history": [],
        "verification_result": {
            "passed": False,
            "failure_category": "TEST",
            "requested_command_count": 2,
            "executed_command_count": 2,
            "result_count": 2,
            "failed_results": [
                {
                    "name": "pytest",
                    "category": "TEST",
                    "failure_category": "TEST",
                    "returncode": 1,
                    "timed_out": False,
                }
            ],
        },
    }


def _planner_result():
    return {
        "repair_plan": {
            "repair_plan_id": "plan-retry-1",
            "mission_id": MISSION_ID,
            "failure_category": "TEST",
            "status": "PLANNED",
        },
        "storage": {
            "latest_path": (
                "data/repair_plans/"
                "mission-36/repair-plan.json"
            ),
            "duplicate": False,
        },
    }


def test_failed_repair_prepares_next_retry():
    request = _failed_request(
        retry_count=0,
        max_retries=3,
    )

    saved = {}

    def save_request(
        *,
        mission_id,
        request_id,
        suffix,
        repair_request,
    ):
        assert mission_id == MISSION_ID
        assert request_id == "request-retry-1"
        assert suffix == "retry-1-prepared"

        saved["request"] = dict(
            repair_request
        )

        return {
            "latest_path": (
                "data/repair_plans/"
                "mission-36/repair-request.json"
            ),
            "archive_path": (
                "data/repair_plans/"
                "mission-36/"
                "patch-request-request-retry-1-"
                "retry-1-prepared.json"
            ),
        }

    with (
        patch(
            "app.missions.retry_controller."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.retry_controller."
            "_load_existing_request",
            return_value=request,
        ),
        patch(
            "app.missions.retry_controller."
            "run_self_repair_planner_safe",
            return_value=_planner_result(),
        ) as planner_mock,
        patch(
            "app.missions.retry_controller."
            "_save_retry_request",
            side_effect=save_request,
        ),
        patch(
            "app.missions.retry_controller."
            "add_mission_log",
        ) as log_mock,
    ):
        result = prepare_repair_retry(
            mission_id=MISSION_ID,
            max_retries=3,
        )

    prepared = result["repair_request"]

    assert prepared["status"] == (
        "AWAITING_REPAIR_REQUEST"
    )
    assert prepared["retry_count"] == 1
    assert prepared["max_retries"] == 3
    assert prepared["retry_started"] is True
    assert prepared["retry_completed"] is False
    assert prepared["retry_exhausted"] is False

    assert prepared[
        "retry_repair_plan_id"
    ] == "plan-retry-1"

    assert prepared["patch_generated"] is False
    assert prepared["patch_checked"] is False
    assert prepared["patch_applied"] is False

    assert prepared[
        "repair_verification_passed"
    ] is None

    assert prepared[
        "repair_patch_rolled_back"
    ] is False

    assert prepared["auto_apply"] is False

    assert len(
        prepared["retry_history"]
    ) == 1

    history = prepared["retry_history"][0]

    assert history["retry_number"] == 1
    assert history[
        "previous_request_id"
    ] == "request-retry-1"
    assert history[
        "previous_failure_category"
    ] == "TEST"
    assert history[
        "previous_status"
    ] == "REPAIR_FAILED"
    assert history[
        "repair_plan_id"
    ] == "plan-retry-1"
    assert history["result"] == (
        "AWAITING_REPAIR_REQUEST"
    )

    assert result["retry"] == {
        "prepared": True,
        "exhausted": False,
        "duplicate": False,
        "retry_count": 1,
        "max_retries": 3,
    }

    planner_mock.assert_called_once_with(
        MISSION_ID
    )

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_RETRY_PREPARED"
        in event_types
    )

    assert saved["request"]["status"] == (
        "AWAITING_REPAIR_REQUEST"
    )


def test_failed_repair_stops_when_retry_exhausted():
    request = _failed_request(
        retry_count=1,
        max_retries=1,
    )

    saved = {}

    def save_request(
        *,
        mission_id,
        request_id,
        suffix,
        repair_request,
    ):
        assert mission_id == MISSION_ID
        assert request_id == "request-retry-1"
        assert suffix == "retry-exhausted"

        saved["request"] = dict(
            repair_request
        )

        return {
            "latest_path": (
                "data/repair_plans/"
                "mission-36/repair-request.json"
            ),
            "archive_path": (
                "data/repair_plans/"
                "mission-36/"
                "patch-request-request-retry-1-"
                "retry-exhausted.json"
            ),
        }

    with (
        patch(
            "app.missions.retry_controller."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.retry_controller."
            "_load_existing_request",
            return_value=request,
        ),
        patch(
            "app.missions.retry_controller."
            "run_self_repair_planner_safe",
        ) as planner_mock,
        patch(
            "app.missions.retry_controller."
            "_save_retry_request",
            side_effect=save_request,
        ),
        patch(
            "app.missions.retry_controller."
            "add_mission_log",
        ) as log_mock,
    ):
        result = prepare_repair_retry(
            mission_id=MISSION_ID,
            max_retries=1,
        )

    exhausted = result["repair_request"]

    assert exhausted["status"] == (
        "RETRY_EXHAUSTED"
    )
    assert exhausted["retry_count"] == 1
    assert exhausted["max_retries"] == 1
    assert exhausted["retry_started"] is False
    assert exhausted["retry_completed"] is False
    assert exhausted["retry_exhausted"] is True
    assert exhausted["auto_apply"] is False

    assert result["retry"] == {
        "prepared": False,
        "exhausted": True,
        "duplicate": False,
        "retry_count": 1,
        "max_retries": 1,
    }

    planner_mock.assert_not_called()

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_RETRY_EXHAUSTED"
        in event_types
    )

    assert saved["request"]["status"] == (
        "RETRY_EXHAUSTED"
    )
