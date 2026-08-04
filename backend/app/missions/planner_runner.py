from __future__ import annotations

import os

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.missions.models import MissionTaskUpdate
from app.missions.requirement_analyzer import (
    analyze_requirement,
)
from app.missions.service import (
    add_mission_log,
    get_mission,
    update_mission_task,
)


class MissionPlannerError(Exception):
    """Mission計画生成に失敗した場合の例外。"""


def _classify_path(path: str) -> str:
    lowered = path.lower()

    if path.endswith(
        (
            "test.py",
            "_test.py",
            ".test.ts",
            ".test.tsx",
            ".spec.ts",
            ".spec.tsx",
        )
    ) or "/tests/" in lowered:
        return "TEST"

    if (
        "/migrations/" in lowered
        or "/schemas/" in lowered
        or "/models/" in lowered
        or "database" in lowered
    ):
        return "DATA"

    if path.startswith("frontend/"):
        return "FRONTEND"

    if (
        "/api/" in lowered
        or "/routers/" in lowered
        or "/services/" in lowered
        or "/core/" in lowered
        or path.endswith("main.py")
    ):
        return "BACKEND"

    return "OTHER"


def _risk_weight(level: str | None) -> int:
    return {
        "high": 3,
        "medium": 2,
        "low": 1,
    }.get(level or "", 0)


