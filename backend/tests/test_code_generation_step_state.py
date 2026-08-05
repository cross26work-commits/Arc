from app.missions.code_generation_runner import (
    _mark_generation_step_failed,
    _mark_generation_step_patch_ready,
)
from app.missions.implementation_step_state import (
    initialize_step_execution,
    start_current_step,
)
from app.missions.models import (
    FileOperation,
    ImplementationPlan,
    ImplementationStep,
    RequirementAnalyzerResult,
)


def _execution():
    requirement = RequirementAnalyzerResult(
        objective="APIを実装する。",
        success_criteria=[
            "APIテストが成功する。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求である。"
        ),
    )

    operation = FileOperation(
        path="app/api.py",
        operation="UPDATE",
        purpose="APIを更新する。",
        category="BACKEND",
    )

    plan = ImplementationPlan(
        mission_id=1,
        project_id=1,
        project_name="Example",
        objective=requirement.objective,
        requirement_contract_version=(
            requirement.contract_version
        ),
        requirement_contract=requirement,
        implementation_possible=True,
        selected_files=[operation],
        steps=[
            ImplementationStep(
                step_id="step-1",
                position=1,
                title="API",
                description="APIを更新する。",
                category="BACKEND",
                file_operations=[
                    operation
                ],
            )
        ],
        execution_order=["step-1"],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary=(
            "APIを更新する。"
        ),
    )

    state = initialize_step_execution(
        plan
    )

    return start_current_step(
        state
    )


def test_marks_step_patch_ready() -> None:
    state = _execution()

    state = (
        _mark_generation_step_patch_ready(
            execution=state,
            prompt_version=(
                "code-generation-prompt-v0.1"
            ),
            context_sha256="a" * 64,
            integration={
                "integration_version":
                    "integration-v0.1",
                "contract_sha256": "b" * 64,
                "patch_request_sha256":
                    "c" * 64,
                "patch_sha256": "d" * 64,
                "changed_files": [
                    "app/api.py"
                ],
                "changed_file_count": 1,
                "edit_count": 2,
            },
        )
    )

    result = state.results["step-1"]

    assert result.status == "PATCH_READY"
    assert result.attempt_count == 1
    assert result.prompt_version == (
        "code-generation-prompt-v0.1"
    )
    assert result.context_sha256 == "a" * 64
    assert result.contract_sha256 == "b" * 64
    assert result.patch_sha256 == "d" * 64
    assert result.changed_files == [
        "app/api.py"
    ]
    assert result.metadata[
        "patch_request_sha256"
    ] == "c" * 64
    assert result.metadata[
        "changed_file_count"
    ] == 1
    assert result.metadata["edit_count"] == 2


def test_marks_step_failed() -> None:
    state = _execution()

    state = _mark_generation_step_failed(
        execution=state,
        error="LLM Pipeline failed.",
    )

    result = state.results["step-1"]

    assert result.status == "FAILED"
    assert result.error == (
        "LLM Pipeline failed."
    )
    assert result.attempt_count == 1
    assert state.current_step_id == "step-1"
    assert state.remaining_step_ids == [
        "step-1"
    ]


def test_patch_ready_does_not_complete_step() -> None:
    state = _execution()

    state = (
        _mark_generation_step_patch_ready(
            execution=state,
            prompt_version="v0.1",
            context_sha256="a" * 64,
            integration={
                "contract_sha256": "b" * 64,
                "patch_sha256": "c" * 64,
                "changed_files": [],
                "changed_file_count": 0,
                "edit_count": 0,
            },
        )
    )

    assert state.execution_completed is False
    assert state.completed_step_ids == []
    assert state.remaining_step_ids == [
        "step-1"
    ]
    assert state.current_step_id == "step-1"
