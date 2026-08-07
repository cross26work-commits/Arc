from pathlib import Path
from unittest.mock import patch

from app.missions.repair_patch_apply import (
    apply_repair_patch,
)
from app.missions.repair_verification_runner import (
    run_repair_verification,
)


MISSION_ID = 36
PATCH_SHA256 = "a" * 64


def _mission(
    *,
    implementation_status: str = "RUNNING",
    verification_status: str = "PENDING",
):
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "Fixture",
        "title": "Patch Apply Verification",
        "objective": "Verify repaired patch",
        "status": "RUNNING",
        "progress": 80,
        "tasks": [
            {
                "task_type": "APPROVAL",
                "status": "COMPLETED",
            },
            {
                "task_type": "IMPLEMENTATION",
                "status": implementation_status,
            },
            {
                "task_type": "VERIFICATION",
                "status": verification_status,
            },
        ],
    }


def _verification_mission():
    return _mission(
        implementation_status="COMPLETED",
        verification_status="PENDING",
    )


def _checked_request():
    return {
        "mission_id": MISSION_ID,
        "request_id": "request-patch-1",
        "repair_plan_id": "plan-patch-1",
        "status": "PATCH_CHECKED",
        "patch_generated": True,
        "patch_checked": True,
        "patch_applied": False,
        "auto_apply": False,
        "failure_source": "IMPLEMENTATION_PATCH",
        "failure_category": "PATCH",
        "patch_result": {
            "patch_applicable": True,
            "implementation_mode": "PATCH_CHECKED",
            "patch_sha256": PATCH_SHA256,
            "changed_file_count": 1,
            "changed_files": [
                "src/calculator.py",
            ],
            "operation_count": 1,
        },
    }


def _apply_result():
    return {
        "mission": _mission(),
        "patch_apply": {
            "patch_apply_version": (
                "mission-patch-apply-v0.1"
            ),
            "applied": True,
            "rolled_back": False,
            "patch_sha256": PATCH_SHA256,
            "changed_file_count": 1,
            "changed_files": [
                "src/calculator.py",
            ],
            "working_tree_clean": False,
            "applied_at": (
                "2026-08-06T00:00:00+00:00"
            ),
        },
        "implementation": {
            "mode": "PATCH_APPLIED",
        },
    }


def _verification_result():
    return {
        "mission": _mission(),
        "verification": {
            "verification_version": (
                "mission-verification-v0.1"
            ),
            "passed": True,
            "failure_category": None,
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
                    "passed": True,
                    "failure_category": None,
                    "returncode": 0,
                    "timed_out": False,
                },
            ],
        },
    }


def test_patch_apply_then_repair_verification_passes(
    tmp_path,
):
    mission_dir = tmp_path / "mission-36"
    mission_dir.mkdir(parents=True)

    state = {
        "request": _checked_request(),
    }

    def load_request(_mission_id):
        return dict(state["request"])

    def write_json(path, payload):
        path = Path(path)

        if path.name == "repair-request.json":
            state["request"] = dict(payload)

    def save_verified_request(
        *,
        mission_id,
        request_id,
        suffix,
        repair_request,
    ):
        assert mission_id == MISSION_ID
        assert request_id == "request-patch-1"
        assert suffix == "verified"

        state["request"] = dict(
            repair_request
        )

        return {
            "latest_path": (
                str(
                    mission_dir
                    / "repair-request.json"
                )
            ),
            "archive_path": (
                str(
                    mission_dir
                    / "patch-request-"
                    "request-patch-1-verified.json"
                )
            ),
        }

    with (
        patch(
            "app.missions.repair_patch_apply."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_patch_apply."
            "_load_existing_request",
            side_effect=load_request,
        ),
        patch(
            "app.missions.repair_patch_apply."
            "apply_mission_implementation_patch_safe",
            return_value=_apply_result(),
        ) as apply_mock,
        patch(
            "app.missions.repair_patch_apply."
            "_latest_request_path",
            return_value=(
                mission_dir
                / "repair-request.json"
            ),
        ),
        patch(
            "app.missions.repair_patch_apply."
            "REPAIR_PLAN_ROOT",
            tmp_path,
        ),
        patch(
            "app.missions.repair_patch_apply."
            "_write_json_atomic",
            side_effect=write_json,
        ),
        patch(
            "app.missions.repair_patch_apply."
            "add_mission_log",
        ),
        patch(
            "app.missions.repair_verification_runner."
            "get_mission",
            return_value=_verification_mission(),
        ),
        patch(
            "app.missions.repair_verification_runner."
            "_load_existing_request",
            side_effect=load_request,
        ),
        patch(
            "app.missions.repair_verification_runner."
            "run_mission_verification_safe",
            return_value=_verification_result(),
        ) as verification_mock,
        patch(
            "app.missions.repair_verification_runner."
            "_save_updated_request",
            side_effect=save_verified_request,
        ),
        patch(
            "app.missions.repair_verification_runner."
            "add_mission_log",
        ),
    ):
        applied = apply_repair_patch(
            mission_id=MISSION_ID,
            decided_by="arc-test",
            note="Patch repair integration test",
        )

        applied_request = applied[
            "repair_request"
        ]

        assert applied_request["status"] == (
            "PATCH_APPLIED"
        )
        assert applied_request[
            "patch_generated"
        ] is True
        assert applied_request[
            "patch_checked"
        ] is True
        assert applied_request[
            "patch_applied"
        ] is True
        assert applied_request[
            "auto_apply"
        ] is False

        assert applied_request[
            "failure_source"
        ] == "IMPLEMENTATION_PATCH"

        verified = run_repair_verification(
            mission_id=MISSION_ID
        )

    verified_request = verified[
        "repair_request"
    ]

    assert verified_request["status"] == (
        "REPAIR_VERIFIED"
    )
    assert verified_request[
        "repair_verification_passed"
    ] is True
    assert verified_request[
        "patch_applied"
    ] is True
    assert verified_request[
        "retry_started"
    ] is False
    assert verified_request[
        "auto_apply"
    ] is False

    assert verified_request[
        "failure_source"
    ] == "IMPLEMENTATION_PATCH"

    summary = verified_request[
        "verification_result"
    ]

    assert summary["passed"] is True
    assert summary[
        "requested_command_count"
    ] == 2
    assert summary[
        "executed_command_count"
    ] == 2
    assert summary["result_count"] == 2
    assert summary["failed_results"] == []

    apply_mock.assert_called_once()
    verification_mock.assert_called_once_with(
        MISSION_ID
    )

    apply_payload = (
        apply_mock.call_args.kwargs[
            "payload"
        ]
    )

    assert apply_payload.confirmation == (
        "APPLY_PATCH"
    )
    assert (
        apply_payload.expected_patch_sha256
        == PATCH_SHA256
    )
