import pytest

from app.missions.implementation_step_state import (
    ImplementationStepStateError,
    block_current_step,
    complete_current_step,
    initialize_step_execution,
    start_current_step,
    update_current_step_status,
)
from app.missions.models import (
    FileOperation,
    ImplementationPlan,
    ImplementationStep,
    RequirementAnalyzerResult,
)


def _plan() -> ImplementationPlan:
    requirement = RequirementAnalyzerResult(
        objective="APIとテストを実装する。",
        success_criteria=[
            "テストが成功する。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求である。"
        ),
    )

    api_operation = FileOperation(
        path="app/api.py",
        operation="UPDATE",
        purpose="APIを実装する。",
        category="BACKEND",
    )

    test_operation = FileOperation(
        path="tests/test_api.py",
        operation="UPDATE",
        purpose="テストを実装する。",
        category="TEST",
    )

    return ImplementationPlan(
        mission_id=1,
        project_id=1,
        project_name="Example",
        objective=requirement.objective,
        requirement_contract_version=(
            requirement.contract_version
        ),
        requirement_contract=requirement,
        implementation_possible=True,
        selected_files=[
            api_operation,
            test_operation,
        ],
        steps=[
            ImplementationStep(
                step_id="step-1",
                position=1,
                title="API",
                description="APIを実装する。",
                category="BACKEND",
                file_operations=[
                    api_operation
                ],
            ),
            ImplementationStep(
                step_id="step-2",
                position=2,
                title="Test",
                description="テストを実装する。",
                category="TEST",
                file_operations=[
                    test_operation
                ],
                depends_on_steps=[
                    "step-1"
                ],
            ),
        ],
        execution_order=[
            "step-1",
            "step-2",
        ],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary=(
            "APIとテストを実装する。"
        ),
    )


def test_initializes_execution_state() -> None:
    state = initialize_step_execution(
        _plan()
    )

    assert state.current_step_id == "step-1"
    assert state.completed_step_ids == []
    assert state.remaining_step_ids == [
        "step-1",
        "step-2",
    ]
    assert state.execution_completed is False
    assert state.results[
        "step-1"
    ].status == "PENDING"


def test_starts_current_step() -> None:
    state = initialize_step_execution(
        _plan()
    )

    state = start_current_step(state)

    assert state.results[
        "step-1"
    ].status == "GENERATING"
    assert state.results[
        "step-1"
    ].attempt_count == 1
    assert state.total_attempt_count == 1


def test_updates_current_step_status() -> None:
    state = initialize_step_execution(
        _plan()
    )
    state = start_current_step(state)

    state = update_current_step_status(
        state,
        status="PATCH_READY",
        metadata={
            "prompt_version": "v0.1"
        },
    )

    assert state.results[
        "step-1"
    ].status == "PATCH_READY"
    assert state.results[
        "step-1"
    ].metadata[
        "prompt_version"
    ] == "v0.1"


def test_completes_and_advances_step() -> None:
    state = initialize_step_execution(
        _plan()
    )
    state = start_current_step(state)

    state = complete_current_step(
        state,
        verification_passed=True,
        changed_files=[
            "app/api.py"
        ],
    )

    assert state.completed_step_ids == [
        "step-1"
    ]
    assert state.remaining_step_ids == [
        "step-2"
    ]
    assert state.current_step_id == "step-2"
    assert state.results[
        "step-1"
    ].status == "COMPLETED"


def test_completes_all_steps() -> None:
    state = initialize_step_execution(
        _plan()
    )

    state = start_current_step(state)
    state = complete_current_step(
        state,
        verification_passed=True,
    )

    state = start_current_step(state)
    state = complete_current_step(
        state,
        verification_passed=True,
    )

    assert state.execution_completed is True
    assert state.current_step_id is None
    assert state.remaining_step_ids == []
    assert state.completed_step_ids == [
        "step-1",
        "step-2",
    ]


def test_failed_verification_does_not_advance() -> None:
    state = initialize_step_execution(
        _plan()
    )
    state = start_current_step(state)

    with pytest.raises(
        ImplementationStepStateError,
        match="Verification",
    ):
        complete_current_step(
            state,
            verification_passed=False,
        )

    assert state.current_step_id == "step-1"
    assert state.remaining_step_ids == [
        "step-1",
        "step-2",
    ]
    assert state.results[
        "step-1"
    ].status == "FAILED"


def test_blocks_current_step() -> None:
    state = initialize_step_execution(
        _plan()
    )

    state = block_current_step(
        state,
        reason="追加情報が必要です。",
    )

    assert state.blocked_step_ids == [
        "step-1"
    ]
    assert state.results[
        "step-1"
    ].status == "BLOCKED"
    assert state.current_step_id == "step-1"
