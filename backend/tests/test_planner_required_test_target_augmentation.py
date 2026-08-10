from app.missions import planner_runner
from app.missions.models import RequirementAnalyzerResult


def _requirement() -> RequirementAnalyzerResult:
    return RequirementAnalyzerResult(
        objective=(
            "Update the authentication backend."
        ),
        requirements=[
            "Change only the required behavior.",
        ],
        success_criteria=[
            "Add or update focused regression tests.",
        ],
        implementation_possible=True,
        analysis_summary=(
            "The requested change is implementable."
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


def test_adds_derived_test_target_when_requirement_needs_test_mutation(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    api_dir = backend / "app" / "api"

    api_dir.mkdir(
        parents=True,
    )

    (backend / "requirements.txt").write_text(
        "fastapi==0.138.2\n"
        "pytest==8.4.1\n",
        encoding="utf-8",
    )

    (api_dir / "auth.py").write_text(
        "def current_user():\n"
        "    return None\n",
        encoding="utf-8",
    )

    augment = getattr(
        planner_runner,
        "_augment_required_test_mutation_target",
        None,
    )

    assert augment is not None, (
        "Planner must augment required TEST "
        "mutation targets before workstream planning."
    )

    selected = augment(
        project_path=str(tmp_path),
        selected_files=[
            _backend_file(),
        ],
        requirement=_requirement(),
    )

    assert [
        item["path"]
        for item in selected
    ] == [
        "backend/app/api/auth.py",
        "backend/tests/test_auth.py",
    ]

    assert selected[1]["category"] == "TEST"


def test_does_not_add_test_target_when_mutation_is_not_required(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()

    (backend / "requirements.txt").write_text(
        "pytest==8.4.1\n",
        encoding="utf-8",
    )

    requirement = RequirementAnalyzerResult(
        objective=(
            "Update the authentication backend."
        ),
        requirements=[
            "Change only the required behavior.",
        ],
        success_criteria=[
            "Existing regression tests must pass.",
        ],
        implementation_possible=True,
        analysis_summary=(
            "The requested change is implementable."
        ),
    )

    selected = (
        planner_runner
        ._augment_required_test_mutation_target(
            project_path=str(tmp_path),
            selected_files=[
                _backend_file(),
            ],
            requirement=requirement,
        )
    )

    assert [
        item["path"]
        for item in selected
    ] == [
        "backend/app/api/auth.py",
    ]


def test_does_not_duplicate_existing_test_target(
    tmp_path,
) -> None:
    existing_test = {
        "path": "backend/tests/test_auth.py",
        "role": "existing auth tests",
        "language": "python",
        "score": 40,
        "category": "TEST",
        "risk_level": "low",
        "risk_score": 5,
        "direct_dependencies": [
            "backend/app/api/auth.py",
        ],
        "direct_dependents": [],
        "affected_count": 0,
        "reasons": [
            "Existing regression test target.",
        ],
        "warnings": [],
        "dependency": {},
    }

    selected = (
        planner_runner
        ._augment_required_test_mutation_target(
            project_path=str(tmp_path),
            selected_files=[
                _backend_file(),
                existing_test,
            ],
            requirement=_requirement(),
        )
    )

    assert [
        item["path"]
        for item in selected
    ] == [
        "backend/app/api/auth.py",
        "backend/tests/test_auth.py",
    ]
