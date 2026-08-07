import json
from pathlib import Path
from unittest.mock import patch

from app.missions.repair_cycle_runner import (
    REPAIR_CYCLE_RUNNER_VERSION,
    run_repair_cycle,
)


MISSION_ID = 36


def _mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "ArcStepFixture",
        "title": "Repair Cycle Runner E2E",
        "objective": (
            "Run bounded repair stages "
            "until approval is required"
        ),
        "status": "APPROVED",
        "progress": 80,
        "tasks": [],
    }


def _step(
    *,
    stage,
    before,
    after,
    next_stage,
    executed=True,
    duplicate=False,
    outcome="COMPLETED",
):
    return {
        "mission": _mission(),
        "orchestrator_version": (
            "mission-repair-cycle-"
            "orchestrator-v0.1"
        ),
        "step_id": f"step-{stage.lower()}",
        "step_signature": (
            f"signature-{stage.lower()}"
        ),
        "stage": stage,
        "executed": executed,
        "duplicate": duplicate,
        "outcome": outcome,
        "reason": f"Execute {stage}",
        "request_status_before": before,
        "request_status_after": after,
        "next_stage": next_stage,
        "single_stage_only": True,
        "auto_apply": False,
    }


def test_runner_executes_multiple_stages_and_stops_for_approval(
    tmp_path,
):
    mission_dir = tmp_path / "mission-36"

    steps = [
        _step(
            stage="BUILD_CONTEXT",
            before="AWAITING_REPAIR_REQUEST",
            after="AWAITING_REPAIR_REQUEST",
            next_stage="GENERATE_EDIT",
        ),
        _step(
            stage="GENERATE_EDIT",
            before="AWAITING_REPAIR_REQUEST",
            after="AWAITING_REPAIR_REQUEST",
            next_stage="EVALUATE_POLICY",
        ),
        _step(
            stage="EVALUATE_POLICY",
            before="AWAITING_REPAIR_REQUEST",
            after="AWAITING_REPAIR_REQUEST",
            next_stage="WAIT_APPROVAL",
        ),
        {
            "mission": _mission(),
            "orchestrator_version": (
                "mission-repair-cycle-"
                "orchestrator-v0.1"
            ),
            "step_id": "step-wait-approval",
            "step_signature": (
                "signature-wait-approval"
            ),
            "stage": "WAIT_APPROVAL",
            "executed": False,
            "duplicate": False,
            "outcome": "WAITING_APPROVAL",
            "reason": (
                "Explicit approval is required."
            ),
            "request_status_before": (
                "AWAITING_REPAIR_REQUEST"
            ),
            "request_status_after": (
                "AWAITING_REPAIR_REQUEST"
            ),
            "next_action": (
                "MASTER_APPROVAL_REQUIRED"
            ),
            "single_stage_only": True,
            "auto_apply": False,
        },
    ]

    with (
        patch(
            "app.missions.repair_cycle_runner."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "run_repair_cycle_step_safe",
            side_effect=steps,
        ) as step_mock,
        patch(
            "app.missions.repair_cycle_runner."
            "_mission_directory",
            return_value=mission_dir,
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "add_mission_log",
        ) as log_mock,
    ):
        result = run_repair_cycle(
            mission_id=MISSION_ID,
            max_steps=8,
        )

    assert result["runner_version"] == (
        REPAIR_CYCLE_RUNNER_VERSION
    )

    assert result["stop_reason"] == (
        "WAIT_APPROVAL"
    )
    assert result["completed"] is False
    assert result["blocked"] is False
    assert result["waiting_approval"] is True
    assert result["bounded"] is True

    assert result["step_count"] == 4
    assert result[
        "executed_step_count"
    ] == 3

    assert [
        item["stage"]
        for item in result["steps"]
    ] == [
        "BUILD_CONTEXT",
        "GENERATE_EDIT",
        "EVALUATE_POLICY",
        "WAIT_APPROVAL",
    ]

    assert step_mock.call_count == 4

    assert result["safety"] == {
        "single_stage_orchestrator": True,
        "bounded_loop": True,
        "max_steps_enforced": True,
        "auto_apply_override": False,
        "retry_override": False,
        "stop_on_blocked": True,
        "stop_on_waiting_approval": True,
        "stop_on_duplicate": True,
        "stop_on_repeated_state": True,
    }

    history_path = Path(
        result["history_path"]
    )

    assert history_path.exists()

    history_payload = json.loads(
        history_path.read_text(
            encoding="utf-8"
        )
    )

    assert history_payload[
        "runner_version"
    ] == REPAIR_CYCLE_RUNNER_VERSION

    assert history_payload[
        "mission_id"
    ] == MISSION_ID

    assert history_payload[
        "latest_run"
    ]["stop_reason"] == "WAIT_APPROVAL"

    assert len(
        history_payload["runs"]
    ) == 1

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_CYCLE_RUN_"
        "WAITING_APPROVAL"
        in event_types
    )


def test_runner_reaches_cycle_completed(
    tmp_path,
):
    mission_dir = tmp_path / "mission-36"

    steps = [
        _step(
            stage="APPLY_PATCH",
            before="PATCH_CHECKED",
            after="PATCH_APPLIED",
            next_stage="VERIFY_REPAIR",
        ),
        _step(
            stage="VERIFY_REPAIR",
            before="PATCH_APPLIED",
            after="REPAIR_VERIFIED",
            next_stage="CYCLE_COMPLETED",
        ),
        {
            "mission": _mission(),
            "orchestrator_version": (
                "mission-repair-cycle-"
                "orchestrator-v0.1"
            ),
            "stage": "CYCLE_COMPLETED",
            "executed": False,
            "duplicate": False,
            "outcome": "COMPLETED",
            "reason": "Repair verified.",
            "request_status_before": (
                "REPAIR_VERIFIED"
            ),
            "request_status_after": (
                "REPAIR_VERIFIED"
            ),
            "next_action": None,
        },
    ]

    with (
        patch(
            "app.missions.repair_cycle_runner."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "run_repair_cycle_step_safe",
            side_effect=steps,
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "_mission_directory",
            return_value=mission_dir,
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "add_mission_log",
        ),
    ):
        result = run_repair_cycle(
            mission_id=MISSION_ID,
            max_steps=8,
        )

    assert result["stop_reason"] == (
        "CYCLE_COMPLETED"
    )
    assert result["completed"] is True
    assert result["blocked"] is False
    assert result["waiting_approval"] is False

    assert result["step_count"] == 3
    assert result[
        "executed_step_count"
    ] == 2


def test_runner_stops_at_max_steps(
    tmp_path,
):
    mission_dir = tmp_path / "mission-36"

    steps = [
        _step(
            stage="BUILD_CONTEXT",
            before="REQUEST-1",
            after="REQUEST-2",
            next_stage="GENERATE_EDIT",
        ),
        _step(
            stage="GENERATE_EDIT",
            before="REQUEST-2",
            after="REQUEST-3",
            next_stage="EVALUATE_POLICY",
        ),
    ]

    with (
        patch(
            "app.missions.repair_cycle_runner."
            "get_mission",
            return_value=_mission(),
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "run_repair_cycle_step_safe",
            side_effect=steps,
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "_mission_directory",
            return_value=mission_dir,
        ),
        patch(
            "app.missions.repair_cycle_runner."
            "add_mission_log",
        ),
    ):
        result = run_repair_cycle(
            mission_id=MISSION_ID,
            max_steps=2,
        )

    assert result["stop_reason"] == (
        "MAX_STEPS_REACHED"
    )
    assert result["completed"] is False
    assert result["bounded"] is True
    assert result["step_count"] == 2
