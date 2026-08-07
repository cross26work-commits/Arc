import json
from unittest.mock import patch

from app.missions.self_repair_planner import (
    FAILURE_SOURCE_IMPLEMENTATION_PATCH,
    run_self_repair_planner,
)


def _mission_with_patch_failure():
    return {
        "id": 36,
        "project_id": 1,
        "project_name": "Fixture",
        "title": "Repair Patch Failure",
        "objective": "Repair failed patch",
        "status": "RUNNING",
        "tasks": [
            {
                "id": 1,
                "task_type": "IMPLEMENTATION",
                "status": "RUNNING",
                "result": json.dumps(
                    {
                        "mode": "PATCH_CHECKED",
                        "last_patch_failure": {
                            "stage": "PATCH_APPLY",
                            "failed_at": (
                                "2026-08-06T00:00:00"
                                "+00:00"
                            ),
                            "error": (
                                "patch does not apply"
                            ),
                            "failure_category": (
                                "PATCH"
                            ),
                            "failure_classification": {
                                "failure_category": (
                                    "PATCH"
                                ),
                                "classification_source": (
                                    "IMPLEMENTATION_"
                                    "PATCH_APPLY"
                                ),
                                "reason_code": (
                                    "PATCH_CONTENT_FAILURE"
                                ),
                                "confidence": 0.94,
                            },
                        },
                    }
                ),
            },
            {
                "id": 2,
                "task_type": "VERIFICATION",
                "status": "PENDING",
                "result": json.dumps(
                    {
                        "passed": None,
                        "results": [],
                    }
                ),
            },
        ],
    }


def test_planner_creates_plan_from_patch_failure(
    tmp_path,
):
    mission = _mission_with_patch_failure()

    with (
        patch(
            "app.missions.self_repair_planner."
            "get_mission",
            return_value=mission,
        ),
        patch(
            "app.missions.self_repair_planner."
            "REPAIR_PLAN_ROOT",
            tmp_path,
        ),
        patch(
            "app.missions.self_repair_planner."
            "add_mission_log"
        ) as log_mock,
    ):
        result = run_self_repair_planner(
            mission_id=36
        )

    repair_plan = result["repair_plan"]

    assert repair_plan[
        "failure_source"
    ] == FAILURE_SOURCE_IMPLEMENTATION_PATCH

    assert repair_plan[
        "verification"
    ]["failure_category"] == "PATCH"

    assert repair_plan[
        "repair_policy"
    ]["repair_action"] == (
        "REGENERATE_PATCH"
    )

    assert repair_plan[
        "failure_count"
    ] == 1

    assert repair_plan[
        "failures"
    ][0]["name"] == "PATCH_APPLY"

    log_mock.assert_called_once()

    metadata = (
        log_mock.call_args.kwargs[
            "metadata"
        ]
    )

    assert metadata[
        "failure_source"
    ] == FAILURE_SOURCE_IMPLEMENTATION_PATCH


def test_patch_failure_plan_duplicate_is_reused(
    tmp_path,
):
    mission = _mission_with_patch_failure()

    with (
        patch(
            "app.missions.self_repair_planner."
            "get_mission",
            return_value=mission,
        ),
        patch(
            "app.missions.self_repair_planner."
            "REPAIR_PLAN_ROOT",
            tmp_path,
        ),
        patch(
            "app.missions.self_repair_planner."
            "add_mission_log"
        ),
    ):
        first = run_self_repair_planner(
            mission_id=36
        )
        second = run_self_repair_planner(
            mission_id=36
        )

    assert (
        first["repair_plan"]["repair_plan_id"]
        == second["repair_plan"][
            "repair_plan_id"
        ]
    )

    assert second["storage"][
        "duplicate"
    ] is True
