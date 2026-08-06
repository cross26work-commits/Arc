from app.missions.repair_request_builder import (
    _repair_policy_payload,
)
from app.missions.retry_controller import (
    _policy_retry_limit,
    _resolve_retry_limit,
)


def _plan(category: str):
    return {
        "verification": {
            "failure_category": category,
        },
    }


def _request(
    category: str,
    *,
    stored_max: int | None = None,
    embedded_max: int | None = None,
):
    request = {
        "failure_category": category,
    }

    if stored_max is not None:
        request["max_retries"] = stored_max

    if embedded_max is not None:
        request["repair_policy"] = {
            "max_retries": embedded_max,
        }

    return request


def test_repair_request_policy_payload_for_build():
    payload = _repair_policy_payload(
        _plan("BUILD")
    )

    assert payload == {
        "policy_version": (
            "mission-repair-policy-v0.1"
        ),
        "failure_category": "BUILD",
        "repair_action": "REGENERATE_CODE",
        "resume_stage": "RUN_CODE_GENERATION",
        "max_retries": 2,
        "requires_approval": False,
    }


def test_policy_retry_limit_uses_embedded_policy():
    assert (
        _policy_retry_limit(
            _request(
                "BUILD",
                embedded_max=2,
            )
        )
        == 2
    )


def test_policy_retry_limit_falls_back_to_category():
    assert (
        _policy_retry_limit(
            _request("SYNTAX")
        )
        == 3
    )


def test_requested_limit_cannot_exceed_policy():
    limit = _resolve_retry_limit(
        repair_request=_request(
            "BUILD",
            stored_max=5,
        ),
        requested_max_retries=7,
    )

    assert limit == 2


def test_requested_limit_can_be_lower_than_policy():
    limit = _resolve_retry_limit(
        repair_request=_request(
            "SYNTAX",
            stored_max=3,
        ),
        requested_max_retries=1,
    )

    assert limit == 1


def test_dependency_retry_is_limited_to_one():
    limit = _resolve_retry_limit(
        repair_request=_request(
            "DEPENDENCY",
            stored_max=10,
        ),
        requested_max_retries=10,
    )

    assert limit == 1


def test_unknown_failure_retry_is_limited_to_one():
    limit = _resolve_retry_limit(
        repair_request=_request(
            "NOT_SUPPORTED",
            stored_max=10,
        ),
        requested_max_retries=10,
    )

    assert limit == 1
