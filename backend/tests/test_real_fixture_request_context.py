import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from app.missions.models import (
    MissionPatchEdit,
    MissionRepairRequestCreate,
)
from app.missions.repair_context_builder import (
    build_repair_context,
)
from app.missions.repair_request_builder import (
    create_repair_patch_request,
)


MISSION_ID = 36

FIXTURE_ROOT = Path(
    r"C:\Users\closs\ArcRepairFixture"
)

TARGET_RELATIVE_PATH = (
    "src/calculator.py"
)

TARGET_PATH = (
    FIXTURE_ROOT
    / TARGET_RELATIVE_PATH
)


def _planning_result():
    return {
        "selected_files": [
            {
                "path": TARGET_RELATIVE_PATH,
                "operation": "UPDATE",
                "purpose": (
                    "Repair multiply implementation."
                ),
                "category": "BACKEND",
            }
        ],
        "modified_files": [
            TARGET_RELATIVE_PATH,
        ],
        "implementation_plan": {
            "steps": [
                {
                    "step_id": "step-1",
                    "position": 1,
                    "title": (
                        "Repair calculator multiply"
                    ),
                    "description": (
                        "Restore multiplication behavior."
                    ),
                    "target_files": [
                        TARGET_RELATIVE_PATH,
                    ],
                }
            ],
        },
        "verification_commands": [
            "python -m pytest -q",
        ],
    }


