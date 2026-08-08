from app.missions.models import RequirementAnalyzerResult
from app.missions.planner_runner import (
    _build_verification_commands,
)


def test_verification_commands_include_pytest_when_requirement_requires_tests(
) -> None:
    files = [
        {
            "path": "backend/app/api/auth.py",
            "category": "BACKEND",
        }
    ]

    requirement = RequirementAnalyzerResult(
        objective=(
            "Resolve the authentication production issue."
        ),
        requirements=[
            "Update only the required backend behavior."
        ],
        success_criteria=[
            "Related tests must pass.",
            "Existing tests must have no regressions.",
        ],
        implementation_possible=True,
        analysis_summary=(
            "Authentication change is implementable."
        ),
    )

    commands = _build_verification_commands(
        files,
        requirement=requirement,
    )

    command_values = [
        item["command"]
        for item in commands
    ]

    assert any(
        "-m pytest" in command
        for command in command_values
    )