def _select_files(
    candidates: list[dict[str, Any]],
    *,
    max_files: int = 10,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    for item in candidates:
        path = item.get("path")

        if not path:
            continue

        dependency = item.get("dependency") or {}
        risk = dependency.get("risk") or {}

        selected.append(
            {
                "path": path,
                "role": item.get("role"),
                "language": item.get("language"),
                "score": item.get("score", 0),
                "category": _classify_path(path),
                "risk_level": risk.get("level", "unknown"),
                "risk_score": risk.get("score", 0),
                "direct_dependencies": dependency.get(
                    "direct_dependencies",
                    [],
                ),
                "direct_dependents": dependency.get(
                    "direct_dependents",
                    [],
                ),
                "affected_count": dependency.get(
                    "affected_count",
                    0,
                ),
                "reasons": item.get("reasons", []),
            }
        )

    selected.sort(
        key=lambda item: (
            -item["score"],
            -_risk_weight(item["risk_level"]),
            item["path"],
        )
    )

    return selected[:max_files]


def _build_workstreams(
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in files:
        grouped[item["category"]].append(item)

    order = [
        "BACKEND",
        "DATA",
        "FRONTEND",
        "TEST",
        "OTHER",
    ]

    labels = {
        "BACKEND": "Backend・API",
        "DATA": "DB・データモデル",
        "FRONTEND": "Frontend・画面",
        "TEST": "テスト",
        "OTHER": "その他",
    }

    workstreams: list[dict[str, Any]] = []
    position = 1

    for category in order:
        category_files = grouped.get(category, [])

        if not category_files:
            continue

        workstreams.append(
            {
                "position": position,
                "category": category,
                "title": labels[category],
                "file_count": len(category_files),
                "files": [
                    item["path"]
                    for item in category_files
                ],
                "purpose": (
                    f"{labels[category]}に関係する候補を確認し、"
                    "Mission目的に必要な変更だけを実施する。"
                ),
            }
        )

        position += 1

    return workstreams


def _build_verification_commands(
    files: list[dict[str, Any]],
) -> list[dict[str, str]]:
    categories = {
        item["category"]
        for item in files
    }

    commands: list[dict[str, str]] = []

    if os.name == "nt":
        python_command = r"venv\Scripts\python.exe"
    else:
        python_command = "venv/bin/python"

    if {
        "BACKEND",
        "DATA",
    } & categories:
        commands.append(
            {
                "name": "Python構文確認",
                "command": (
                    "cd backend && "
                    f"{python_command} -m compileall -q app"
                ),
            }
        )

    if "FRONTEND" in categories:
        commands.append(
            {
                "name": "Frontend Build",
                "command": "npm run build",
            }
        )

    if "TEST" in categories:
        commands.append(
            {
                "name": "自動テスト",
                "command": (
                    "cd backend && "
                    f"{python_command} -m pytest"
                ),
            }
        )

    commands.append(
        {
            "name": "Git差分確認",
            "command": "git diff --check && git status",
        }
    )

    return commands


def _calculate_plan_risk(
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    high = sum(
        1
        for item in files
        if item["risk_level"] == "high"
    )

    medium = sum(
        1
        for item in files
        if item["risk_level"] == "medium"
    )

    affected = sum(
        int(item.get("affected_count", 0))
        for item in files
    )

    score = min(
        high * 25
        + medium * 12
        + min(affected, 30),
        100,
    )

    if score >= 70:
        level = "high"
        label = "高"
    elif score >= 35:
        level = "medium"
        label = "中"
    else:
        level = "low"
        label = "低"

    return {
        "level": level,
        "label": label,
        "score": score,
        "high_risk_file_count": high,
        "medium_risk_file_count": medium,
        "affected_reference_count": affected,
        "reason": (
            f"高リスク候補{high}件、"
            f"中リスク候補{medium}件、"
            f"影響参照合計{affected}件"
        ),
    }


def _estimate_effort(
    files: list[dict[str, Any]],
    workstreams: list[dict[str, Any]],
) -> dict[str, Any]:
    file_count = len(files)
    stream_count = len(workstreams)

    points = file_count + stream_count * 2

    if points <= 6:
        level = "small"
        label = "小"
        estimated_minutes = 30
    elif points <= 14:
        level = "medium"
        label = "中"
        estimated_minutes = 90
    else:
        level = "large"
        label = "大"
        estimated_minutes = 180

    return {
        "level": level,
        "label": label,
        "estimated_minutes": estimated_minutes,
        "basis": (
            f"候補ファイル{file_count}件、"
            f"作業領域{stream_count}件"
        ),
        "note": (
            "現時点のルールベース概算。"
            "詳細設計後に再評価する。"
        ),
    }


def _build_approval_summary(
    *,
    mission: dict[str, Any],
    files: list[dict[str, Any]],
    workstreams: list[dict[str, Any]],
    risk: dict[str, Any],
    effort: dict[str, Any],
) -> str:
    top_files = [
        item["path"]
        for item in files[:5]
    ]

    return (
        f"Mission「{mission['title']}」について、"
        f"{len(files)}件の変更候補と"
        f"{len(workstreams)}領域の作業計画を作成しました。"
        f"総合リスクは{risk['label']}、"
        f"概算規模は{effort['label']}です。"
        f"優先確認対象: {', '.join(top_files)}"
    )


def _recover_planning_failure(
    *,
    mission_id: int,
    error: Exception,
) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        task = connection.execute(
            """
            SELECT id
            FROM mission_tasks
            WHERE mission_id = ?
              AND task_type = 'PLANNING'
            LIMIT 1
            """,
            (mission_id,),
        ).fetchone()

        if task is None:
            return

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'READY',
                result = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    {
                        "status": "FAILED_RETRYABLE",
                        "error_type": error.__class__.__name__,
                        "error": str(error),
                    },
                    ensure_ascii=False,
                ),
                now,
                task["id"],
            ),
        )

        connection.execute(
            """
            UPDATE missions
            SET
                status = 'PLANNED',
                progress = 29,
                next_action =
                    '前回の計画生成エラーを確認し、再試行する',
                error_count = error_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                mission_id,
            ),
        )

        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="ERROR",
        event_type="MISSION_PLANNING_FAILED",
        message=(
            "Mission計画生成に失敗したため、"
            "PLANNING TaskをREADYへ復旧しました。"
        ),
        metadata={
            "error_type": error.__class__.__name__,
            "error": str(error),
            "retryable": True,
        },
    )


def _run_mission_planner_impl(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    analysis_task = next(
        (
            task
            for task in mission["tasks"]
            if task["task_type"] == "ANALYSIS"
        ),
        None,
    )

    planning_task = next(
        (
            task
            for task in mission["tasks"]
            if task["task_type"] == "PLANNING"
        ),
        None,
    )

    if analysis_task is None or planning_task is None:
        raise MissionPlannerError(
            "ANALYSISまたはPLANNING Taskがありません。"
        )

    if analysis_task["status"] != "COMPLETED":
        raise MissionPlannerError(
            "ANALYSIS Taskが完了していません。"
        )

    if not analysis_task["result"]:
        raise MissionPlannerError(
            "ANALYSIS結果が保存されていません。"
        )

    if planning_task["status"] not in {
        "READY",
        "RUNNING",
    }:
        raise MissionPlannerError(
            "PLANNING Taskは実行可能状態ではありません。"
        )

    if planning_task["status"] == "READY":
        mission = update_mission_task(
            mission_id=mission_id,
            task_id=planning_task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

        planning_task = next(
            task
            for task in mission["tasks"]
            if task["task_type"] == "PLANNING"
        )

    try:
        analysis = json.loads(
            analysis_task["result"]
        )
    except json.JSONDecodeError as error:
        raise MissionPlannerError(
            "ANALYSIS結果のJSONを読み取れません。"
        ) from error

    candidates = analysis.get("candidates", [])

    if not candidates:
        raise MissionPlannerError(
            "計画へ使用できる候補ファイルがありません。"
        )

    selected_files = _select_files(candidates)
    workstreams = _build_workstreams(selected_files)
    verification = _build_verification_commands(
        selected_files
    )
    risk = _calculate_plan_risk(selected_files)
    effort = _estimate_effort(
        selected_files,
        workstreams,
    )

    requirement = analyze_requirement(
        objective=mission["objective"],
        success_criteria=mission["success_criteria"],
    )

    requirement_payload = requirement.model_dump(
        mode="json"
    )

    plan = {
        "plan_version": "mission-planner-v0.2",
        "mission_id": mission_id,
        "project_id": mission["project_id"],
        "project_name": mission["project_name"],
        "objective": mission["objective"],
        "success_criteria": mission["success_criteria"],
        "requirement_contract_version": (
            requirement.contract_version
        ),
        "requirement_contract": requirement_payload,
        "implementation_possible": (
            requirement.implementation_possible
        ),
        "ambiguity_count": len(
            requirement.ambiguities
        ),
        "missing_information_count": len(
            requirement.missing_information
        ),
        "requirement_risk_count": len(
            requirement.risks
        ),
        "analysis_version": analysis.get(
            "analysis_version"
        ),
        "selected_file_count": len(selected_files),
        "selected_files": selected_files,
        "workstreams": workstreams,
        "execution_order": [
            stream["title"]
            for stream in workstreams
        ],
        "verification_commands": verification,
        "risk": risk,
        "effort": effort,
    }

    plan["approval_summary"] = _build_approval_summary(
        mission=mission,
        files=selected_files,
        workstreams=workstreams,
        risk=risk,
        effort=effort,
    )

    result_text = json.dumps(
        plan,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionPlannerError(
            "生成した実装計画が保存上限を超えました。"
        )

    target_path = (
        selected_files[0]["path"]
        if selected_files
        else None
    )

    mission = update_mission_task(
        mission_id=mission_id,
        task_id=planning_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
            target_path=target_path,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="MISSION_PLANNING_COMPLETED",
        message=(
            f"候補ファイル{len(selected_files)}件、"
            f"作業領域{len(workstreams)}件の"
            "実装計画を作成しました。"
        ),
        metadata={
            "selected_file_count": len(selected_files),
            "workstream_count": len(workstreams),
            "risk": risk,
            "effort": effort,
            "requirement_contract_version": (
                requirement.contract_version
            ),
            "implementation_possible": (
                requirement.implementation_possible
            ),
            "ambiguity_count": len(
                requirement.ambiguities
            ),
            "missing_information_count": len(
                requirement.missing_information
            ),
            "requirement_risk_count": len(
                requirement.risks
            ),
        },
    )

    return {
        "mission": mission,
        "plan": plan,
    }


def run_mission_planner(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return _run_mission_planner_impl(mission_id)

    except Exception as error:
        _recover_planning_failure(
            mission_id=mission_id,
            error=error,
        )

        if isinstance(error, MissionPlannerError):
            raise

        raise MissionPlannerError(
            "Mission計画生成に失敗しました。"
            "PLANNING Taskを再試行可能な状態へ復旧しました。"
            f" 原因: {error}"
        ) from error
