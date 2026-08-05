import json

import pytest

from app.missions.code_generation_prompt_builder import (
    CODE_GENERATION_PROMPT_VERSION,
    CodeGenerationPromptBuilderError,
    build_code_generation_prompt,
)
from app.missions.models import (
    FileOperation,
    ImplementationPlan,
    ImplementationStep,
    RequirementAnalyzerResult,
)


def _requirement() -> RequirementAnalyzerResult:
    return RequirementAnalyzerResult(
        objective=(
            "顧客登録APIとテストを追加する。"
        ),
        requirements=[
            "顧客登録APIを追加する。",
            "回帰テストを追加する。",
        ],
        success_criteria=[
            "顧客登録テストが成功する。"
        ],
        constraints=[
            "既存APIとの互換性を維持する。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求である。"
        ),
    )


def _plan() -> ImplementationPlan:
    requirement = _requirement()

    model_operation = FileOperation(
        path="app/models.py",
        operation="UPDATE",
        purpose="顧客Modelを更新する。",
        category="DATA",
    )
    api_operation = FileOperation(
        path="app/api/customers.py",
        operation="UPDATE",
        purpose="顧客登録APIを追加する。",
        category="BACKEND",
        depends_on=["app/models.py"],
    )
    test_operation = FileOperation(
        path="tests/test_customers.py",
        operation="UPDATE",
        purpose="回帰テストを追加する。",
        category="TEST",
        depends_on=[
            "app/api/customers.py"
        ],
    )

    return ImplementationPlan(
        mission_id=1,
        project_id=2,
        project_name="Example",
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
            model_operation,
            api_operation,
            test_operation,
        ],
        steps=[
            ImplementationStep(
                step_id="step-1",
                position=1,
                title="Model",
                description=(
                    "顧客Modelを更新する。"
                ),
                category="DATA",
                file_operations=[
                    model_operation
                ],
            ),
            ImplementationStep(
                step_id="step-2",
                position=2,
                title="API",
                description=(
                    "顧客登録APIを追加する。"
                ),
                category="BACKEND",
                file_operations=[
                    api_operation
                ],
                depends_on_steps=[
                    "step-1"
                ],
            ),
            ImplementationStep(
                step_id="step-3",
                position=3,
                title="Test",
                description=(
                    "回帰テストを追加する。"
                ),
                category="TEST",
                file_operations=[
                    test_operation
                ],
                depends_on_steps=[
                    "step-2"
                ],
            ),
        ],
        execution_order=[
            "step-1",
            "step-2",
            "step-3",
        ],
        file_execution_order=[
            "app/models.py",
            "app/api/customers.py",
            "tests/test_customers.py",
        ],
        dependency_graph={
            "edges": [
                {
                    "from": "app/models.py",
                    "to": (
                        "app/api/customers.py"
                    ),
                },
                {
                    "from": (
                        "app/api/customers.py"
                    ),
                    "to": (
                        "tests/test_customers.py"
                    ),
                },
            ]
        },
        verification_commands=[
            "python -m pytest"
        ],
        overall_risk_level="MEDIUM",
        estimated_effort_level="SMALL",
        approval_summary=(
            "Model、API、Testを更新する。"
        ),
    )


def _mission() -> dict:
    return {
        "id": 1,
        "project_id": 2,
        "project_name": "Example",
        "title": "顧客登録API",
        "objective": (
            "顧客登録APIとテストを追加する。"
        ),
        "mission_type": "IMPLEMENTATION",
        "success_criteria": (
            "顧客登録テストが成功すること。"
        ),
    }


def _context() -> dict:
    return {
        "mission_id": 1,
        "context_sha256": "a" * 64,
        "files": [
            {
                "relative_path": (
                    "app/api/customers.py"
                ),
                "source": {
                    "included": True,
                    "content": (
                        "def create_customer():\n"
                        "    pass\n"
                    ),
                    "sha256": "b" * 64,
                },
            }
        ],
    }


def test_builds_structured_prompt() -> None:
    prompt = build_code_generation_prompt(
        mission=_mission(),
        requirement=_requirement(),
        implementation_plan=_plan(),
        context=_context(),
        step_id="step-2",
    )

    assert prompt.prompt_version == (
        CODE_GENERATION_PROMPT_VERSION
    )
    assert prompt.mission_id == 1
    assert prompt.implementation_step_id == (
        "step-2"
    )
    assert prompt.target_files == [
        "app/api/customers.py"
    ]
    assert prompt.completed_dependencies == [
        "step-1"
    ]
    assert prompt.remaining_dependencies == [
        "step-3"
    ]


def test_prompt_contains_requirement_and_plan() -> None:
    prompt = build_code_generation_prompt(
        mission=_mission(),
        requirement=_requirement(),
        implementation_plan=_plan(),
        context=_context(),
        step_id="step-2",
    )

    payload = json.loads(
        prompt.user_prompt
    )

    assert payload[
        "requirement_contract"
    ]["constraints"] == [
        "既存APIとの互換性を維持する。"
    ]
    assert payload[
        "current_step"
    ]["step_id"] == "step-2"
    assert payload[
        "target_files"
    ] == [
        "app/api/customers.py"
    ]


def test_prompt_contains_context() -> None:
    prompt = build_code_generation_prompt(
        mission=_mission(),
        requirement=_requirement(),
        implementation_plan=_plan(),
        context=_context(),
        step_id="step-2",
    )

    payload = json.loads(
        prompt.user_prompt
    )

    assert payload[
        "code_context"
    ]["context_sha256"] == "a" * 64
    assert payload[
        "code_context_summary"
    ]["file_count"] == 1
    assert prompt.metadata[
        "context_file_count"
    ] == 1


def test_uses_first_execution_step_by_default() -> None:
    prompt = build_code_generation_prompt(
        mission=_mission(),
        requirement=_requirement(),
        implementation_plan=_plan(),
        context=_context(),
    )

    assert prompt.implementation_step_id == (
        "step-1"
    )
    assert prompt.target_files == [
        "app/models.py"
    ]


def test_rejects_unknown_step() -> None:
    with pytest.raises(
        CodeGenerationPromptBuilderError,
        match="Step",
    ):
        build_code_generation_prompt(
            mission=_mission(),
            requirement=_requirement(),
            implementation_plan=_plan(),
            context=_context(),
            step_id="step-99",
        )


def test_rejects_mission_plan_mismatch() -> None:
    mission = _mission()
    mission["id"] = 99

    with pytest.raises(
        CodeGenerationPromptBuilderError,
        match="一致しません",
    ):
        build_code_generation_prompt(
            mission=mission,
            requirement=_requirement(),
            implementation_plan=_plan(),
            context=_context(),
        )
