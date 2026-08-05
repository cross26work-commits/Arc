from app.missions.verification_runner import (
    _append_step_verification_history,
    _has_remaining_steps,
)


def _implementation_result(
    *,
    remaining: list[str],
    execution_completed: bool,
) -> dict:
    return {
        "mode": "PATCH_APPLIED",
        "step_execution": {
            "execution_version":
                "implementation-step-execution-v0.1",
            "current_step_id": (
                remaining[0]
                if remaining
                else None
            ),
            "completed_step_ids": [
                "step-1"
            ],
            "remaining_step_ids": remaining,
            "blocked_step_ids": [],
            "results": {},
            "execution_completed":
                execution_completed,
            "total_attempt_count": 1,
        },
    }


def test_detects_remaining_step() -> None:
    result = _implementation_result(
        remaining=["step-2"],
        execution_completed=False,
    )

    assert _has_remaining_steps(
        result
    ) is True


def test_final_step_has_no_remaining_cycle() -> None:
    result = _implementation_result(
        remaining=[],
        execution_completed=True,
    )

    assert _has_remaining_steps(
        result
    ) is False


def test_legacy_result_has_no_step_cycle() -> None:
    assert _has_remaining_steps(
        {
            "mode": "PATCH_APPLIED"
        }
    ) is False


def test_appends_verification_history() -> None:
    result = _implementation_result(
        remaining=["step-2"],
        execution_completed=False,
    )

    updated = (
        _append_step_verification_history(
            implementation_result=result,
            verification_result={
                "passed": True,
                "verification_version":
                    "verification-v0.1",
                "executed_command_count": 2,
            },
        )
    )

    history = updated[
        "step_verification_history"
    ]

    assert len(history) == 1
    assert history[0][
        "step_id"
    ] == "step-1"
    assert history[0]["passed"] is True
    assert history[0][
        "executed_command_count"
    ] == 2


def test_preserves_existing_history() -> None:
    result = _implementation_result(
        remaining=["step-3"],
        execution_completed=False,
    )

    result[
        "step_verification_history"
    ] = [
        {
            "step_id": "step-1",
            "passed": True,
        }
    ]

    updated = (
        _append_step_verification_history(
            implementation_result=result,
            verification_result={
                "passed": True,
                "verification_version":
                    "verification-v0.1",
                "executed_command_count": 1,
            },
        )
    )

    history = updated[
        "step_verification_history"
    ]

    assert len(history) == 2
    assert history[0][
        "step_id"
    ] == "step-1"
    assert history[1][
        "step_id"
    ] == "step-1"
