from pathlib import Path
from unittest.mock import patch

from app.missions.repair_verification_runner import (
    run_repair_verification,
)


MISSION_ID = 36
PATCH_SHA256 = "b" * 64


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "Fixture",
        "title": "Repair Verification Failure",
        "objective": "Verify rollback handling",
        "status": "RUNNING",
        "progress": 85,
        "tasks": [
            {
                "task_type": "APPROVAL",
                "status": "COMPLETED",
            },
            {
                "task_type": "IMPLEMENTATION",
                "status": "COMPLETED",
            },
            {
                "task_type": "VERIFICATION",
                "status": "PENDING",
            },
        ],
    }


def _applied_request():
    return {
        "mission_id": MISSION_ID,
        "request_id": "request-failed-1",
        "repair_plan_id": "plan-failed-1",
        "status": "PATCH_APPLIED",
        "patch_generated": True,
        "patch_checked": True,
        "patch_applied": True,
        "auto_apply": False,
        "failure_source": "IMPLEMENTATION_PATCH",
        "failure_category": "PATCH",
        "apply_result": {
            "patch_sha256": PATCH_SHA256,
            "changed_file_count": 1,
            "changed_files": [
                "src/calculator.py",
            ],
            "rolled_back": False,
            "implementation_mode": "PATCH_APPLIED",
        },
    }


def _failed_verification_result():
    return {
        "mission": _mission(),
        "verification": {
            "verification_version": (
                "mission-verification-v0.1"
            ),
            "passed": False,
            "failure_category": "TEST",
            "requested_command_count": 2,
            "executed_command_count": 2,
            "results": [
                {
                    "name": "python-compile",
                    "category": "SYNTAX",
                    "passed": True,
                    "failure_category": None,
                    "returncode": 0,
                    "timed_out": False,
                },
                {
                    "name": "pytest",
                    "category": "TEST",
                    "passed": False,
                    "failure_category": "TEST",
                    "returncode": 1,
                    "timed_out": False,
                },
            ],
            "rollback": {
                "performed": True,
                "succeeded": True,
            },
        },
    }


def test_failed_repair_verification_records_rollback(
    tmp_path,
):
    mission_dir = tmp_path / "mission-36"
    mission_dir.mkdir(parents=True)

    state = {
        "request": _applied_request(),
    }

    def save_request(
        *,
        mission_id,
        request_id,
        suffix,
        repair_request,
    ):
        assert mission_id == MISSION_ID
        assert request_id == "request-failed-1"
        assert suffix == "failed"

        state["request"] = dict(
            repair_request
        )

        return {
            "latest_path": str(
                mission_dir / "repair-request.json"
            ),
            "archive_path": str(
                mission_dir
                / "patch-request-"
                "request-failed-1-failed.json"
            ),
        }

    with (
        patch(
            "app.missions.repair_verification_runner."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_verification_runner."
            "_load_existing_request",
            return_value=state["request"],
        ),
        patch(
            "app.missions.repair_verification_runner."
            "run_mission_verification_safe",
            return_value=(
                _failed_verification_result()
            ),
        ) as verification_mock,
        patch(
            "app.missions.repair_verification_runner."
            "_save_updated_request",
            side_effect=save_request,
        ),
        patch(
            "app.missions.repair_verification_runner."
            "add_mission_log",
        ) as log_mock,
    ):
        result = run_repair_verification(
            mission_id=MISSION_ID
        )

    request = result["repair_request"]

    assert request["status"] == "REPAIR_FAILED"
    assert request[
        "repair_verification_passed"
    ] is False

    assert request["patch_generated"] is True
    assert request["patch_checked"] is True
    assert request["patch_applied"] is False

    assert request[
        "repair_patch_rolled_back"
    ] is True

    assert request["auto_apply"] is False
    assert request["retry_started"] is False

    assert request[
        "failure_source"
    ] == "IMPLEMENTATION_PATCH"

    summary = request["verification_result"]

    assert summary["passed"] is False
    assert summary[
        "failure_category"
    ] == "TEST"
    assert summary["result_count"] == 2
    assert len(
        summary["failed_results"]
    ) == 1

    failed = summary["failed_results"][0]

    assert failed["name"] == "pytest"
    assert failed["returncode"] == 1
    assert failed["timed_out"] is False

    verification_mock.assert_called_once_with(
        MISSION_ID
    )

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_VERIFICATION_FAILED"
        in event_types
    )
