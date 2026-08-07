import json
from unittest.mock import patch

from app.missions.models import (
    MissionPatchEdit,
    MissionRepairRequestCreate,
)
from app.missions.repair_request_builder import (
    create_repair_patch_request,
)


def _mission():
    return {
        "id": 36,
        "project_id": 1,
        "project_name": "Fixture",
        "title": "Patch Repair",
        "objective": "Repair patch failure",
        "status": "RUNNING",
        "tasks": [
            {
                "id": 1,
                "task_type": "PLANNING",
                "status": "COMPLETED",
                "result": json.dumps(
                    {
                        "selected_files": [
                            {
                                "path": "src/calculator.py",
                            },
                        ],
                        "modified_files": [
                            "src/calculator.py",
                        ],
                        "implementation_plan": {
                            "steps": [
                                {
                                    "step_id": "step-1",
                                    "target_files": [
                                        "src/calculator.py",
                                    ],
                                }
                            ],
                        },
                    }
                ),
            },
            {
                "id": 2,
                "task_type": "APPROVAL",
                "status": "COMPLETED",
                "result": json.dumps(
                    {
                        "approved": True,
                    }
                ),
            },
            {
                "id": 3,
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
                "id": 4,
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


def _repair_plan():
    return {
        "repair_plan_id": "plan-patch-1",
        "status": "PLANNED",
        "auto_apply": False,
        "failure_source": (
            "IMPLEMENTATION_PATCH"
        ),
        "failure_source_version": (
            "implementation-patch-failure-v0.1"
        ),
        "verification_failure_signature": (
            "patch-signature-1"
        ),
        "verification": {
            "failure_category": "PATCH",
        },
        "suspected_files": [
            "src/calculator.py",
        ],
        "repair_policy": {
            "failure_category": "PATCH",
            "repair_action": "REGENERATE_PATCH",
            "resume_stage": (
                "RUN_PATCH_GENERATION"
            ),
            "max_retries": 5,
            "requires_approval": False,
        },
    }


def _payload():
    return MissionRepairRequestCreate(
        edits=[
            MissionPatchEdit(
                path="src/calculator.py",
                operation="REPLACE_UNIQUE",
                old_text="return a + b",
                new_text="return a * b",
            )
        ],
        generated_by=(
            "patch-failure-integration-test"
        ),
    )


def test_patch_failure_creates_repair_request(
    tmp_path,
):
    mission = _mission()
    plan = _repair_plan()

    with (
        patch(
            "app.missions.repair_request_builder."
            "get_mission",
            side_effect=[
                mission,
                mission,
            ],
        ),
        patch(
            "app.missions.repair_request_builder."
            "_load_existing_plan",
            return_value=plan,
        ),
        patch(
            "app.missions.repair_request_builder."
            "_request_directory",
            return_value=(
                tmp_path / "mission-36"
            ),
        ),
        patch(
            "app.missions.repair_request_builder."
            "add_mission_log"
        ) as log_mock,
    ):
        result = create_repair_patch_request(
            mission_id=36,
            payload=_payload(),
        )

    request = result["repair_request"]

    assert request["failure_source"] == (
        "IMPLEMENTATION_PATCH"
    )

    assert request[
        "failure_source_version"
    ] == (
        "implementation-patch-failure-v0.1"
    )

    assert request[
        "failure_category"
    ] == "PATCH"

    assert request[
        "failure_payload"
    ]["stage"] == "PATCH_APPLY"

    assert request[
        "verification_failure_signature"
    ] == "patch-signature-1"

    assert request["operation_count"] == 1
    assert request["status"] == "REQUESTED"
    assert request["patch_generated"] is False

    assert result["storage"][
        "duplicate"
    ] is False

    log_mock.assert_called_once()

    metadata = (
        log_mock.call_args.kwargs[
            "metadata"
        ]
    )

    assert metadata[
        "failure_source"
    ] == "IMPLEMENTATION_PATCH"

    assert metadata[
        "failure_category"
    ] == "PATCH"


def test_patch_failure_request_is_reused(
    tmp_path,
):
    mission = _mission()
    plan = _repair_plan()

    with (
        patch(
            "app.missions.repair_request_builder."
            "get_mission",
            side_effect=[
                mission,
                mission,
                mission,
            ],
        ),
        patch(
            "app.missions.repair_request_builder."
            "_load_existing_plan",
            return_value=plan,
        ),
        patch(
            "app.missions.repair_request_builder."
            "_request_directory",
            return_value=(
                tmp_path / "mission-36"
            ),
        ),
        patch(
            "app.missions.repair_request_builder."
            "add_mission_log"
        ),
    ):
        first = create_repair_patch_request(
            mission_id=36,
            payload=_payload(),
        )

        second = create_repair_patch_request(
            mission_id=36,
            payload=_payload(),
        )

    assert (
        first["repair_request"]["request_id"]
        == second["repair_request"][
            "request_id"
        ]
    )

    assert second["storage"][
        "duplicate"
    ] is True


def test_patch_failure_keeps_edit_scope_restriction(
    tmp_path,
):
    mission = _mission()
    plan = _repair_plan()

    invalid_payload = MissionRepairRequestCreate(
        edits=[
            MissionPatchEdit(
                path="src/unauthorized.py",
                operation="APPEND",
                text="unsafe = True",
            )
        ],
    )

    with (
        patch(
            "app.missions.repair_request_builder."
            "get_mission",
            return_value=mission,
        ),
        patch(
            "app.missions.repair_request_builder."
            "_load_existing_plan",
            return_value=plan,
        ),
        patch(
            "app.missions.repair_request_builder."
            "_request_directory",
            return_value=(
                tmp_path / "mission-36"
            ),
        ),
    ):
        try:
            create_repair_patch_request(
                mission_id=36,
                payload=invalid_payload,
            )
        except Exception as error:
            assert (
                "src/unauthorized.py"
                in str(error)
            )
        else:
            raise AssertionError(
                "Out-of-scope edit was accepted."
            )
