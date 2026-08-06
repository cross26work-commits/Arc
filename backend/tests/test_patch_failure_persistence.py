import json
from unittest.mock import patch

from app.missions.implementation_runner import (
    MissionImplementationError,
    _persist_patch_failure,
)


def _implementation_result():
    return {
        "mode": "PATCH_CHECKED",
        "step_execution": {
            "plan_id": "plan-1",
            "current_step_id": "step-1",
            "remaining_step_ids": [
                "step-1",
            ],
            "completed_step_ids": [],
            "results": {
                "step-1": {
                    "step_id": "step-1",
                    "status": "PATCH_READY",
                    "attempt_count": 1,
                    "metadata": {},
                },
            },
        },
    }


def _classified_error():
    return MissionImplementationError(
        "patch does not apply",
        failure_classification={
            "classifier_version": (
                "mission-failure-classifier-v0.1"
            ),
            "failure_category": "PATCH",
            "classification_source": (
                "IMPLEMENTATION_PATCH_APPLY"
            ),
            "reason_code": (
                "PATCH_CONTENT_FAILURE"
            ),
            "confidence": 0.94,
        },
    )


def test_persist_patch_failure_updates_task_and_log():
    captured = {}

    def fake_update_mission_task(
        *,
        mission_id,
        task_id,
        payload,
    ):
        captured["mission_id"] = mission_id
        captured["task_id"] = task_id
        captured["payload"] = payload
        return {"id": mission_id}

    with (
        patch(
            "app.missions.implementation_runner."
            "update_mission_task",
            side_effect=fake_update_mission_task,
        ),
        patch(
            "app.missions.implementation_runner."
            "add_mission_log",
        ) as log_mock,
        patch(
            "app.missions.implementation_runner."
            "_mark_step_patch_failed",
            side_effect=lambda **kwargs: {
                **kwargs["implementation_result"],
                "step_execution": {
                    "current_step_id": "step-1",
                    "results": {
                        "step-1": {
                            "status": "FAILED",
                            "metadata": {
                                "failure_category": (
                                    "PATCH"
                                ),
                            },
                        },
                    },
                },
            },
        ),
    ):
        result = _persist_patch_failure(
            mission_id=36,
            implementation_task={
                "id": 101,
                "status": "RUNNING",
            },
            implementation_result=(
                _implementation_result()
            ),
            stage="PATCH_APPLY",
            error=_classified_error(),
        )

    assert result[
        "last_patch_failure"
    ]["failure_category"] == "PATCH"

    assert result[
        "last_patch_failure"
    ]["stage"] == "PATCH_APPLY"

    assert result["patch_failure_count"] == 1

    assert captured["mission_id"] == 36
    assert captured["task_id"] == 101
    assert captured["payload"].status == "RUNNING"

    stored = json.loads(
        captured["payload"].result
    )

    assert stored[
        "last_patch_failure"
    ]["failure_category"] == "PATCH"

    log_mock.assert_called_once()

    metadata = (
        log_mock.call_args.kwargs[
            "metadata"
        ]
    )

    assert metadata[
        "failure_category"
    ] == "PATCH"

    assert metadata[
        "stage"
    ] == "PATCH_APPLY"


def test_patch_failure_count_increments():
    implementation = _implementation_result()
    implementation["patch_failure_count"] = 2

    with (
        patch(
            "app.missions.implementation_runner."
            "update_mission_task"
        ),
        patch(
            "app.missions.implementation_runner."
            "add_mission_log"
        ),
        patch(
            "app.missions.implementation_runner."
            "_mark_step_patch_failed",
            side_effect=lambda **kwargs: (
                kwargs["implementation_result"]
            ),
        ),
    ):
        result = _persist_patch_failure(
            mission_id=36,
            implementation_task={
                "id": 101,
            },
            implementation_result=(
                implementation
            ),
            stage="PATCH_CHECK",
            error=_classified_error(),
        )

    assert result["patch_failure_count"] == 3
