from app.missions.models import (
    RequirementAnalyzerResult,
)
from app.missions.planner_runner import (
    _build_typed_implementation_plan,
)


def _mission() -> dict:
    return {
        "id": 1,
        "project_id": 2,
        "project_name": "Example",
        "objective": (
            "顧客登録APIとテストを追加する。"
        ),
        "success_criteria": (
            "APIとテストが正常に動作すること。"
        ),
    }


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
        in_scope=[
            "Backend",
            "Test",
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求である。"
        ),
    )


def test_builds_typed_plan_from_legacy_data() -> None:
    selected_files = [
        {
            "path": "backend/app/api/customers.py",
            "role": "api",
            "language": "python",
            "score": 10,
            "category": "BACKEND",
            "risk_level": "medium",
            "risk_score": 20,
            "direct_dependencies": [],
            "direct_dependents": [
                "backend/tests/test_customers.py"
            ],
            "affected_count": 1,
            "reasons": [
                "顧客登録APIの対象ファイル。"
            ],
        },
        {
            "path": "backend/tests/test_customers.py",
            "role": "test",
            "language": "python",
            "score": 8,
            "category": "TEST",
            "risk_level": "low",
            "risk_score": 5,
            "direct_dependencies": [
                "backend/app/api/customers.py"
            ],
            "direct_dependents": [],
            "affected_count": 0,
            "reasons": [
                "回帰テストの対象ファイル。"
            ],
        },
    ]

    workstreams = [
        {
            "position": 1,
            "category": "BACKEND",
            "title": "Backend・API",
            "file_count": 1,
            "files": [
                "backend/app/api/customers.py"
            ],
            "purpose": (
                "顧客登録APIを実装する。"
            ),
        },
        {
            "position": 2,
            "category": "TEST",
            "title": "テスト",
            "file_count": 1,
            "files": [
                "backend/tests/test_customers.py"
            ],
            "purpose": (
                "顧客登録APIのテストを追加する。"
            ),
        },
    ]

    verification = [
        {
            "name": "Python構文確認",
            "command": (
                "cd backend && "
                "venv/Scripts/python.exe "
                "-m compileall -q app"
            ),
        },
        {
            "name": "自動テスト",
            "command": (
                "cd backend && "
                "venv/Scripts/python.exe "
                "-m pytest"
            ),
        },
    ]

    plan = _build_typed_implementation_plan(
        mission=_mission(),
        requirement=_requirement(),
        selected_files=selected_files,
        workstreams=workstreams,
        verification_commands=verification,
        risk={
            "level": "medium",
        },
        effort={
            "level": "small",
        },
        approval_summary=(
            "APIとテストを更新する。"
        ),
    )

    assert plan.plan_version == (
        "implementation-plan-v0.1"
    )
    assert len(plan.selected_files) == 2
    assert len(plan.steps) == 2
    assert plan.execution_order == [
        "step-1",
        "step-2",
    ]
    assert plan.steps[1].depends_on_steps == [
        "step-1"
    ]
    assert plan.overall_risk_level == "MEDIUM"
    assert plan.estimated_effort_level == "SMALL"


def test_typed_plan_generates_clarification() -> None:
    requirement = RequirementAnalyzerResult(
        objective="認証機能を改善する。",
        ambiguities=[
            "改善内容が明確ではない。"
        ],
        missing_information=[
            "対象認証方式が不明。"
        ],
        implementation_possible=False,
        analysis_summary=(
            "追加確認が必要である。"
        ),
    )

    plan = _build_typed_implementation_plan(
        mission={
            "id": 1,
            "project_id": 1,
            "project_name": "Example",
            "objective": requirement.objective,
            "success_criteria": "",
        },
        requirement=requirement,
        selected_files=[],
        workstreams=[],
        verification_commands=[],
        risk={
            "level": "unknown",
        },
        effort={
            "level": "unknown",
        },
        approval_summary=(
            "実装前に確認が必要である。"
        ),
    )

    assert plan.clarification_required is True
    assert len(plan.clarification_questions) == 2
    assert plan.implementation_possible is False
