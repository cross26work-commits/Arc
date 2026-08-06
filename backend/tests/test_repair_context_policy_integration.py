import pytest

from app.missions.repair_context_builder import (
    MissionRepairContextError,
    _resolve_context_retry_limit,
    _safety_policy,
)


def test_context_retry_limit_uses_build_policy():
    limit = _resolve_context_retry_limit(
        {
            "failure_category": "BUILD",
            "max_retries": 5,
        }
    )

    assert limit == 2


def test_context_retry_limit_uses_syntax_policy():
    limit = _resolve_context_retry_limit(
        {
            "failure_category": "SYNTAX",
        }
    )

    assert limit == 3


def test_context_retry_limit_uses_embedded_policy():
    limit = _resolve_context_retry_limit(
        {
            "failure_category": "BUILD",
            "repair_policy": {
                "max_retries": 1,
            },
            "max_retries": 5,
        }
    )

    assert limit == 1


def test_context_retry_limit_unknown_is_safe():
    limit = _resolve_context_retry_limit(
        {
            "failure_category": "INVALID",
            "max_retries": 10,
        }
    )

    assert limit == 1


def test_context_retry_limit_rejects_zero():
    with pytest.raises(
        MissionRepairContextError
    ):
        _resolve_context_retry_limit(
            {
                "failure_category": "SYNTAX",
                "max_retries": 0,
            }
        )


def test_safety_policy_uses_resolved_limit():
    policy = _safety_policy(
        maximum_retry_count=2
    )

    assert policy[
        "maximum_retry_count"
    ] == 2

    assert policy[
        "forbid_dependency_install_without_approval"
    ] is True
