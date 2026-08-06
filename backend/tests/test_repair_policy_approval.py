import pytest

from app.missions.models import (
    MissionApprovalDecision,
)
from app.missions.repair_cycle_orchestrator import (
    _determine_stage,
)
from app.missions.repair_cycle_runner import (
    _determine_stop_reason,
)
from app.missions.repair_policy_approval import (
    MissionRepairPolicyApprovalError,
    _validate_request_policy,
)


def _dependency_request():
    return {
        "request_id": "request-1",
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


def test_validate_dependency_policy():
    policy = _validate_request_policy(
        _dependency_request()
    )

    assert policy[
        "failure_category"
    ] == "DEPENDENCY"


def test_validate_non_approval_policy_rejected():
    request = _dependency_request()
    request["repair_policy"][
        "repair_action"
    ] = "REGENERATE_CODE"

    with pytest.raises(
        MissionRepairPolicyApprovalError
    ):
        _validate_request_policy(request)


def test_runner_stops_on_policy_approval_stage():
    stop_reason = _determine_stop_reason(
        {
            "stage": "WAIT_POLICY_APPROVAL",
            "outcome": (
                "WAITING_POLICY_APPROVAL"
            ),
            "executed": False,
            "duplicate": False,
        }
    )

    assert stop_reason == "WAIT_APPROVAL"


def test_approval_payload_model_is_compatible():
    payload = MissionApprovalDecision(
        reason="Dependency repair approved",
        decided_by="master",
    )

    assert payload.decided_by == "master"
