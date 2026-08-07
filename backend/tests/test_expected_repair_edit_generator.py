from pathlib import Path
from unittest.mock import patch

from app.missions.repair_context_builder import (
    REPAIR_CONTEXT_VERSION,
)
from app.missions.repair_edit_generator import (
    generate_repair_edit,
)


MISSION_ID = 36
TARGET_PATH = "src/calculator.py"


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "ArcRepairFixture",
        "title": "Repair multiply",
        "purpose": "Restore multiply behavior",
        "status": "RUNNING",
        "progress": 70,
    }


def _context():
    content = (
        "def multiply("
        "left: int, right: int"
        ") -> int:\\n"
        "    return left + right\\n"
    )

    return {
        "repair_context_version": (
            REPAIR_CONTEXT_VERSION
        ),
        "context_id": (
            "real-fixture-context-1"
        ),
        "mission_id": MISSION_ID,
        "repair_request": {
            "request_id": (
                "real-fixture-request-1"
            ),
            "status": "REQUESTED",
            "previous_edits": [],
        },
        "failure_source": "VERIFICATION",
        "failure_category": "TEST",
        "failure_payload": {
            "expected_repair": {
                "operation": (
                    "REPLACE_UNIQUE"
                ),
                "path": TARGET_PATH,
                "old_text": (
                    "    return left + right"
                ),
                "new_text": (
                    "    return left * right"
                ),
            }
        },
        "verification": {
            "passed": False,
            "failure_category": "TEST",
            "failed_results": [
                {
                    "name": "pytest",
                    "passed": False,
                    "failure_category": "TEST",
                    "path": TARGET_PATH,
                    "stderr": (
                        "test_multiply: "
                        "assert 7 == 12"
                    ),
                }
            ],
        },
        "source_files": [
            {
                "relative_path": TARGET_PATH,
                "included": True,
                "exists": True,
                "truncated": False,
                "content": content,
            }
        ],
        "safety_policy": {
            "auto_apply": False,
            "require_patch_check": True,
            "require_verification": True,
        },
    }


def test_expected_repair_generates_edit_ready(
    tmp_path,
):
    context = _context()

    with (
        patch(
            "app.missions.repair_edit_generator."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_edit_generator."
            "_load_repair_context",
            return_value=context,
        ),
        patch(
            "app.missions.repair_edit_generator."
            "_mission_directory",
            return_value=tmp_path,
        ),
        patch(
            "app.missions.repair_edit_generator."
            "add_mission_log",
        ) as log_mock,
    ):
        result = generate_repair_edit(
            MISSION_ID
        )

    draft = result[
        "repair_edit_draft"
    ]

    assert draft["status"] == "EDIT_READY"
    assert draft[
        "next_stage"
    ] == "REPAIR_PATCH_CHECK"

    assert draft["safety"][
        "auto_apply"
    ] is False

    assert draft["safety"][
        "generation_mode"
    ] == "DETERMINISTIC_RULE_BASED"

    assert len(draft["edits"]) == 1

    edit = draft["edits"][0]

    assert edit == {
        "operation": "REPLACE_UNIQUE",
        "path": TARGET_PATH,
        "old_text": (
            "    return left + right"
        ),
        "new_text": (
            "    return left * right"
        ),
        "reason": (
            "Generate a deterministic edit from the explicit expected_repair after confirming that old_text occurs exactly once."
        ),
        "confidence": 1.0,
        "rule_id": (
            "verification-expected-repair-v0.1"
        ),
    }

    latest_path = Path(
        result["storage"]["latest_path"]
    )

    if not latest_path.is_absolute():
        latest_path = (
            Path.cwd().parent
            / latest_path
        )

    assert latest_path.exists()

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_EDIT_GENERATED"
        in event_types
    )
