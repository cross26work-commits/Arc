import json

import pytest

import app.missions.requirement_runner as runner


def _mission(
    *,
    task_status: str = "READY",
    task_result: str | None = None,
) -> dict:
    return {
        "id": 1,
        "project_id": 1,
        "project_name": "Profit Radar",
        "objective": (
            "返信画面を使いやすく改善する"
        ),
        "success_criteria": (
            "返信画面が正常に動作すること"
        ),
        "tasks": [
            {
                "id": 11,
                "mission_id": 1,
                "position": 1,
                "title": "目的と成功条件を整理",
                "description": "要求を整理する",
                "task_type": "REQUIREMENTS",
                "status": task_status,
                "target_path": None,
                "result": task_result,
            },
            {
                "id": 12,
                "mission_id": 1,
                "position": 2,
                "title": "対象コードを調査",
                "description": "コードを調査する",
                "task_type": "ANALYSIS",
                "status": "PENDING",
                "target_path": None,
                "result": None,
            },
        ],
    }


def test_requirement_runner_saves_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "mission": _mission(),
        "logs": [],
    }

    def fake_get_mission(
        mission_id: int,
    ) -> dict:
        assert mission_id == 1
        return state["mission"]

    def fake_update_mission_task(
        *,
        mission_id: int,
        task_id: int,
        payload,
    ) -> dict:
        assert mission_id == 1
        assert task_id == 11

        mission = state["mission"]
        requirements = mission["tasks"][0]

        requirements["status"] = payload.status

        if payload.result is not None:
            requirements["result"] = payload.result

        if payload.status == "COMPLETED":
            mission["tasks"][1]["status"] = "READY"

        return mission

    def fake_add_mission_log(**kwargs) -> None:
        state["logs"].append(kwargs)

    monkeypatch.setattr(
        runner,
        "get_mission",
        fake_get_mission,
    )
    monkeypatch.setattr(
        runner,
        "update_mission_task",
        fake_update_mission_task,
    )
    monkeypatch.setattr(
        runner,
        "add_mission_log",
        fake_add_mission_log,
    )

    result = runner.run_mission_requirements(1)

    contract = result["requirement_contract"]

    assert result["already_completed"] is False
    assert contract["objective"] == (
        "返信画面を使いやすく改善する"
    )

    requirements_task = state["mission"]["tasks"][0]

    assert requirements_task["status"] == "COMPLETED"

    stored = json.loads(
        requirements_task["result"]
    )

    assert stored["contract_version"] == (
        "requirement-contract-v0.1"
    )

    assert state["mission"]["tasks"][1][
        "status"
    ] == "READY"

    assert state["logs"][0][
        "event_type"
    ] == "MISSION_REQUIREMENTS_COMPLETED"


def test_requirement_runner_returns_saved_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = {
        "contract_version":
            "requirement-contract-v0.1",
        "objective": "既存要求",
    }

    monkeypatch.setattr(
        runner,
        "get_mission",
        lambda mission_id: _mission(
            task_status="COMPLETED",
            task_result=json.dumps(
                contract,
                ensure_ascii=False,
            ),
        ),
    )

    result = runner.run_mission_requirements(1)

    assert result["already_completed"] is True
    assert result["requirement_contract"] == contract


def test_requirement_runner_rejects_invalid_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "get_mission",
        lambda mission_id: _mission(
            task_status="PENDING",
        ),
    )

    with pytest.raises(
        runner.MissionRequirementError
    ):
        runner.run_mission_requirements(1)


def test_requirement_runner_safe_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "get_mission",
        lambda mission_id: _mission(
            task_status="PENDING",
        ),
    )

    response = (
        runner.run_mission_requirements_safe(1)
    )

    assert response["ok"] is False
    assert response["result"] is None
    assert response["error"]["type"] == (
        "MissionRequirementError"
    )
