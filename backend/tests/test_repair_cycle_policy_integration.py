from app.missions.repair_cycle_orchestrator import (
    _determine_stage,
    _policy_blocks_automatic_cycle,
    _request_repair_policy,
)
from app.missions.repair_supervisor import (
    _decision_for_run,
)


def _request(
    category: str,
    *,
    status: str = "AWAITING_REPAIR_REQUEST",
):
    return {
        "status": status,
        "failure_category": category,
    }


def test_request_policy_falls_back_to_category():
    policy = _request_repair_policy(
        _request("BUILD")
    )

    assert policy[
        "repair_action"
    ] == "REGENERATE_CODE"

    assert policy[
        "resume_stage"
    ] == "RUN_CODE_GENERATION"


def test_unknown_policy_blocks_cycle():
    request = _request("UNKNOWN")

    assert (
        _policy_blocks_automatic_cycle(
            request
        )
        is True
    )


def test_git_policy_blocks_cycle():
    request = _request("GIT")

    assert (
        _policy_blocks_automatic_cycle(
            request
        )
        is True
    )


def test_build_policy_does_not_block_cycle():
    request = _request("BUILD")

    assert (
        _policy_blocks_automatic_cycle(
            request
        )
        is False
    )


def test_unknown_failure_returns_state_blocked():
    stage, reason = _determine_stage(
        mission_id=36,
        request=_request("UNKNOWN"),
        context=None,
        draft=None,
        connection=None,
    )

    assert stage == "STATE_BLOCKED"
    assert "STOP_AND_INSPECT" in reason


def test_build_failure_still_builds_context():
    stage, _ = _determine_stage(
        mission_id=36,
        request=_request("BUILD"),
        context=None,
        draft=None,
        connection=None,
    )

    assert stage == "BUILD_CONTEXT"


def test_supervisor_requires_policy_inspection():
    decision = _decision_for_run(
        {
            "stop_reason": "STATE_BLOCKED",
            "latest_step": {
                "repair_action": (
                    "STOP_AND_INSPECT"
                ),
                "resume_stage": "STOPPED",
            },
        }
    )

    assert decision[
        "decision"
    ] == (
        "REPAIR_POLICY_INSPECTION_REQUIRED"
    )

    assert decision[
        "recommended_action"
    ] == "INSPECT_FAILURE_AND_POLICY"

    assert decision[
        "requires_master_action"
    ] is True

    assert decision[
        "can_continue"
    ] is False
