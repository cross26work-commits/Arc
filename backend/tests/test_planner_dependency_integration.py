from app.missions.models import (
    RequirementAnalyzerResult,
)
from app.missions.planner_runner import (
    _build_typed_implementation_plan,
)


def _requirement() -> RequirementAnalyzerResult:
    return RequirementAnalyzerResult(
        objective=(
            "依存関係を考慮してAPIを実装する。"
        ),
        requirements=[
            "Model、Service、Routerを更新する。"
        ],
        success_criteria=[
            "依存順序どおりに計画される。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求である。"
        ),
    )


def _mission() -> dict:
    return {
        "id": 1,
        "project_id": 1,
        "project_name": "Example",
        "objective": (
            "依存関係を考慮してAPIを実装する。"
        ),
        "success_criteria": (
            "依存順序どおりに実装されること。"
        ),
    }


def test_connects_file_dependencies_to_steps() -> None:
    selected_files = [
        {
            "path": "app/models.py",
            "category": "DATA",
            "language": "python",
            "risk_level": "low",
            "score": 10,
            "direct_dependencies": [],
            "direct_dependents": [
                "app/service.py"
            ],
            "reasons": ["Data Model"],
        },
        {
            "path": "app/service.py",
            "category": "BACKEND",
            "language": "python",
            "risk_level": "medium",
            "score": 9,
            "direct_dependencies": [
                "app/models.py"
            ],
            "direct_dependents": [
                "app/router.py"
            ],
            "reasons": ["Service"],
        },
        {
            "path": "app/router.py",
            "category": "FRONTEND",
            "language": "python",
            "risk_level": "low",
            "score": 8,
            "direct_dependencies": [
                "app/service.py"
            ],
            "direct_dependents": [],
            "reasons": ["Router"],
        },
    ]

    workstreams = [
        {
            "position": 1,
            "category": "DATA",
            "title": "Data",
            "files": ["app/models.py"],
            "purpose": "Modelを更新する。",
        },
        {
            "position": 2,
            "category": "BACKEND",
            "title": "Backend",
            "files": ["app/service.py"],
            "purpose": "Serviceを更新する。",
        },
        {
            "position": 3,
            "category": "FRONTEND",
            "title": "Router",
            "files": ["app/router.py"],
            "purpose": "Routerを更新する。",
        },
    ]

    plan = _build_typed_implementation_plan(
        mission=_mission(),
        requirement=_requirement(),
        selected_files=selected_files,
        workstreams=workstreams,
        verification_commands=[],
        risk={"level": "medium"},
        effort={"level": "small"},
        approval_summary=(
            "依存順序に従って更新する。"
        ),
    )

    assert plan.file_execution_order == [
        "app/models.py",
        "app/service.py",
        "app/router.py",
    ]
    assert plan.execution_order == [
        "step-1",
        "step-2",
        "step-3",
    ]
    assert plan.steps[0].depends_on_steps == []
    assert plan.steps[1].depends_on_steps == [
        "step-1"
    ]
    assert plan.steps[2].depends_on_steps == [
        "step-2"
    ]
    assert plan.dependency_graph[
        "edge_count"
    ] == 2


def test_marks_independent_steps_parallel() -> None:
    selected_files = [
        {
            "path": "app/backend.py",
            "category": "BACKEND",
            "language": "python",
            "risk_level": "low",
            "score": 10,
            "direct_dependencies": [],
            "direct_dependents": [],
            "reasons": ["Backend"],
        },
        {
            "path": "frontend/page.tsx",
            "category": "FRONTEND",
            "language": "typescript",
            "risk_level": "low",
            "score": 9,
            "direct_dependencies": [],
            "direct_dependents": [],
            "reasons": ["Frontend"],
        },
    ]

    workstreams = [
        {
            "position": 1,
            "category": "BACKEND",
            "title": "Backend",
            "files": ["app/backend.py"],
            "purpose": "Backendを更新する。",
        },
        {
            "position": 2,
            "category": "FRONTEND",
            "title": "Frontend",
            "files": ["frontend/page.tsx"],
            "purpose": "Frontendを更新する。",
        },
    ]

    plan = _build_typed_implementation_plan(
        mission=_mission(),
        requirement=_requirement(),
        selected_files=selected_files,
        workstreams=workstreams,
        verification_commands=[],
        risk={"level": "low"},
        effort={"level": "small"},
        approval_summary=(
            "独立した変更を実行する。"
        ),
    )

    assert plan.parallel_groups == [
        [
            "step-1",
            "step-2",
        ]
    ]
    assert plan.steps[0].can_run_in_parallel is True
    assert plan.steps[1].can_run_in_parallel is True
    assert plan.steps[0].depends_on_steps == []
    assert plan.steps[1].depends_on_steps == []


def test_cycle_uses_safe_sequential_fallback() -> None:
    selected_files = [
        {
            "path": "app/a.py",
            "category": "BACKEND",
            "language": "python",
            "risk_level": "medium",
            "score": 10,
            "direct_dependencies": [
                "app/b.py"
            ],
            "direct_dependents": [
                "app/b.py"
            ],
            "reasons": ["A"],
        },
        {
            "path": "app/b.py",
            "category": "TEST",
            "language": "python",
            "risk_level": "medium",
            "score": 9,
            "direct_dependencies": [
                "app/a.py"
            ],
            "direct_dependents": [
                "app/a.py"
            ],
            "reasons": ["B"],
        },
    ]

    workstreams = [
        {
            "position": 1,
            "category": "BACKEND",
            "title": "A",
            "files": ["app/a.py"],
            "purpose": "Aを更新する。",
        },
        {
            "position": 2,
            "category": "TEST",
            "title": "B",
            "files": ["app/b.py"],
            "purpose": "Bを更新する。",
        },
    ]

    plan = _build_typed_implementation_plan(
        mission=_mission(),
        requirement=_requirement(),
        selected_files=selected_files,
        workstreams=workstreams,
        verification_commands=[],
        risk={"level": "medium"},
        effort={"level": "small"},
        approval_summary=(
            "循環依存を確認する。"
        ),
    )

    assert len(plan.dependency_cycles) == 1
    assert plan.execution_order == [
        "step-1",
        "step-2",
    ]
    assert plan.steps[0].depends_on_steps == []
    assert plan.steps[1].depends_on_steps == [
        "step-1"
    ]
    assert plan.parallel_groups == []
