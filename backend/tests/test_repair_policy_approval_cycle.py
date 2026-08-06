from unittest.mock import patch

from app.missions.repair_cycle_orchestrator import (
    _determine_stage,
    _policy_approval_decision,
)


def _request():
    return {
        "request_id": "request-policy-1",
        "status": "AWAITING_REPAIR_REQUEST",
        "failure_category": "DEPENDENCY",
        "repair_policy": {
            "policy_version": (
                "mission-repair-policy-v0.1"
            ),
            "failure_category": "DEPENDENCY",
            "repair_action": "REQUIRE_APPROVAL",
            "resume_stage": "WAIT_REPAIR_APPROVAL",
            "max_retries": 1,
            "requires_approval": True,
        },
    }


def _approval_result(
    decision: str | None,
):
    approval = (
        None
        if decision is None
        else {
            "request_id": "request-policy-1",
            "decision": decision,
        }
    )

    return {
        "approval": approval,
    }


@patch(
    "app.missions.repair_cycle_orchestrator."
    "get_repair_policy_approval_safe"
)
def test_policy_approval_pending(
    approval_mock,
):
    approval_mock.return_value = (
        _approval_result(None)
    )

    decision = _policy_approval_decision(
        mission_id=36,
        request=_request(),
    )

    assert decision == "PENDING"


@patch(
    "app.missions.repair_cycle_orchestrator."
    "get_repair_policy_approval_safe"
)
def test_pending_policy_returns_wait_stage(
    approval_mock,
):
    approval_mock.return_value = (
        _approval_result(None)
    )

    stage, _ = _determine_stage(
        mission_id=36,
        request=_request(),
        context=None,
        draft=None,
        connection=None,
    )

    assert stage == "WAIT_POLICY_APPROVAL"


@patch(
    "app.missions.repair_cycle_orchestrator."
    "get_repair_policy_approval_safe"
)
def test_approved_policy_continues_to_context(
    approval_mock,
):
    approval_mock.return_value = (
        _approval_result("APPROVED")
    )

    stage, _ = _determine_stage(
        mission_id=36,
        request=_request(),
        context=None,
        draft=None,
        connection=None,
    )

    assert stage == "BUILD_CONTEXT"


@patch(
    "app.missions.repair_cycle_orchestrator."
    "get_repair_policy_approval_safe"
)
def test_rejected_policy_blocks_cycle(
    approval_mock,
):
    approval_mock.return_value = (
        _approval_result("REJECTED")
    )

    stage, reason = _determine_stage(
        mission_id=36,
        request=_request(),
        context=None,
        draft=None,
        connection=None,
    )

    assert stage == "STATE_BLOCKED"
    assert (
        "REPAIR_POLICY_REJECTED"
        in reason
    )


@patch(
    "app.missions.repair_cycle_orchestrator."
    "get_repair_policy_approval_safe"
)
def test_old_request_approval_is_ignored(
    approval_mock,
):
    approval_mock.return_value = {
        "approval": {
            "request_id": "old-request",
            "decision": "APPROVED",
        },
    }

    decision = _policy_approval_decision(
        mission_id=36,
        request=_request(),
    )

    assert decision == "PENDING"
