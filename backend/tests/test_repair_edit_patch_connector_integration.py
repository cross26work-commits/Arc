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
TARGET_PATH = "src/calculator.py"


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "ArcRepairFixture",
        "title": "Repair multiply",
        "status": "RUNNING",
        "progress": 75,
    }


def _request():
    return {
        "mission_id": MISSION_ID,
        "request_id": "real-request-1",
        "repair_plan_id": "real-plan-1",
        "status": "REQUESTED",
        "failure_source": "VERIFICATION",
        "failure_category": "TEST",
        "generated_by": "real-fixture-e2e",
        "note": "Repair multiply",
        "edits": [],
        "patch_generated": False,
        "patch_checked": False,
        "patch_applied": False,
        "auto_apply": False,
    }


def _draft():
    return {
        "repair_edit_schema_version": (
            REPAIR_EDIT_SCHEMA_VERSION
        ),
        "generator_version": (
            REPAIR_EDIT_GENERATOR_VERSION
        ),
        "draft_id": "real-draft-1",
        "context_id": "real-context-1",
        "mission_id": MISSION_ID,
        "status": "EDIT_READY",
        "edits": [
            {
                "operation": "REPLACE_UNIQUE",
                "path": TARGET_PATH,
                "old_text": (
                    "    return left + right"
                ),
                "new_text": (
                    "    return left * right"
                ),
                "reason": (
                    "Deterministic expected repair."
                ),
                "confidence": 1.0,
                "rule_id": (
                    "verification-expected-repair-v0.1"
                ),
            }
        ],
        "safety": {
            "auto_apply": False,
            "requires_patch_check": True,
            "requires_backup": True,
            "requires_verification": True,
            "requires_rollback_on_failure": True,
            "generation_mode": (
                "DETERMINISTIC_RULE_BASED"
            ),
        },
        "next_stage": "REPAIR_PATCH_CHECK",
    }


def _generated_patch_result():
    return {
        "mission": _mission(),
        "generator": {
            "generator_version": (
                "mission-patch-generator-v0.1"
            ),
            "changed_file_count": 1,
            "changed_files": [
                TARGET_PATH,
            ],
            "operation_count": 1,
            "result_path": (
                "data/generated-patch.json"
            ),
            "patch_text": (
                "--- a/src/calculator.py\n"
                "+++ b/src/calculator.py\n"
                "@@\n"
                "-    return left + right\n"
                "+    return left * right\n"
            ),
        },
        "patch_check": {
            "patch_applicable": True,
            "patch_sha256": "abc123",
        },
        "implementation": {
            "mode": "PATCH_CHECKED",
            "patch": {
                "sha256": "abc123",
            },
        },
    }


def test_edit_draft_connects_to_patch_check(
    tmp_path,
):
    state = {
        "request": _request(),
    }

    mission_dir = (
        tmp_path
        / f"mission-{MISSION_ID}"
    )
    mission_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    def load_request(_mission_id):
        return dict(
            state["request"]
        )

    def write_json(path, payload):
        path = Path(path)

        if path.name == "repair-request.json":
            state["request"] = dict(
                payload
            )

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
            return_value=_draft(),
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
        ) as edit_log_mock,
    ):
        connected = connect_repair_edit(
            mission_id=MISSION_ID
        )

    connected_request = connected[
        "repair_request"
    ]

    assert connected_request[
        "status"
    ] == "AWAITING_REPAIR_PATCH_CHECK"

    assert connected_request[
        "next_stage"
    ] == "REPAIR_PATCH_CHECK"

    assert connected_request[
        "auto_apply"
    ] is False

    assert connected_request[
        "requires_patch_check"
    ] is True

    assert connected_request[
        "requires_verification"
    ] is True

    assert connected_request[
        "repair_edit_count"
    ] == 1

    assert connected_request[
        "edits"
    ][0]["path"] == TARGET_PATH

    assert connected_request[
        "edits"
    ][0]["old_text"] == (
        "    return left + right"
    )

    assert connected_request[
        "edits"
    ][0]["new_text"] == (
        "    return left * right"
    )

    edit_events = [
        call.kwargs.get("event_type")
        for call in edit_log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_EDIT_CONNECTED"
        in edit_events
    )

    with (
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
            return_value=(
                _generated_patch_result()
            ),
        ) as generator_mock,
        patch(
            "app.missions.repair_patch_connector."
            "_latest_request_path",
            return_value=(
                mission_dir
                / "repair-request.json"
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
        ) as patch_log_mock,
    ):
        checked = (
            connect_repair_request_to_patch_generator(
                mission_id=MISSION_ID
            )
        )

    checked_request = checked[
        "repair_request"
    ]

    assert checked_request[
        "status"
    ] == "PATCH_CHECKED"

    assert checked_request[
        "patch_generated"
    ] is True

    assert checked_request[
        "patch_checked"
    ] is True

    assert checked_request[
        "patch_applied"
    ] is False

    assert checked_request[
        "auto_apply"
    ] is False

    patch_result = checked_request[
        "patch_result"
    ]

    assert patch_result[
        "patch_applicable"
    ] is True

    assert patch_result[
        "implementation_mode"
    ] == "PATCH_CHECKED"

    assert patch_result[
        "changed_files"
    ] == [
        TARGET_PATH,
    ]

    assert patch_result[
        "patch_sha256"
    ] == "abc123"

    generator_mock.assert_called_once()

    generated_payload = (
        generator_mock
        .call_args
        .kwargs[
            "payload"
        ]
    )

    assert len(
        generated_payload.edits
    ) == 1

    assert (
        generated_payload
        .edits[0]
        .path
        == TARGET_PATH
    )

    patch_events = [
        call.kwargs.get("event_type")
        for call in patch_log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_PATCH_CHECKED"
        in patch_events
    )



