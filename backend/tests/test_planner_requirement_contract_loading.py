import json

import pytest

from app.missions.planner_runner import (
    MissionPlannerError,
    _load_requirement_contract,
)


def _valid_contract() -> dict:
    return {
        "contract_version": "requirement-contract-v0.1",
        "objective": "既存APIへ顧客登録機能を追加する。",
        "requirements": [
            "顧客登録APIを追加する。"
        ],
        "success_criteria": [
            "顧客登録テストが成功する。"
        ],
        "in_scope": [
            "Backend"
        ],
        "out_of_scope": [],
        "constraints": [],
        "ambiguities": [],
        "missing_information": [],
        "risks": [],
        "implementation_possible": True,
        "analysis_summary": (
            "顧客登録機能は実装可能である。"
        ),
    }


def test_loads_saved_requirement_contract() -> None:
    task = {
        "status": "COMPLETED",
        "result": json.dumps(
            _valid_contract(),
            ensure_ascii=False,
        ),
    }

    requirement = _load_requirement_contract(task)

    assert requirement.objective == (
        "既存APIへ顧客登録機能を追加する。"
    )
    assert requirement.implementation_possible is True
    assert requirement.contract_version == (
        "requirement-contract-v0.1"
    )


def test_accepts_requirement_contract_dict() -> None:
    task = {
        "status": "COMPLETED",
        "result": _valid_contract(),
    }

    requirement = _load_requirement_contract(task)

    assert len(requirement.requirements) == 1
    assert len(requirement.success_criteria) == 1


def test_rejects_invalid_requirement_json() -> None:
    task = {
        "status": "COMPLETED",
        "result": "{invalid-json",
    }

    with pytest.raises(
        MissionPlannerError,
        match="JSON",
    ):
        _load_requirement_contract(task)


def test_rejects_incomplete_requirement_contract() -> None:
    task = {
        "status": "COMPLETED",
        "result": json.dumps(
            {
                "objective": "顧客機能を追加する。",
            },
            ensure_ascii=False,
        ),
    }

    with pytest.raises(
        MissionPlannerError,
        match="Requirement Contract",
    ):
        _load_requirement_contract(task)


def test_rejects_uncompleted_requirements_task() -> None:
    task = {
        "status": "RUNNING",
        "result": json.dumps(
            _valid_contract(),
            ensure_ascii=False,
        ),
    }

    with pytest.raises(
        MissionPlannerError,
        match="完了していません",
    ):
        _load_requirement_contract(task)
