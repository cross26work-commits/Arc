from pathlib import Path
from unittest.mock import patch

from app.missions.repair_edit_connector import (
    connect_repair_edit,
)
from app.missions.repair_edit_generator import (
    REPAIR_EDIT_GENERATOR_VERSION,
    REPAIR_EDIT_SCHEMA_VERSION,
)
from app.missions.repair_patch_connector import (
    connect_repair_request_to_patch_generator,
)


MISSION_ID = 36


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "Fixture",
        "title": "Patch Failure Repair",
        "objective": "Regenerate failed patch",
        "status": "RUNNING",
        "progress": 70,
    }


def _initial_request():
    return {
        "mission_id": MISSION_ID,
        "request_id": "request-patch-1",
        "repair_plan_id": "plan-patch-1",
        "status": "REPAIR_FAILED",
        "next_stage": "GENERATE_REPAIR_EDIT",
        "auto_apply": False,
        "patch_generated": False,
        "patch_checked": False,
        "patch_applied": False,
        "failure_source": "IMPLEMENTATION_PATCH",
        "failure_source_version": (
            "implementation-patch-failure-v0.1"
        ),
        "failure_category": "PATCH",
        "failure_signature": "patch-signature-1",
        "failure_payload": {
            "stage": "PATCH_APPLY",
            "error": "patch does not apply",
            "failure_category": "PATCH",
        },
        "edits": [],
        "generated_by": (
            "patch-failure-repair-test"
        ),
    }


def _edit_draft():
    return {
        "repair_edit_schema_version": (
            REPAIR_EDIT_SCHEMA_VERSION
        ),
        "generator_version": (
            REPAIR_EDIT_GENERATOR_VERSION
        ),
        "mission_id": MISSION_ID,
        "request_id": "request-patch-1",
        "context_id": "repair-context-patch-1",
        "draft_id": "repair-edit-draft-patch-1",
        "status": "EDIT_READY",
        "reason": "Deterministic repair edit.",
        "edits": [
            {
                "operation": "REPLACE_UNIQUE",
                "path": "src/calculator.py",
                "old_text": "return a + b",
                "new_text": "return a * b",
            }
        ],
        "safety": {
            "auto_apply": False,
            "requires_unique_match": True,
            "requires_patch_check": True,
            "requires_backup": True,
            "requires_verification": True,
            "requires_rollback_on_failure": True,
            "generated_by_ai_model": False,
            "generation_mode": (
                "DETERMINISTIC_RULE_BASED"
            ),
            "supported_operations": [
                "REPLACE_UNIQUE",
            ],
        },
    }


def _generated_patch_result():
    return {
        "mission": _mission(),
        "generator": {
            "patch_sha256": "abc123",
            "operation_count": 1,
            "changed_files": [
                "src/calculator.py",
            ],
        },
        "patch_check": {
            "applicable": True,
            "changed_files": [
                "src/calculator.py",
            ],
        },
        "implementation": {
            "mode": "PATCH_CHECKED",
            "changed_files": [
                "src/calculator.py",
            ],
        },
    }


def test_patch_failure_edit_connects_to_patch_check(
    tmp_path,
):
    mission_dir = tmp_path / "mission-36"
    mission_dir.mkdir(parents=True)

    state = {
        "request": _initial_request(),
    }

    def load_request(_mission_id):
        return dict(state["request"])

    def write_json(path, payload):
        path = Path(path)

        if path.name == "repair-request.json":
            state["request"] = dict(payload)

    with (
        patch(
            "app.missions.repair_edit_connector."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_edit_connector."
            "_load_existing_request",
            side_effect=load_request,
        ),
        patch(
            "app.missions.repair_edit_connector."
            "_load_edit_draft",
            return_value=_edit_draft(),
        ),
        patch(
            "app.missions.repair_edit_connector."
            "_mission_directory",
            return_value=mission_dir,
        ),
        patch(
            "app.missions.repair_edit_connector."
            "_write_json_atomic",
            side_effect=write_json,
        ),
        patch(
            "app.missions.repair_edit_connector."
            "add_mission_log",
        ),
        patch(
            "app.missions.repair_patch_connector."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_patch_connector."
            "_load_existing_request",
            side_effect=load_request,
        ),
        patch(
            "app.missions.repair_patch_connector."
            "generate_mission_patch_safe",
            return_value=_generated_patch_result(),
        ) as generator_mock,
        patch(
            "app.missions.repair_patch_connector."
            "_result_summary",
            return_value={
                "patch_applicable": True,
                "implementation_mode": (
                    "PATCH_CHECKED"
                ),
                "changed_file_count": 1,
                "changed_files": [
                    "src/calculator.py",
                ],
                "operation_count": 1,
                "patch_sha256": "abc123",
            },
        ),
        patch(
            "app.missions.repair_patch_connector."
            "_latest_request_path",
            return_value=(
                mission_dir / "repair-request.json"
            ),
        ),
        patch(
            "app.missions.repair_patch_connector."
            "REPAIR_PLAN_ROOT",
            tmp_path,
        ),
        patch(
            "app.missions.repair_patch_connector."
            "_write_json_atomic",
            side_effect=write_json,
        ),
        patch(
            "app.missions.repair_patch_connector."
            "add_mission_log",
        ),
    ):
        connected = connect_repair_edit(
            mission_id=MISSION_ID
        )

        connected_request = connected[
            "repair_request"
        ]

        assert connected_request["status"] == (
            "AWAITING_REPAIR_PATCH_CHECK"
        )
        assert connected_request["next_stage"] == (
            "REPAIR_PATCH_CHECK"
        )
        assert len(
            connected_request["edits"]
        ) == 1

        # Failure SourceがConnector経由でも消えない。
        assert connected_request[
            "failure_source"
        ] == "IMPLEMENTATION_PATCH"

        checked = (
            connect_repair_request_to_patch_generator(
                mission_id=MISSION_ID
            )
        )

    final_request = checked["repair_request"]

    assert final_request["status"] == (
        "PATCH_CHECKED"
    )
    assert final_request[
        "patch_generated"
    ] is True
    assert final_request[
        "patch_checked"
    ] is True
    assert final_request[
        "patch_applied"
    ] is False
    assert final_request[
        "auto_apply"
    ] is False

    assert final_request[
        "failure_source"
    ] == "IMPLEMENTATION_PATCH"
    assert final_request[
        "failure_category"
    ] == "PATCH"

    generator_mock.assert_called_once()

    payload = (
        generator_mock.call_args.kwargs[
            "payload"
        ]
    )

    assert len(payload.edits) == 1
    assert payload.edits[0].path == (
        "src/calculator.py"
    )
    assert payload.edits[0].operation == (
        "REPLACE_UNIQUE"
    )

    assert "failure=PATCH" in payload.note
