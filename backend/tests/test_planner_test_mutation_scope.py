import pytest

from app.missions import planner_runner
from app.missions.models import RequirementAnalyzerResult


def _requirement(
    *,
    success_criteria: list[str],
) -> RequirementAnalyzerResult:
    return RequirementAnalyzerResult(
        objective=(
            "Update the required backend behavior."
        ),
        requirements=[
            "Change only the required backend behavior.",
        ],
        success_criteria=success_criteria,
        implementation_possible=True,
        analysis_summary=(
            "The requested backend change is implementable."
        ),
    )


def _backend_file() -> dict:
    return {
        "path": "backend/app/api/auth.py",
        "role": "auth API routes",
        "language": "python",
        "score": 50,
        "category": "BACKEND",
        "risk_level": "low",
        "risk_score": 10,
        "direct_dependencies": [],
        "direct_dependents": [],
        "affected_count": 0,
        "reasons": [
            "Authentication backend target.",
        ],
        "warnings": [],
        "dependency": {},
    }


def test_rejects_plan_without_test_mutation_when_tests_must_be_added() -> None:
    validator = getattr(
        planner_runner,
        "_validate_required_mutation_scope",
        None,
    )

    assert validator is not None, (
        "Planner must provide a mutation-scope "
        "requirement validator."
    )

    requirement = _requirement(
        success_criteria=[
            "Add or update focused regression tests.",
        ],
    )

    with pytest.raises(
        planner_runner.MissionPlannerError,
        match="TEST",
    ):
        validator(
            selected_files=[
                _backend_file(),
            ],
            requirement=requirement,
        )


def test_typed_plan_rejects_missing_required_test_mutation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        planner_runner,
        "_get_project_path",
        lambda project_id: str(tmp_path),
    )

    requirement = _requirement(
        success_criteria=[
            "Add or update focused regression tests.",
        ],
    )

    selected_files = [
        _backend_file(),
    ]

    workstreams = [
        {
            "position": 1,
            "category": "BACKEND",
            "title": "Backend",
            "file_count": 1,
            "files": [
                "backend/app/api/auth.py",
            ],
            "purpose": (
                "Update the required authentication behavior."
            ),
        },
    ]

    with pytest.raises(
        planner_runner.MissionPlannerError,
        match="TEST",
    ):
        planner_runner._build_typed_implementation_plan(
            mission={
                "id": 22,
                "project_id": 1,
                "project_name": "Example",
                "objective": requirement.objective,
                "success_criteria": (
                    "Add or update focused regression tests."
                ),
            },
            requirement=requirement,
            selected_files=selected_files,
            workstreams=workstreams,
            verification_commands=[],
            risk={
                "level": "low",
            },
            effort={
                "level": "small",
            },
            approval_summary=(
                "Update the required authentication behavior."
            ),
        )


def test_allows_backend_only_scope_when_tests_only_need_to_pass() -> None:
    requirement = _requirement(
        success_criteria=[
            "Existing regression tests must pass.",
            "Run pytest and confirm there are no regressions.",
        ],
    )

    planner_runner._validate_required_mutation_scope(
        selected_files=[
            _backend_file(),
        ],
        requirement=requirement,
    )


def test_rejects_missing_test_target_for_japanese_test_mutation_requirement() -> None:
    requirement = _requirement(
        success_criteria=[
            "\u30c6\u30b9\u30c8\u3092\u8ffd\u52a0\u3059\u308b\u3002",
        ],
    )

    with pytest.raises(
        planner_runner.MissionPlannerError,
        match="TEST",
    ):
        planner_runner._validate_required_mutation_scope(
            selected_files=[
                _backend_file(),
            ],
            requirement=requirement,
        )


def test_allows_backend_only_scope_when_japanese_requirement_forbids_test_changes() -> None:
    requirement = _requirement(
        success_criteria=[
            "\u30c6\u30b9\u30c8\u3092\u8ffd\u52a0\u3057\u306a\u3044\u3002",
            "\u65e2\u5b58\u30c6\u30b9\u30c8\u304c\u6210\u529f\u3059\u308b\u3053\u3068\u3002",
        ],
    )

    planner_runner._validate_required_mutation_scope(
        selected_files=[
            _backend_file(),
        ],
        requirement=requirement,
    )