def test_real_fixture_content_flows_from_generated_edit_to_patch_check_contract(
    tmp_path,
):
    from app.missions.repair_context_builder import (
        REPAIR_CONTEXT_VERSION,
    )
    from app.missions.repair_edit_generator import (
        generate_repair_edit,
    )

    fixture_root = Path(
        r"C:\Users\closs\ArcRepairFixture"
    )

    target = (
        fixture_root
        / TARGET_PATH
    )

    assert target.is_file()

    source_content = (
        target.read_text(
            encoding="utf-8",
        )
        .replace(
            "\r\n",
            "\n",
        )
    )

    broken_block = (
        "def multiply(left: int, right: int) -> int:\n"
        '    """Return the product of two integers."""\n'
        "    return left + right"
    )

    fixed_block = (
        "def multiply(left: int, right: int) -> int:\n"
        '    """Return the product of two integers."""\n'
        "    return left * right"
    )

    assert source_content.count(
        broken_block
    ) == 1

    assert (
        fixed_block
        not in source_content
    )

    state = {
        "request": _request(),
    }

    mission_dir = (
        tmp_path
        / f"mission-{MISSION_ID}"
    )

    mission_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    context = {
        "repair_context_version": (
            REPAIR_CONTEXT_VERSION
        ),
        "context_id": (
            "real-fixture-acceptance-context-1"
        ),
        "mission_id": MISSION_ID,
        "repair_request": {
            "request_id": (
                state["request"]["request_id"]
            ),
            "status": (
                state["request"]["status"]
            ),
            "previous_edits": [],
        },
        "failure_source": "VERIFICATION",
        "failure_category": "TEST",
        "failure_payload": {
            "expected_repair": {
                "operation": "REPLACE_UNIQUE",
                "path": TARGET_PATH,
                "old_text": (
                    broken_block
                ),
                "new_text": (
                    fixed_block
                ),
            },
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
                },
            ],
        },
        "source_files": [
            {
                "relative_path": TARGET_PATH,
                "included": True,
                "exists": True,
                "truncated": False,
                "content": source_content,
            },
        ],
        "safety_policy": {
            "auto_apply": False,
            "require_patch_check": True,
            "require_verification": True,
        },
    }

    def load_request(_mission_id):
        assert _mission_id == MISSION_ID

        return dict(
            state["request"]
        )

    def write_request(path, payload):
        path = Path(path)

        if path.name == "repair-request.json":
            state["request"] = dict(
                payload
            )

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
            return_value=mission_dir,
        ),
        patch(
            "app.missions.repair_edit_generator."
            "add_mission_log",
        ),
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
            "_mission_directory",
            return_value=mission_dir,
        ),
        patch(
            "app.missions.repair_edit_connector."
            "_write_json_atomic",
            side_effect=write_request,
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
            return_value=(
                _generated_patch_result()
            ),
        ) as generator_mock,
        patch(
            "app.missions.repair_patch_connector."
            "_latest_request_path",
            return_value=(
                mission_dir
                / "repair-request.json"
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
            side_effect=write_request,
        ),
        patch(
            "app.missions.repair_patch_connector."
            "add_mission_log",
        ),
    ):
        generated_edit = (
            generate_repair_edit(
                MISSION_ID
            )
        )

        draft = generated_edit[
            "repair_edit_draft"
        ]

        assert draft[
            "status"
        ] == "EDIT_READY"

        assert draft[
            "safety"
        ][
            "generation_mode"
        ] == "DETERMINISTIC_RULE_BASED"

        assert len(
            draft["edits"]
        ) == 1

        generated = draft[
            "edits"
        ][0]

        assert generated[
            "operation"
        ] == "REPLACE_UNIQUE"

        assert generated[
            "path"
        ] == TARGET_PATH

        assert generated[
            "old_text"
        ] == broken_block

        assert generated[
            "new_text"
        ] == fixed_block

        draft_path = (
            mission_dir
            / "repair-edit-draft.json"
        )

        assert draft_path.is_file()

        connected = (
            connect_repair_edit(
                mission_id=MISSION_ID
            )
        )

        connected_request = (
            connected[
                "repair_request"
            ]
        )

        assert connected_request[
            "status"
        ] == "AWAITING_REPAIR_PATCH_CHECK"

        assert connected_request[
            "edits"
        ][0][
            "path"
        ] == TARGET_PATH

        assert connected_request[
            "edits"
        ][0][
            "old_text"
        ] == broken_block

        assert connected_request[
            "edits"
        ][0][
            "new_text"
        ] == fixed_block

        checked = (
            connect_repair_request_to_patch_generator(
                mission_id=MISSION_ID
            )
        )

    checked_request = (
        checked[
            "repair_request"
        ]
    )

    assert checked_request[
        "status"
    ] == "PATCH_CHECKED"

    assert checked_request[
        "patch_generated"
    ] is True

    assert checked_request[
        "patch_checked"
    ] is True

    generator_mock.assert_called_once()

    payload = (
        generator_mock
        .call_args
        .kwargs[
            "payload"
        ]
    )

    assert len(
        payload.edits
    ) == 1

    payload_edit = (
        payload.edits[0]
    )

    assert (
        payload_edit.operation
        == "REPLACE_UNIQUE"
    )

    assert (
        payload_edit.path
        == TARGET_PATH
    )

    assert (
        payload_edit.old_text
        == broken_block
    )

    assert (
        payload_edit.new_text
        == fixed_block
    )
