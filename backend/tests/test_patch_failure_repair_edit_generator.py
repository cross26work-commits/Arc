import json
from unittest.mock import patch

from app.missions.repair_edit_generator import (
    generate_repair_edit,
)


def _patch_failure_context():
    return {
        "repair_context_version": (
            "mission-repair-context-v0.1"
        ),
        "context_id": "patch-context-1",
        "mission_id": 36,
        "failure_source": (
            "IMPLEMENTATION_PATCH"
        ),
        "failure_category": "PATCH",
        "failure_payload": {
            "stage": "PATCH_APPLY",
            "error": "patch does not apply",
            "failure_category": "PATCH",
        },
        "repair_request": {
            "request_id": "request-patch-1",
            "status": "REPAIR_FAILED",
            "next_stage": "GENERATE_EDIT",
            "previous_edits": [],
        },
        "verification": {
            "passed": False,
            "failure_category": "PATCH",
            "failure_source": (
                "IMPLEMENTATION_PATCH"
            ),
            "failed_results": [
                {
                    "passed": False,
                    "name": "PATCH_APPLY",
                    "category": "PATCH",
                    "failure_category": "PATCH",
                    "stderr": (
                        "patch does not apply"
                    ),
                    "stdout": "",
                    "suspected_files": [
                        "src/calculator.py",
                    ],
                    "failure_source": (
                        "IMPLEMENTATION_PATCH"
                    ),
                }
            ],
        },
        "source_files": [
            {
                "relative_path": (
                    "src/calculator.py"
                ),
                "included": True,
                "content": (
                    "def multiply(a, b):\n"
                    "    return a + b\n"
                ),
            }
        ],
        "safety_policy": {
            "auto_apply": False,
            "require_unique_match": True,
            "require_patch_check": True,
            "require_backup": True,
            "require_verification": True,
            "require_rollback_on_failure": True,
            "allowed_edit_operations": [
                "REPLACE_UNIQUE",
            ],
        },
    }


def test_patch_failure_reaches_edit_generator(
    tmp_path,
):
    context = _patch_failure_context()

    with (
        patch(
            "app.missions.repair_edit_generator."
            "get_mission",
            return_value={
                "id": 36,
                "project_id": 1,
                "project_name": "Fixture",
                "title": "Patch Repair",
                "objective": "Repair patch failure",
                "status": "RUNNING",
                "progress": 60,
            },
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
            "add_mission_log"
        ),
    ):
        result = generate_repair_edit(
            mission_id=36
        )

    draft = result["repair_edit_draft"]

    assert draft["status"] in {
        "EDIT_READY",
        "INSUFFICIENT_CONTEXT",
    }

    assert draft[
        "generation_summary"
    ]["failure_count"] == 1

    assert draft[
        "generation_summary"
    ]["source_file_count"] == 1

    assert draft[
        "safety"
    ]["auto_apply"] is False

    assert draft[
        "safety"
    ]["requires_verification"] is True
