import json

from app.missions.code_generation_runner import (
    _build_generation_prompts,
    _load_prompt_inputs,
)
from app.missions.models import (
    FileOperation,
    ImplementationPlan,
    ImplementationStep,
    RequirementAnalyzerResult,
)


def _requirement() -> RequirementAnalyzerResult:
    return RequirementAnalyzerResult(
        objective="顧客APIを実装する。",
        requirements=[
            "顧客APIを追加する。"
        ],
        success_criteria=[
            "APIテストが成功する。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求である。"
        ),
    )


def _typed_plan() -> ImplementationPlan:
    requirement = _requirement()

    operation = FileOperation(
        path="app/api/customers.py",
        operation="UPDATE",
        purpose="顧客APIを追加する。",
        category="BACKEND",
    )

    step = ImplementationStep(
        step_id="step-1",
        position=1,
        title="API",
        description="顧客APIを実装する。",
        category="BACKEND",
        file_operations=[operation],
    )

    return ImplementationPlan(
        mission_id=1,
        project_id=1,
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
        selected_files=[operation],
        steps=[step],
        execution_order=["step-1"],
        file_execution_order=[
            "app/api/customers.py"
        ],
        verification_commands=[
            "python -m pytest"
        ],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary=(
            "顧客APIを追加する。"
        ),
    )


def _mission() -> dict:
    requirement = _requirement()
    typed_plan = _typed_plan()

    return {
        "id": 1,
        "project_id": 1,
        "project_name": "Example",
        "title": "顧客API",
        "objective": requirement.objective,
        "mission_type": "IMPLEMENTATION",
        "success_criteria": (
            "APIテストが成功すること。"
        ),
        "tasks": [
            {
                "task_type": "REQUIREMENTS",
                "status": "COMPLETED",
                "result": json.dumps(
                    requirement.model_dump(
                        mode="json"
                    ),
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "PLANNING",
                "status": "COMPLETED",
                "result": json.dumps(
                    {
                        "typed_plan": (
                            typed_plan.model_dump(
                                mode="json"
                            )
                        )
                    },
                    ensure_ascii=False,
                ),
            },
        ],
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
                        "def customer():\n"
                        "    pass\n"
                    ),
                    "sha256": "b" * 64,
                },
            }
        ],
    }


def test_loads_requirement_and_typed_plan() -> None:
    requirement, plan = _load_prompt_inputs(
        _mission()
    )

    assert requirement.objective == (
        "顧客APIを実装する。"
    )
    assert plan.plan_version == (
        "implementation-plan-v0.1"
    )
    assert plan.execution_order == [
        "step-1"
    ]


def test_builds_structured_generation_prompt() -> None:
    bundle = _build_generation_prompts(
        mission=_mission(),
        context=_context(),
    )

    assert bundle["mode"] == "STRUCTURED"
    assert bundle["prompt_version"] == (
        "code-generation-prompt-v0.1"
    )
    assert bundle[
        "implementation_step_id"
    ] == "step-1"
    assert bundle["target_files"] == [
        "app/api/customers.py"
    ]
    assert bundle["fallback_reason"] is None


def test_structured_prompt_contains_typed_data() -> None:
    bundle = _build_generation_prompts(
        mission=_mission(),
        context=_context(),
    )

    payload = json.loads(
        bundle["user_prompt"]
    )

    assert payload[
        "requirement_contract"
    ]["objective"] == (
        "顧客APIを実装する。"
    )
    assert payload[
        "current_step"
    ]["step_id"] == "step-1"
    assert payload["target_files"] == [
        "app/api/customers.py"
    ]


def test_falls_back_when_typed_plan_missing() -> None:
    mission = _mission()

    planning_task = next(
        task
        for task in mission["tasks"]
        if task["task_type"] == "PLANNING"
    )

    planning_task["result"] = json.dumps(
        {
            "plan_version":
                "mission-planner-v0.2"
        }
    )

    bundle = _build_generation_prompts(
        mission=mission,
        context=_context(),
    )

    assert bundle["mode"] == (
        "LEGACY_FALLBACK"
    )
    assert bundle["prompt_version"] == (
        "legacy-code-generation-prompt-v0.1"
    )
    assert bundle["fallback_reason"] is not None
    assert bundle["target_files"] == []
