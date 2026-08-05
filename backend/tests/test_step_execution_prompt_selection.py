import json

from app.missions.code_generation_runner import (
    _build_generation_prompts,
    _load_current_step_id,
)
from app.missions.implementation_runner import (
    _initialize_plan_step_execution,
)
from app.missions.models import (
    FileOperation,
    ImplementationPlan,
    ImplementationStep,
    RequirementAnalyzerResult,
)


def _requirement() -> RequirementAnalyzerResult:
    return RequirementAnalyzerResult(
        objective="APIとテストを実装する。",
        requirements=[
            "APIを実装する。",
            "テストを実装する。",
        ],
        success_criteria=[
            "テストが成功する。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求である。"
        ),
    )


def _plan() -> ImplementationPlan:
    requirement = _requirement()

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
        file_execution_order=[
            "app/api.py",
            "tests/test_api.py",
        ],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary=(
            "APIとテストを実装する。"
        ),
    )


def _legacy_plan_payload() -> dict:
    plan = _plan()

    return {
        "plan_version":
            "mission-planner-v0.3",
        "selected_files": [
            {
                "path": "app/api.py"
            },
            {
                "path": "tests/test_api.py"
            },
        ],
        "verification_commands": [],
        "typed_plan": plan.model_dump(
            mode="json"
        ),
    }


def _mission(
    *,
    current_step_id: str = "step-2",
) -> dict:
    requirement = _requirement()
    plan = _plan()

    execution = (
        _initialize_plan_step_execution(
            _legacy_plan_payload()
        )
    )

    assert execution is not None

    execution["current_step_id"] = (
        current_step_id
    )

    return {
        "id": 1,
        "project_id": 1,
        "project_name": "Example",
        "title": "API実装",
        "objective": requirement.objective,
        "mission_type": "IMPLEMENTATION",
        "success_criteria": (
            "テストが成功すること。"
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
                            plan.model_dump(
                                mode="json"
                            )
                        )
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "IMPLEMENTATION",
                "status": "RUNNING",
                "result": json.dumps(
                    {
                        "mode": "BACKUP_READY",
                        "step_execution":
                            execution,
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
                "relative_path":
                    "app/api.py",
                "source": {
                    "included": True,
                    "content": "pass\n",
                    "sha256": "b" * 64,
                },
            },
            {
                "relative_path":
                    "tests/test_api.py",
                "source": {
                    "included": True,
                    "content": "pass\n",
                    "sha256": "c" * 64,
                },
            },
        ],
    }


def test_initializes_step_execution_from_typed_plan() -> None:
    execution = (
        _initialize_plan_step_execution(
            _legacy_plan_payload()
        )
    )

    assert execution is not None
    assert execution["current_step_id"] == (
        "step-1"
    )
    assert execution[
        "remaining_step_ids"
    ] == [
        "step-1",
        "step-2",
    ]


def test_legacy_plan_without_typed_plan_returns_none() -> None:
    execution = (
        _initialize_plan_step_execution(
            {
                "selected_files": [
                    {
                        "path": "app/api.py"
                    }
                ]
            }
        )
    )

    assert execution is None


def test_loads_current_step_from_implementation() -> None:
    step_id = _load_current_step_id(
        _mission(
            current_step_id="step-2"
        )
    )

    assert step_id == "step-2"


def test_prompt_uses_persisted_current_step() -> None:
    mission = _mission(
        current_step_id="step-2"
    )

    step_id = _load_current_step_id(
        mission
    )

    bundle = _build_generation_prompts(
        mission=mission,
        context=_context(),
        step_id=step_id,
    )

    assert bundle["mode"] == "STRUCTURED"
    assert bundle[
        "implementation_step_id"
    ] == "step-2"
    assert bundle["target_files"] == [
        "tests/test_api.py"
    ]


def test_missing_implementation_state_uses_plan_default() -> None:
    mission = _mission()

    mission["tasks"] = [
        task
        for task in mission["tasks"]
        if task["task_type"]
        != "IMPLEMENTATION"
    ]

    step_id = _load_current_step_id(
        mission
    )

    bundle = _build_generation_prompts(
        mission=mission,
        context=_context(),
        step_id=step_id,
    )

    assert step_id is None
    assert bundle[
        "implementation_step_id"
    ] == "step-1"
