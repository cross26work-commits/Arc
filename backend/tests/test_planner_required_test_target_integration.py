import json

from app.missions import planner_runner
from app.missions.models import RequirementAnalyzerResult


def _candidate() -> dict:
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
        "dependency": {
            "risk": {
                "level": "low",
                "score": 10,
            },
        },
    }


def test_main_planner_adds_derived_test_target_before_workstreams(
    monkeypatch,
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

    requirement = RequirementAnalyzerResult(
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

    mission = {
        "id": 22,
        "project_id": 1,
        "project_name": "Example",
        "title": "Authentication production readiness",
        "objective": requirement.objective,
        "success_criteria": (
            "Add or update focused regression tests."
        ),
        "tasks": [
            {
                "id": 118,
                "task_type": "REQUIREMENTS",
                "status": "COMPLETED",
                "result": requirement.model_dump_json(),
                "target_path": None,
            },
            {
                "id": 119,
                "task_type": "ANALYSIS",
                "status": "COMPLETED",
                "result": json.dumps(
                    {
                        "analysis_version": (
                            "analysis-v0.1"
                        ),
                        "candidates": [
                            _candidate(),
                        ],
                    }
                ),
                "target_path": None,
            },
            {
                "id": 120,
                "task_type": "PLANNING",
                "status": "READY",
                "result": None,
                "target_path": None,
            },
        ],
    }

    state = {
        "mission": mission,
        "completed_result": None,
    }

    def fake_get_mission(mission_id: int) -> dict:
        assert mission_id == 22
        return state["mission"]

    def fake_update_mission_task(
        *,
        mission_id: int,
        task_id: int,
        payload,
    ) -> dict:
        assert mission_id == 22

        updated_tasks = []

        for task in state["mission"]["tasks"]:
            updated = dict(task)

            if task["id"] == task_id:
                if payload.status is not None:
                    updated["status"] = payload.status

                if payload.result is not None:
                    updated["result"] = payload.result
                    state["completed_result"] = (
                        payload.result
                    )

                if payload.target_path is not None:
                    updated["target_path"] = (
                        payload.target_path
                    )

            updated_tasks.append(updated)

        state["mission"] = {
            **state["mission"],
            "tasks": updated_tasks,
        }

        return state["mission"]

    monkeypatch.setattr(
        planner_runner,
        "get_mission",
        fake_get_mission,
    )
    monkeypatch.setattr(
        planner_runner,
        "update_mission_task",
        fake_update_mission_task,
    )
    monkeypatch.setattr(
        planner_runner,
        "add_mission_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        planner_runner,
        "_get_project_path",
        lambda project_id: str(tmp_path),
    )

    planner_runner._run_mission_planner_impl(22)

    assert state["completed_result"] is not None

    plan = json.loads(
        state["completed_result"]
    )

    assert [
        item["path"]
        for item in plan["selected_files"]
    ] == [
        "backend/app/api/auth.py",
        "backend/tests/test_auth.py",
    ]

    assert any(
        stream["category"] == "TEST"
        and "backend/tests/test_auth.py"
        in stream["files"]
        for stream in plan["workstreams"]
    )

    typed_files = {
        item["path"]: item
        for item in plan["typed_plan"][
            "selected_files"
        ]
    }

    assert (
        typed_files[
            "backend/tests/test_auth.py"
        ]["operation"]
        == "CREATE"
    )
