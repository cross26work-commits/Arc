from app.missions.code_generation_runner import (
    _mark_generation_step_patch_ready,
)
from app.missions.implementation_runner import (
    _mark_step_patch_applied,
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
from app.missions.verification_runner import (
    _complete_step_verification,
    _has_remaining_steps,
    _start_step_verification,
)


def _plan() -> ImplementationPlan:
    requirement = RequirementAnalyzerResult(
        objective=(
            "APIとテストを段階的に実装する。"
        ),
        requirements=[
            "APIを実装する。",
            "APIテストを実装する。",
        ],
        success_criteria=[
            "すべてのテストが成功する。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "2Stepで実装可能な要求である。"
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
        purpose="APIテストを実装する。",
        category="TEST",
        depends_on=[
            "app/api.py"
        ],
    )

    return ImplementationPlan(
        mission_id=1,
        project_id=1,
        project_name="StepLoopFixture",
        objective=requirement.objective,
        success_criteria=(
            requirement.success_criteria
        ),
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
                description=(
                    "APIテストを実装する。"
                ),
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
        file_execution_order=[
            "app/api.py",
            "tests/test_api.py",
        ],
        verification_commands=[
            "python -m pytest"
        ],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary=(
            "APIの後にテストを実装する。"
        ),
    )


def _generate_patch_apply_verify(
    implementation_result: dict,
    *,
    context_sha: str,
    contract_sha: str,
    patch_sha: str,
    changed_file: str,
) -> dict:
    execution = implementation_result[
        "step_execution"
    ]

    execution_model = start_current_step(
        execution
    )

    execution_model = (
        _mark_generation_step_patch_ready(
            execution=execution_model,
            prompt_version=(
                "code-generation-prompt-v0.1"
            ),
            context_sha256=context_sha,
            integration={
                "integration_version":
                    "patch-integration-v0.1",
                "contract_sha256":
                    contract_sha,
                "patch_request_sha256":
                    "f" * 64,
                "patch_sha256":
                    patch_sha,
                "changed_files": [
                    changed_file
                ],
                "changed_file_count": 1,
                "edit_count": 1,
            },
        )
    )

    implementation_result = {
        **implementation_result,
        "step_execution": (
            execution_model.model_dump(
                mode="json"
            )
        ),
    }

    implementation_result = (
        _mark_step_patch_applied(
            implementation_result=(
                implementation_result
            ),
            patch_sha256=patch_sha,
            changed_files=[
                changed_file
            ],
            applied_at=(
                "2026-08-04T07:00:00+00:00"
            ),
        )
    )

    implementation_result = (
        _start_step_verification(
            implementation_result
        )
    )

    implementation_result = (
        _complete_step_verification(
            implementation_result=(
                implementation_result
            ),
            verification_result={
                "passed": True,
                "verification_version":
                    "verification-v0.1",
                "executed_command_count": 1,
            },
        )
    )

    return implementation_result


def test_runs_two_step_loop_to_completion() -> None:
    execution = initialize_step_execution(
        _plan()
    )

    implementation_result = {
        "mode": "BACKUP_READY",
        "step_execution": (
            execution.model_dump(
                mode="json"
            )
        ),
    }

    # Step 1
    implementation_result = (
        _generate_patch_apply_verify(
            implementation_result,
            context_sha="a" * 64,
            contract_sha="b" * 64,
            patch_sha="c" * 64,
            changed_file="app/api.py",
        )
    )

    step_execution = implementation_result[
        "step_execution"
    ]

    assert step_execution[
        "completed_step_ids"
    ] == [
        "step-1"
    ]
    assert step_execution[
        "remaining_step_ids"
    ] == [
        "step-2"
    ]
    assert step_execution[
        "current_step_id"
    ] == "step-2"
    assert _has_remaining_steps(
        implementation_result
    ) is True

    # 次Step再武装相当
    implementation_result = {
        **implementation_result,
        "mode": "BACKUP_READY",
    }

    # Step 2
    implementation_result = (
        _generate_patch_apply_verify(
            implementation_result,
            context_sha="d" * 64,
            contract_sha="e" * 64,
            patch_sha="f" * 64,
            changed_file=(
                "tests/test_api.py"
            ),
        )
    )

    step_execution = implementation_result[
        "step_execution"
    ]

    assert step_execution[
        "completed_step_ids"
    ] == [
        "step-1",
        "step-2",
    ]
    assert step_execution[
        "remaining_step_ids"
    ] == []
    assert step_execution[
        "current_step_id"
    ] is None
    assert step_execution[
        "execution_completed"
    ] is True
    assert _has_remaining_steps(
        implementation_result
    ) is False

    step_1 = step_execution[
        "results"
    ]["step-1"]
    step_2 = step_execution[
        "results"
    ]["step-2"]

    assert step_1["status"] == "COMPLETED"
    assert step_1[
        "changed_files"
    ] == [
        "app/api.py"
    ]
    assert step_1[
        "verification_passed"
    ] is True

    assert step_2["status"] == "COMPLETED"
    assert step_2[
        "changed_files"
    ] == [
        "tests/test_api.py"
    ]
    assert step_2[
        "verification_passed"
    ] is True

    assert step_execution[
        "total_attempt_count"
    ] == 2


def test_step_two_cannot_start_before_step_one_completion() -> None:
    execution = initialize_step_execution(
        _plan()
    )

    assert execution.current_step_id == (
        "step-1"
    )
    assert execution.results[
        "step-2"
    ].status == "PENDING"
    assert execution.completed_step_ids == []


def test_final_step_does_not_request_rearm() -> None:
    execution = initialize_step_execution(
        _plan()
    )

    implementation_result = {
        "mode": "BACKUP_READY",
        "step_execution": (
            execution.model_dump(
                mode="json"
            )
        ),
    }

    implementation_result = (
        _generate_patch_apply_verify(
            implementation_result,
            context_sha="a" * 64,
            contract_sha="b" * 64,
            patch_sha="c" * 64,
            changed_file="app/api.py",
        )
    )

    implementation_result = {
        **implementation_result,
        "mode": "BACKUP_READY",
    }

    implementation_result = (
        _generate_patch_apply_verify(
            implementation_result,
            context_sha="d" * 64,
            contract_sha="e" * 64,
            patch_sha="f" * 64,
            changed_file=(
                "tests/test_api.py"
            ),
        )
    )

    assert _has_remaining_steps(
        implementation_result
    ) is False
    assert implementation_result[
        "step_execution"
    ]["execution_completed"] is True
