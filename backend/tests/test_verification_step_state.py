from app.missions.implementation_step_state import (
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
from app.missions.verification_runner import (
    _complete_step_verification,
    _fail_step_verification,
    _start_step_verification,
)


def _patch_applied_result(
    *,
    two_steps: bool = False,
) -> dict:
    requirement = RequirementAnalyzerResult(
        objective="APIを更新する。",
        success_criteria=[
            "テストが成功する。"
        ],
        implementation_possible=True,
        analysis_summary="実装可能。",
    )

    operation = FileOperation(
        path="app/api.py",
        operation="UPDATE",
        purpose="APIを更新する。",
        category="BACKEND",
    )

    steps = [
        ImplementationStep(
            step_id="step-1",
            position=1,
            title="API",
            description="APIを更新する。",
            category="BACKEND",
            file_operations=[operation],
        )
    ]

    if two_steps:
        steps.append(
            ImplementationStep(
                step_id="step-2",
                position=2,
                title="Test",
                description="テストを更新する。",
                category="TEST",
                file_operations=[],
                depends_on_steps=["step-1"],
            )
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
        steps=steps,
        execution_order=[
            step.step_id
            for step in steps
        ],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary="APIを更新する。",
    )

    execution = initialize_step_execution(
        plan
    )
    execution = start_current_step(
        execution
    )
    execution = update_current_step_status(
        execution,
        status="PATCH_READY",
    )
    execution = update_current_step_status(
        execution,
        status="PATCH_APPLIED",
    )

    execution.results[
        "step-1"
    ].changed_files = [
        "app/api.py"
    ]

    return {
        "mode": "PATCH_APPLIED",
        "step_execution": (
            execution.model_dump(
                mode="json"
            )
        ),
    }


def test_starts_verification() -> None:
    result = _start_step_verification(
        _patch_applied_result()
    )

    step = result[
        "step_execution"
    ]["results"]["step-1"]

    assert step["status"] == "VERIFYING"
    assert step["metadata"][
        "verification_started_at"
    ] is not None


def test_completes_and_advances_step() -> None:
    result = _start_step_verification(
        _patch_applied_result(
            two_steps=True
        )
    )

    result = _complete_step_verification(
        implementation_result=result,
        verification_result={
            "passed": True,
            "verification_version":
                "verification-v0.1",
            "executed_command_count": 2,
        },
    )

    execution = result[
        "step_execution"
    ]

    assert execution[
        "completed_step_ids"
    ] == ["step-1"]
    assert execution[
        "remaining_step_ids"
    ] == ["step-2"]
    assert execution[
        "current_step_id"
    ] == "step-2"
    assert execution[
        "results"
    ]["step-1"]["status"] == "COMPLETED"


def test_completes_final_step() -> None:
    result = _start_step_verification(
        _patch_applied_result()
    )

    result = _complete_step_verification(
        implementation_result=result,
        verification_result={
            "passed": True,
            "verification_version":
                "verification-v0.1",
            "executed_command_count": 1,
        },
    )

    execution = result[
        "step_execution"
    ]

    assert execution[
        "execution_completed"
    ] is True
    assert execution[
        "current_step_id"
    ] is None
    assert execution[
        "remaining_step_ids"
    ] == []


def test_marks_verification_failed() -> None:
    result = _start_step_verification(
        _patch_applied_result()
    )

    result = _fail_step_verification(
        implementation_result=result,
        verification_result={
            "passed": False,
            "failure_category":
                "TEST_FAILURE",
            "executed_command_count": 1,
        },
    )

    execution = result[
        "step_execution"
    ]
    step = execution[
        "results"
    ]["step-1"]

    assert step["status"] == "FAILED"
    assert step["verification_passed"] is False
    assert execution[
        "current_step_id"
    ] == "step-1"
    assert execution[
        "remaining_step_ids"
    ] == ["step-1"]
