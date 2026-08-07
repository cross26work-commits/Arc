from pathlib import Path
from unittest.mock import patch

import pytest

from app.missions.repair_cycle_orchestrator import (
    REPAIR_CYCLE_ORCHESTRATOR_VERSION,
    run_repair_cycle_step,
)


MISSION_ID = 36


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "Fixture",
        "title": "Repair Cycle Integration",
        "objective": "Validate repair orchestration",
        "status": "APPROVED",
        "progress": 80,
        "tasks": [],
    }


def _request(status):
    return {
        "mission_id": MISSION_ID,
        "request_id": "request-cycle-1",
        "status": status,
        "failure_category": "PATCH",
        "auto_apply": False,
        "retry_count": 0,
    }


def _context():
    return {
        "mission_id": MISSION_ID,
        "context_id": "context-cycle-1",
        "repair_request": {
            "request_id": "request-cycle-1",
        },
    }


def _draft():
    return {
        "mission_id": MISSION_ID,
        "draft_id": "draft-cycle-1",
        "context_id": "context-cycle-1",
        "status": "EDIT_READY",
    }


def _connection():
    return {
        "mission_id": MISSION_ID,
        "connection_id": "connection-cycle-1",
        "draft_id": "draft-cycle-1",
    }


STAGE_CASES = [
    (
        "BUILD_CONTEXT",
        "build_repair_context_safe",
        {},
    ),
    (
        "GENERATE_EDIT",
        "generate_repair_edit_safe",
        {},
    ),
    (
        "EVALUATE_POLICY",
        "evaluate_repair_execution_policy_safe",
        {},
    ),
    (
        "CONNECT_EDIT",
        "connect_repair_edit_safe",
        {},
    ),
    (
        "GENERATE_PATCH",
        (
            "connect_repair_request_to_"
            "patch_generator_safe"
        ),
        {},
    ),
    (
        "APPLY_PATCH",
        "apply_repair_patch_safe",
        {
            "keyword_call": True,
        },
    ),
    (
        "VERIFY_REPAIR",
        "run_repair_verification_safe",
        {},
    ),
    (
        "PREPARE_RETRY",
        "prepare_repair_retry_safe",
        {
            "keyword_call": True,
        },
    ),
]


@pytest.mark.parametrize(
    (
        "stage",
        "handler_name",
        "options",
    ),
    STAGE_CASES,
)
def test_orchestrator_executes_resolved_stage(
    tmp_path,
    stage,
    handler_name,
    options,
):
    request_before = _request("TEST_BEFORE")
    request_after = _request("TEST_AFTER")

    request_reads = [
        request_before,
        request_after,
    ]

    context_reads = [
        _context(),
        _context(),
    ]

    draft_reads = [
        _draft(),
        _draft(),
    ]

    connection_reads = [
        _connection(),
        _connection(),
    ]

    handler_result = {
        "stage_result": stage,
    }

    state_path = (
        tmp_path
        / "repair-cycle-state.json"
    )

    with (
        patch(
            "app.missions.repair_cycle_orchestrator."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_request",
            side_effect=request_reads,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_context",
            side_effect=context_reads,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_edit_draft",
            side_effect=draft_reads,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_connection",
            side_effect=connection_reads,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_determine_stage",
            side_effect=[
                (
                    stage,
                    f"Execute {stage}",
                ),
                (
                    "CYCLE_COMPLETED",
                    "Cycle completed",
                ),
            ],
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_last_step_is_duplicate",
            return_value=False,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_save_cycle_state",
            return_value=state_path,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "add_mission_log",
        ) as log_mock,
        patch(
            (
                "app.missions."
                "repair_cycle_orchestrator."
                f"{handler_name}"
            ),
            return_value=handler_result,
        ) as handler_mock,
    ):
        result = run_repair_cycle_step(
            MISSION_ID
        )

    assert result["stage"] == stage
    assert result["executed"] is True
    assert result["duplicate"] is False
    assert result["outcome"] == "COMPLETED"

    assert result[
        "request_status_before"
    ] == "TEST_BEFORE"

    assert result[
        "request_status_after"
    ] == "TEST_AFTER"

    assert result[
        "next_stage"
    ] == "CYCLE_COMPLETED"

    assert result["result"] == handler_result

    assert result[
        "orchestrator_version"
    ] == REPAIR_CYCLE_ORCHESTRATOR_VERSION

    assert result[
        "single_stage_only"
    ] is True

    assert result["auto_apply"] is False

    if options.get("keyword_call"):
        if stage == "APPLY_PATCH":
            handler_mock.assert_called_once()

            kwargs = (
                handler_mock
                .call_args
                .kwargs
            )

            assert kwargs[
                "mission_id"
            ] == MISSION_ID

            assert kwargs[
                "decided_by"
            ] == (
                REPAIR_CYCLE_ORCHESTRATOR_VERSION
            )

            assert (
                "single-stage execution"
                in kwargs["note"]
            )

        elif stage == "PREPARE_RETRY":
            handler_mock.assert_called_once_with(
                mission_id=MISSION_ID,
                max_retries=None,
            )
    else:
        handler_mock.assert_called_once_with(
            MISSION_ID
        )

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_CYCLE_STEP_COMPLETED"
        in event_types
    )


def test_orchestrator_returns_completed_cycle():
    request = _request("REPAIR_VERIFIED")

    with (
        patch(
            "app.missions.repair_cycle_orchestrator."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_request",
            return_value=request,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_context",
            return_value=_context(),
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_edit_draft",
            return_value=_draft(),
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_connection",
            return_value=_connection(),
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_determine_stage",
            return_value=(
                "CYCLE_COMPLETED",
                "Repair verified.",
            ),
        ),
    ):
        result = run_repair_cycle_step(
            MISSION_ID
        )

    assert result["stage"] == (
        "CYCLE_COMPLETED"
    )
    assert result["executed"] is False
    assert result["outcome"] == "COMPLETED"
    assert result["next_action"] is None


def test_orchestrator_returns_blocked_state(
    tmp_path,
):
    request = _request(
        "PATCH_APPLY_FAILED"
    )

    state_path = (
        tmp_path
        / "repair-cycle-state.json"
    )

    with (
        patch(
            "app.missions.repair_cycle_orchestrator."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_request",
            return_value=request,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_context",
            return_value=None,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_edit_draft",
            return_value=None,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_repair_connection",
            return_value=None,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_determine_stage",
            return_value=(
                "STATE_BLOCKED",
                "Patch apply failed.",
            ),
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "_save_cycle_state",
            return_value=state_path,
        ),
        patch(
            "app.missions.repair_cycle_orchestrator."
            "add_mission_log",
        ) as log_mock,
    ):
        result = run_repair_cycle_step(
            MISSION_ID
        )

    assert result["stage"] == "STATE_BLOCKED"
    assert result["executed"] is False
    assert result["outcome"] == "BLOCKED"

    assert result["next_action"] == (
        "HUMAN_OR_AI_REVIEW_REQUIRED"
    )

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_CYCLE_BLOCKED"
        in event_types
    )
