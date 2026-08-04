from __future__ import annotations

import json
from typing import Any

from app.missions.models import MissionTaskUpdate
from app.missions.requirement_analyzer import (
    RequirementAnalyzerError,
    analyze_requirement,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
    update_mission_task,
)


REQUIREMENT_RUNNER_VERSION = (
    "mission-requirement-runner-v0.1"
)


class MissionRequirementError(Exception):
    """Mission要求整理に失敗した場合の例外。"""


def _requirements_task(
    mission: dict[str, Any],
) -> dict[str, Any] | None:
    return next(
        (
            task
            for task in mission.get("tasks", [])
            if task.get("task_type") == "REQUIREMENTS"
        ),
        None,
    )


def _run_mission_requirements_impl(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    task = _requirements_task(mission)

    if task is None:
        raise MissionRequirementError(
            "REQUIREMENTS Taskが見つかりません。"
        )

    status = str(
        task.get("status") or ""
    ).strip().upper()

    if status == "COMPLETED":
        raw_result = task.get("result")

        if not raw_result:
            raise MissionRequirementError(
                "REQUIREMENTS Taskは完了していますが、"
                "Requirement Contractがありません。"
            )

        try:
            contract = json.loads(raw_result)
        except json.JSONDecodeError as error:
            raise MissionRequirementError(
                "保存済みRequirement Contractを"
                "読み取れません。"
            ) from error

        return {
            "runner_version":
                REQUIREMENT_RUNNER_VERSION,
            "mission": mission,
            "requirement_contract": contract,
            "already_completed": True,
        }

    if status not in {
        "READY",
        "RUNNING",
    }:
        raise MissionRequirementError(
            "REQUIREMENTS Taskは"
            "実行可能状態ではありません: "
            f"{status or 'NONE'}"
        )

    if status == "READY":
        mission = update_mission_task(
            mission_id=mission_id,
            task_id=task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

        task = _requirements_task(mission)

        if task is None:
            raise MissionRequirementError(
                "RUNNING更新後のREQUIREMENTS Taskを"
                "取得できません。"
            )

    result = analyze_requirement(
        objective=mission["objective"],
        success_criteria=(
            mission.get("success_criteria")
        ),
    )

    contract = result.model_dump(
        mode="json"
    )

    result_text = json.dumps(
        contract,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionRequirementError(
            "Requirement Contractが"
            "保存上限を超えました。"
        )

    mission = update_mission_task(
        mission_id=mission_id,
        task_id=task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_REQUIREMENTS_COMPLETED"
        ),
        message=(
            "要求を構造化し、"
            "Requirement Contractを保存しました。"
        ),
        metadata={
            "runner_version":
                REQUIREMENT_RUNNER_VERSION,
            "contract_version":
                result.contract_version,
            "implementation_possible":
                result.implementation_possible,
            "requirement_count":
                len(result.requirements),
            "success_criteria_count":
                len(result.success_criteria),
            "ambiguity_count":
                len(result.ambiguities),
            "missing_information_count":
                len(result.missing_information),
            "risk_count":
                len(result.risks),
        },
    )

    return {
        "runner_version":
            REQUIREMENT_RUNNER_VERSION,
        "mission": mission,
        "requirement_contract": contract,
        "already_completed": False,
    }


def run_mission_requirements(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return _run_mission_requirements_impl(
            mission_id
        )

    except (
        MissionRequirementError,
        MissionError,
        RequirementAnalyzerError,
    ):
        raise

    except Exception as error:
        raise MissionRequirementError(
            "Mission要求整理に失敗しました。"
            f" 原因: {error}"
        ) from error


def run_mission_requirements_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        result = run_mission_requirements(
            mission_id
        )

        return {
            "ok": True,
            "runner_version":
                REQUIREMENT_RUNNER_VERSION,
            "result": result,
            "error": None,
        }

    except Exception as error:
        return {
            "ok": False,
            "runner_version":
                REQUIREMENT_RUNNER_VERSION,
            "result": None,
            "error": {
                "type": type(error).__name__,
                "message": str(error),
            },
        }