def _verification_result():
    return {
        "verification_version": (
            "real-fixture-verification-v0.1"
        ),
        "passed": False,
        "failure_source": "VERIFICATION",
        "failure_category": "TEST",
        "requested_command_count": 1,
        "executed_command_count": 1,
        "results": [
            {
                "name": "pytest",
                "category": "TEST",
                "failure_category": "TEST",
                "passed": False,
                "returncode": 1,
                "timed_out": False,
                "command": "python -m pytest -q",
                "stdout": "",
                "stderr": (
                    "tests/test_calculator.py::"
                    "test_multiply failed: "
                    "assert 7 == 12"
                ),
                "suspected_files": [
                    TARGET_RELATIVE_PATH,
                ],
            }
        ],
    }


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "ArcRepairFixture",
        "project_path": str(
            FIXTURE_ROOT
        ),
        "title": (
            "Repair real multiply failure"
        ),
        "purpose": (
            "Restore multiply and pass pytest."
        ),
        "objective": (
            "Restore multiply and pass pytest."
        ),
        "status": "RUNNING",
        "progress": 70,
        "tasks": [
            {
                "task_type": "PLANNING",
                "status": "COMPLETED",
                "result": json.dumps(
                    _planning_result(),
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "APPROVAL",
                "status": "COMPLETED",
                "result": json.dumps(
                    {
                        "decision": "APPROVED",
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "IMPLEMENTATION",
                "status": "READY",
                "result": json.dumps(
                    {
                        "mode": "PATCH_APPLIED",
                        "status": "COMPLETED",
                        "patch_applied": True,
                        "changed_files": [
                            TARGET_RELATIVE_PATH,
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "VERIFICATION",
                "status": "FAILED",
                "result": json.dumps(
                    _verification_result(),
                    ensure_ascii=False,
                ),
            },
        ],
    }


def _repair_plan():
    return {
        "repair_version": (
            "mission-self-repair-v0.1"
        ),
        "repair_plan_id": (
            "real-fixture-plan-1"
        ),
        "mission_id": MISSION_ID,
        "failure_source": "VERIFICATION",
        "failure_source_version": (
            "real-fixture-verification-v0.1"
        ),
        "verification_failure_signature": (
            "real-fixture-signature-1"
        ),
        "verification": {
            "passed": False,
            "failure_category": "TEST",
            "failure_categories": [
                "TEST",
            ],
            "requested_command_count": 1,
            "executed_command_count": 1,
        },
        "failures": [
            {
                "index": 0,
                "name": "pytest",
                "command": "python -m pytest -q",
                "category": "TEST",
                "failure_category": "TEST",
                "returncode": 1,
                "timed_out": False,
                "stdout": "",
                "stderr": (
                    "test_multiply expected 12 "
                    "but returned 7"
                ),
                "suspected_files": [
                    TARGET_RELATIVE_PATH,
                ],
            }
        ],
        "failure_count": 1,
        "selected_files": [
            TARGET_RELATIVE_PATH,
        ],
        "suspected_files": [
            TARGET_RELATIVE_PATH,
        ],
        "recommended_files": [
            TARGET_RELATIVE_PATH,
        ],
        "repair_policy": {
            "policy_version": (
                "mission-repair-policy-v0.1"
            ),
            "failure_category": "TEST",
            "repair_action": (
                "REGENERATE_EDIT"
            ),
            "resume_stage": (
                "REPAIR_EDIT"
            ),
            "max_retries": 3,
            "requires_approval": False,
        },
        "status": "PLANNED",
        "auto_apply": False,
    }


def _real_source_file(
    relative_path,
    remaining_bytes,
):
    normalized = str(
        relative_path
    ).replace("\\", "/")

    path = (
        FIXTURE_ROOT
        / normalized
    )

    raw = path.read_bytes()

    included_raw = raw[
        :remaining_bytes
    ]

    content = included_raw.decode(
        "utf-8"
    )

    return {
        "path": normalized,
        "included": True,
        "exists": True,
        "truncated": (
            len(included_raw) < len(raw)
        ),
        "size_bytes": len(raw),
        "included_bytes": len(
            included_raw
        ),
        "sha256": hashlib.sha256(
            raw
        ).hexdigest(),
        "content": content,
    }


def test_real_repair_plan_connects_to_request_and_context(
    tmp_path,
):
    assert TARGET_PATH.exists()

    original_content = (
        TARGET_PATH.read_text(
            encoding="utf-8"
        )
    )

    # 故障状態が維持されていること。
    assert (
        "return left + right"
        in original_content
    )

    mission = _mission()
    repair_plan = _repair_plan()

    request_root = (
        tmp_path
        / "repair-request"
    )

    context_root = (
        tmp_path
        / "repair-context"
    )

    payload = MissionRepairRequestCreate(
        edits=[
            MissionPatchEdit(
                operation=(
                    "REPLACE_UNIQUE"
                ),
                path=TARGET_RELATIVE_PATH,
                old_text=(
                    "    return left + right"
                ),
                new_text=(
                    "    return left * right"
                ),
            )
        ],
        generated_by=(
            "real-fixture-e2e"
        ),
        note=(
            "Real fixture Request and "
            "Context integration test"
        ),
    )

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
            return_value=repair_plan,
        ),
        patch(
            "app.missions.repair_request_builder."
            "_load_existing_request",
            return_value=None,
        ),
        patch(
            "app.missions.repair_request_builder."
            "_request_directory",
            return_value=request_root,
        ),
        patch(
            "app.missions.repair_request_builder."
            "add_mission_log",
        ) as request_log_mock,
    ):
        request_result = (
            create_repair_patch_request(
                mission_id=MISSION_ID,
                payload=payload,
            )
        )

    repair_request = request_result[
        "repair_request"
    ]

    assert repair_request[
        "status"
    ] == "REQUESTED"

    assert repair_request[
        "failure_source"
    ] == "VERIFICATION"

    assert repair_request[
        "failure_category"
    ] == "TEST"

    assert repair_request[
        "allowed_paths"
    ] == [
        TARGET_RELATIVE_PATH,
    ]

    assert repair_request[
        "edit_paths"
    ] == [
        TARGET_RELATIVE_PATH,
    ]

    assert repair_request[
        "operation_count"
    ] == 1

    assert repair_request[
        "auto_apply"
    ] is False

    assert repair_request[
        "patch_generated"
    ] is False

    assert repair_request[
        "patch_applied"
    ] is False

    request_event_types = [
        call.kwargs.get(
            "event_type"
        )
        for call in (
            request_log_mock
            .call_args_list
        )
    ]

    assert (
        "MISSION_REPAIR_PATCH_REQUEST_CREATED"
        in request_event_types
    )

    with (
        patch(
            "app.missions.repair_context_builder."
            "get_mission",
            return_value=mission,
        ),
        patch(
            "app.missions.repair_context_builder."
            "_load_existing_request",
            return_value=repair_request,
        ),
        patch(
            "app.missions.repair_context_builder."
            "_find_repair_plan",
            return_value=repair_plan,
        ),
        patch(
            "app.missions.repair_context_builder."
            "_read_source_file",
            side_effect=_real_source_file,
        ) as source_mock,
        patch(
            "app.missions.repair_context_builder."
            "REPAIR_PLAN_ROOT",
            context_root,
        ),
        patch(
            "app.missions.repair_context_builder."
            "add_mission_log",
        ) as context_log_mock,
    ):
        context_result = (
            build_repair_context(
                MISSION_ID
            )
        )

    context = context_result[
        "repair_context"
    ]

    assert context[
        "mission_id"
    ] == MISSION_ID

    assert context[
        "failure_source"
    ] == "VERIFICATION"

    assert context[
        "failure_category"
    ] == "TEST"

    assert context[
        "repair_request"
    ]["request_id"] == repair_request[
        "request_id"
    ]

    assert TARGET_RELATIVE_PATH in (
        context["candidate_paths"]
    )

    source_files = context[
        "source_files"
    ]

    target_source = next(
        item
        for item in source_files
        if item.get("path")
        == TARGET_RELATIVE_PATH
    )

    assert target_source[
        "included"
    ] is True

    assert target_source[
        "exists"
    ] is True

    assert target_source[
        "truncated"
    ] is False

    normalized_context_content = (
        target_source["content"]
        .replace("\r\n", "\n")
    )

    normalized_original_content = (
        original_content
        .replace("\r\n", "\n")
    )

    assert (
        normalized_context_content
        == normalized_original_content
    )

    assert (
        "def multiply("
        in target_source["content"]
    )

    assert (
        "return left + right"
        in target_source["content"]
    )

    expected_sha = hashlib.sha256(
        TARGET_PATH.read_bytes()
    ).hexdigest()

    assert target_source[
        "sha256"
    ] == expected_sha

    assert context[
        "context_limits"
    ]["included_file_count"] >= 1

    assert context[
        "safety_policy"
    ]["auto_apply"] is False

    source_mock.assert_called()

    latest_path = Path(
        context_result[
            "storage"
        ]["latest_path"]
    )

    if not latest_path.is_absolute():
        latest_path = (
            Path.cwd().parent
            / latest_path
        )

    assert latest_path.exists()

    context_event_types = [
        call.kwargs.get(
            "event_type"
        )
        for call in (
            context_log_mock
            .call_args_list
        )
    ]

    assert (
        "MISSION_REPAIR_CONTEXT_BUILT"
        in context_event_types
    )

    # この段階では実Fixtureを変更しない。
    assert (
        TARGET_PATH.read_text(
            encoding="utf-8"
        )
        == original_content
    )
