import pytest

from app.missions.implementation_runner import (
    MissionImplementationError,
    _mark_step_patch_applied,
)
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


def _patch_ready_result() -> dict:
    requirement = RequirementAnalyzerResult(
        objective="APIを更新する。",
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
        execution_order=[
            "step-1"
        ],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary=(
            "APIを更新する。"
        ),
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

    execution.results[
        "step-1"
    ].patch_sha256 = "a" * 64

    return {
        "mode": "PATCH_CHECKED",
        "step_execution": (
            execution.model_dump(
                mode="json"
            )
        ),
        "unrelated_field": {
            "preserved": True
        },
    }


def test_marks_current_step_patch_applied() -> None:
    result = _mark_step_patch_applied(
        implementation_result=(
            _patch_ready_result()
        ),
        patch_sha256="b" * 64,
        changed_files=[
            "app/api.py"
        ],
        applied_at=(
            "2026-08-04T06:30:00+00:00"
        ),
        apply_result_path=(
            "data/patch_apply.json"
        ),
    )

    execution = result[
        "step_execution"
    ]
    step = execution[
        "results"
    ]["step-1"]

    assert step["status"] == (
        "PATCH_APPLIED"
    )
    assert step["patch_sha256"] == (
        "b" * 64
    )
    assert step["changed_files"] == [
        "app/api.py"
    ]
    assert step["metadata"][
        "patch_applied_at"
    ] == (
        "2026-08-04T06:30:00+00:00"
    )
    assert step["metadata"][
        "apply_result_path"
    ] == "data/patch_apply.json"
    assert step["metadata"][
        "changed_file_count"
    ] == 1
    assert result[
        "unrelated_field"
    ] == {
        "preserved": True
    }


def test_patch_applied_does_not_complete_step() -> None:
    result = _mark_step_patch_applied(
        implementation_result=(
            _patch_ready_result()
        ),
        patch_sha256="b" * 64,
        changed_files=[
            "app/api.py"
        ],
        applied_at=(
            "2026-08-04T06:30:00+00:00"
        ),
    )

    execution = result[
        "step_execution"
    ]

    assert execution[
        "execution_completed"
    ] is False
    assert execution[
        "completed_step_ids"
    ] == []
    assert execution[
        "remaining_step_ids"
    ] == [
        "step-1"
    ]
    assert execution[
        "current_step_id"
    ] == "step-1"


def test_rejects_non_patch_ready_step() -> None:
    result = _patch_ready_result()

    result[
        "step_execution"
    ]["results"][
        "step-1"
    ]["status"] = "GENERATING"

    with pytest.raises(
        MissionImplementationError,
        match="PATCH_READY",
    ):
        _mark_step_patch_applied(
            implementation_result=result,
            patch_sha256="b" * 64,
            changed_files=[
                "app/api.py"
            ],
            applied_at=(
                "2026-08-04T06:30:00+00:00"
            ),
        )


def test_legacy_result_without_step_state_is_unchanged() -> None:
    legacy = {
        "mode": "PATCH_CHECKED",
        "patch": {
            "patch_sha256": "a" * 64
        },
    }

    result = _mark_step_patch_applied(
        implementation_result=legacy,
        patch_sha256="b" * 64,
        changed_files=[
            "app/api.py"
        ],
        applied_at=(
            "2026-08-04T06:30:00+00:00"
        ),
    )

    assert result is legacy
    assert "step_execution" not in result
