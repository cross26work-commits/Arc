from __future__ import annotations

import json
from typing import Any

from app.missions.models import MissionTaskUpdate
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
    update_mission_task,
)


ANALYSIS_REPORTING_VERSION = (
    "mission-analysis-reporting-v0.1"
)


class MissionAnalysisReportingError(Exception):
    """分析Mission報告処理に失敗した場合の例外。"""


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in mission["tasks"]
            if item["task_type"] == task_type
        ),
        None,
    )

    if task is None:
        raise MissionAnalysisReportingError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _load_result(
    task: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    raw = task.get("result")

    if not raw:
        raise MissionAnalysisReportingError(
            f"{label}結果が保存されていません。"
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MissionAnalysisReportingError(
            f"{label}結果のJSONを読み取れません。"
        ) from error

    if not isinstance(result, dict):
        raise MissionAnalysisReportingError(
            f"{label}結果の形式が不正です。"
        )

    return result


def _safe_list(
    value: Any,
) -> list[Any]:
    if isinstance(value, list):
        return value

    return []


def _extract_recommendations(
    analysis: dict[str, Any],
    planning: dict[str, Any],
) -> list[Any]:
    recommendations: list[Any] = []

    selected_files = _safe_list(
        planning.get("selected_files")
    )

    for item in selected_files:
        if not isinstance(item, dict):
            continue

        path = str(
            item.get("path") or ""
        ).strip()

        if not path:
            continue

        warnings = _safe_list(
            item.get("warnings")
        )

        for warning in warnings:
            if not isinstance(warning, dict):
                continue

            level = str(
                warning.get("level") or ""
            ).strip().lower()

            if level not in {
                "high",
                "medium",
            }:
                continue

            code = str(
                warning.get("code") or "WARNING"
            ).strip()

            message = str(
                warning.get("message") or ""
            ).strip()

            title = (
                f"{path} ? {code} ??????"
            )

            if message:
                title += f": {message}"

            recommendations.append(
                {
                    "title": title,
                    "path": path,
                    "code": code,
                    "level": level,
                    "message": message,
                }
            )

    generic_recommendations: list[Any] = []

    for source, keys in (
        (
            planning,
            (
                "recommendations",
                "recommended_actions",
                "next_actions",
                "execution_order",
            ),
        ),
        (
            analysis,
            (
                "recommendations",
                "recommended_actions",
                "suggestions",
            ),
        ),
    ):
        found = False

        for key in keys:
            value = source.get(key)

            if isinstance(value, list):
                generic_recommendations = value
                found = True
                break

        if found:
            break

    recommendations.extend(
        generic_recommendations
    )

    return recommendations

def _extract_risks(
    analysis: dict[str, Any],
    planning: dict[str, Any],
) -> list[Any]:
    risks: list[Any] = []

    for source in (
        analysis,
        planning,
    ):
        for key in (
            "risks",
            "remaining_risks",
            "risk_items",
        ):
            value = source.get(key)

            if isinstance(value, list):
                risks.extend(value)

        single_risk = source.get("risk")

        if isinstance(single_risk, dict):
            risks.append(single_risk)

    return risks


def _build_human_summary(
    *,
    mission: dict[str, Any],
    analysis: dict[str, Any],
    planning: dict[str, Any],
    recommendations: list[Any],
    risks: list[Any],
) -> str:
    candidates = _safe_list(
        analysis.get("candidates")
    )
    selected_files = _safe_list(
        planning.get("selected_files")
    )
    workstreams = _safe_list(
        planning.get("workstreams")
    )

    lines = [
        f"Mission「{mission['title']}」の分析を完了しました。",
        "",
        f"目的: {mission['objective']}",
        f"Project: {mission['project_name']}",
        (
            "分析候補数: "
            f"{len(candidates)}"
        ),
        (
            "重点確認ファイル数: "
            f"{len(selected_files)}"
        ),
        (
            "計画領域数: "
            f"{len(workstreams)}"
        ),
        (
            "推奨対応数: "
            f"{len(recommendations)}"
        ),
        (
            "確認済みリスク数: "
            f"{len(risks)}"
        ),
        "",
        "コード変更: なし",
        "Verification: 対象外",
        "Commit: 対象外",
    ]

    if recommendations:
        lines.extend(
            [
                "",
                "推奨対応:",
            ]
        )

        for index, item in enumerate(
            recommendations,
            start=1,
        ):
            if isinstance(item, dict):
                title = (
                    item.get("title")
                    or item.get("name")
                    or item.get("action")
                    or item.get("description")
                    or str(item)
                )
            else:
                title = str(item)

            lines.append(
                f"{index}. {title}"
            )

    if risks:
        lines.extend(
            [
                "",
                "残存・確認対象リスク:",
            ]
        )

        for index, item in enumerate(
            risks,
            start=1,
        ):
            if isinstance(item, dict):
                description = (
                    item.get("reason")
                    or item.get("description")
                    or item.get("label")
                    or item.get("level")
                    or str(item)
                )
            else:
                description = str(item)

            lines.append(
                f"{index}. {description}"
            )

    return "\n".join(lines)


def run_mission_analysis_reporting(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    if mission.get("mission_type") != "ANALYSIS":
        raise MissionAnalysisReportingError(
            "ANALYSIS Mission以外では実行できません。"
        )

    requirements_task = _task_by_type(
        mission,
        "REQUIREMENTS",
    )
    analysis_task = _task_by_type(
        mission,
        "ANALYSIS",
    )
    planning_task = _task_by_type(
        mission,
        "PLANNING",
    )
    reporting_task = _task_by_type(
        mission,
        "ANALYSIS_REPORTING",
    )

    for task, label in (
        (
            requirements_task,
            "REQUIREMENTS",
        ),
        (
            analysis_task,
            "ANALYSIS",
        ),
        (
            planning_task,
            "PLANNING",
        ),
    ):
        if task["status"] != "COMPLETED":
            raise MissionAnalysisReportingError(
                f"{label} Taskが完了していません。"
            )

    if reporting_task["status"] not in {
        "PENDING",
        "READY",
        "RUNNING",
    }:
        raise MissionAnalysisReportingError(
            "ANALYSIS_REPORTING Taskは"
            "実行可能状態ではありません。"
        )

    requirements_raw = requirements_task.get("result")

    requirements = {
        "summary": (
            requirements_raw
            if isinstance(requirements_raw, str)
            else ""
        ),
    }

    analysis = _load_result(
        analysis_task,
        label="ANALYSIS",
    )
    planning = _load_result(
        planning_task,
        label="PLANNING",
    )

    recommendations = _extract_recommendations(
        analysis,
        planning,
    )
    risks = _extract_risks(
        analysis,
        planning,
    )

    report = {
        "analysis_reporting_version": (
            ANALYSIS_REPORTING_VERSION
        ),
        "mission": {
            "id": mission["id"],
            "mission_type": mission["mission_type"],
            "title": mission["title"],
            "objective": mission["objective"],
            "success_criteria": (
                mission["success_criteria"]
            ),
            "project_id": mission["project_id"],
            "project_name": (
                mission["project_name"]
            ),
        },
        "requirements": requirements,
        "analysis": analysis,
        "planning": planning,
        "recommendations": recommendations,
        "risks": risks,
        "completion": {
            "success": True,
            "code_changed": False,
            "verification_required": False,
            "commit_required": False,
            "rollback_required": False,
        },
    }

    report["summary"] = _build_human_summary(
        mission=mission,
        analysis=analysis,
        planning=planning,
        recommendations=recommendations,
        risks=risks,
    )

    result_text = json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionAnalysisReportingError(
            "分析報告結果が保存上限を超えました。"
        )

    if reporting_task["status"] != "RUNNING":
        update_mission_task(
            mission_id=mission_id,
            task_id=reporting_task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

    updated_mission = update_mission_task(
        mission_id=mission_id,
        task_id=reporting_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_ANALYSIS_REPORTING_COMPLETED"
        ),
        message=(
            "Requirements・Analysis・Planning結果を"
            "統合し、分析Missionの最終報告を作成しました。"
        ),
        metadata={
            "analysis_reporting_version": (
                ANALYSIS_REPORTING_VERSION
            ),
            "success": True,
            "recommendation_count": len(
                recommendations
            ),
            "risk_count": len(risks),
            "code_changed": False,
            "verification_required": False,
            "commit_required": False,
        },
    )

    return {
        "mission": updated_mission,
        "report": report,
    }


def run_mission_analysis_reporting_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_mission_analysis_reporting(
            mission_id
        )
    except MissionAnalysisReportingError:
        raise
    except MissionError as error:
        raise MissionAnalysisReportingError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionAnalysisReportingError(
            "Analysis Reporting Runnerで"
            "予期しないエラーが発生しました: "
            f"{error}"
        ) from error
