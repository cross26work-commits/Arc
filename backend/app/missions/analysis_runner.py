from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.analyzer.service import (
    FileAnalysisError,
    analyze_project_file,
)
from app.database import get_connection
from app.dependencies.service import (
    DependencyGraphError,
    analyze_dependency_tree,
)
from app.missions.models import MissionTaskUpdate
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
    update_mission_task,
)


STOP_WORDS = {
    "profit",
    "radar",
    "現在地",
    "調査",
    "必要",
    "作業",
    "計画",
    "作成",
    "開始",
    "まで",
    "する",
    "して",
    "できる",
    "ため",
    "これ",
    "それ",
    "実装",
    "追加",
    "変更",
    "機能",
    "確認",
    "プロジェクト",
}

SEARCH_HINTS = {
    "ベータ": [
        "dashboard",
        "auth",
        "login",
        "register",
        "settings",
        "gmail",
        "reply",
        "results",
        "customer",
        "lead",
    ],
    "テスト": [
        "test",
        "pytest",
        "build",
        "lint",
        "health",
    ],
    "認証": [
        "auth",
        "login",
        "register",
        "session",
        "supabase",
    ],
    "メール": [
        "gmail",
        "reply",
        "email",
        "message",
    ],
    "利益": [
        "profit",
        "revenue",
        "dashboard",
        "results",
    ],
    "LINE": [
        "line",
        "integration",
        "message",
        "webhook",
    ],
}


class MissionAnalysisError(Exception):
    """Mission調査処理に失敗した場合の例外。"""


def _get_project(project_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, path
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()


def _tokenize_objective(objective: str) -> list[str]:
    values = re.findall(
        r"[A-Za-z][A-Za-z0-9_/-]{2,}|"
        r"[一-龥ぁ-んァ-ヶー]{2,}",
        objective,
    )

    tokens: list[str] = []

    for value in values:
        normalized = value.strip()

        if not normalized:
            continue

        if normalized.lower() in STOP_WORDS:
            continue

        if normalized in STOP_WORDS:
            continue

        tokens.append(normalized)

    for keyword, hints in SEARCH_HINTS.items():
        if keyword.lower() in objective.lower():
            tokens.extend(hints)

    return list(dict.fromkeys(tokens))


def _search_index(
    *,
    project_id: int,
    query: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    like_query = f"%{query}%"

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                project_files.relative_path AS path,
                code_symbols.line_number AS line_number,
                code_symbols.name AS symbol_name,
                code_symbols.symbol_type AS symbol_type
            FROM project_files
            LEFT JOIN code_symbols
                ON code_symbols.project_file_id = project_files.id
            WHERE project_files.project_id = ?
              AND (
                    project_files.relative_path LIKE ?
                 OR code_symbols.name LIKE ?
                 OR code_symbols.metadata LIKE ?
              )
            ORDER BY
                CASE
                    WHEN project_files.relative_path LIKE ?
                    THEN 0
                    ELSE 1
                END,
                project_files.relative_path ASC,
                code_symbols.line_number ASC
            LIMIT ?
            """,
            (
                project_id,
                like_query,
                like_query,
                like_query,
                like_query,
                limit,
            ),
        ).fetchall()

    return [
        {
            "path": row["path"],
            "line_number": row["line_number"],
            "symbol_name": row["symbol_name"],
            "symbol_type": row["symbol_type"],
            "query": query,
        }
        for row in rows
    ]


def _rank_candidate_files(
    search_results: list[dict[str, Any]],
    max_candidates: int = 12,
) -> list[dict[str, Any]]:
    scores: Counter[str] = Counter()
    reasons: dict[str, set[str]] = {}

    for result in search_results:
        path = result["path"]
        query = result["query"]

        scores[path] += 3
        reasons.setdefault(path, set()).add(
            f"検索語「{query}」に一致"
        )

        if result.get("symbol_name"):
            scores[path] += 2
            reasons[path].add(
                f"シンボル「{result['symbol_name']}」"
            )

        lowered = path.lower()

        if "/api/" in lowered or "/routers/" in lowered:
            scores[path] += 2
            reasons[path].add("API層")

        if "/services/" in lowered:
            scores[path] += 2
            reasons[path].add("Service層")

        if "/app/" in lowered and path.endswith("page.tsx"):
            scores[path] += 2
            reasons[path].add("画面ルート")

        if "test" in lowered:
            scores[path] += 1
            reasons[path].add("テスト関連")

    ranked = []

    for path, score in scores.most_common(max_candidates):
        ranked.append(
            {
                "path": path,
                "score": score,
                "reasons": sorted(reasons[path]),
            }
        )

    return ranked


def _analyze_candidates(
    *,
    project_path: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    analyzed: list[dict[str, Any]] = []

    for candidate in candidates:
        path = candidate["path"]

        try:
            analysis = analyze_project_file(
                project_path=project_path,
                relative_path=path,
            )
        except FileAnalysisError as error:
            analyzed.append(
                {
                    **candidate,
                    "analysis_error": str(error),
                }
            )
            continue

        try:
            dependency = analyze_dependency_tree(
                project_path=project_path,
                target_path=path,
                direction="both",
                max_depth=3,
                max_nodes=120,
            )
        except DependencyGraphError as error:
            dependency = {
                "dependency_error": str(error),
            }

        analyzed.append(
            {
                **candidate,
                "role": analysis["role"],
                "language": analysis["language"],
                "metrics": analysis["metrics"],
                "routes": analysis["routes"][:10],
                "api_calls": analysis["api_calls"][:10],
                "sdk_calls": analysis["sdk_calls"][:10],
                "warnings": analysis["warnings"][:10],
                "dependency": {
                    "direct_dependencies": dependency.get(
                        "direct_dependencies",
                        [],
                    )[:15],
                    "direct_dependents": dependency.get(
                        "direct_dependents",
                        [],
                    )[:15],
                    "affected_count": dependency.get(
                        "summary",
                        {},
                    ).get("affected_count", 0),
                    "risk": dependency.get("risk"),
                    "error": dependency.get(
                        "dependency_error"
                    ),
                },
            }
        )

    return analyzed


def _build_analysis_summary(
    *,
    objective: str,
    search_terms: list[str],
    analyzed: list[dict[str, Any]],
) -> dict[str, Any]:
    high_risk = [
        item
        for item in analyzed
        if item.get("dependency", {})
        .get("risk", {})
        .get("level") == "high"
    ]

    medium_risk = [
        item
        for item in analyzed
        if item.get("dependency", {})
        .get("risk", {})
        .get("level") == "medium"
    ]

    api_files = [
        item["path"]
        for item in analyzed
        if item.get("routes")
    ]

    frontend_files = [
        item["path"]
        for item in analyzed
        if item.get("language") in {
            "typescript-react",
            "typescript",
            "javascript-react",
            "javascript",
        }
    ]

    backend_files = [
        item["path"]
        for item in analyzed
        if item.get("language") == "python"
    ]

    return {
        "objective": objective,
        "search_terms": search_terms,
        "candidate_count": len(analyzed),
        "high_risk_count": len(high_risk),
        "medium_risk_count": len(medium_risk),
        "api_files": api_files,
        "frontend_files": frontend_files,
        "backend_files": backend_files,
        "candidates": analyzed,
    }


def _run_mission_analysis_impl(
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

    if analysis_task is None:
        raise MissionAnalysisError(
            "ANALYSIS Taskが見つかりません。"
        )

    if analysis_task["status"] not in {
        "READY",
        "RUNNING",
    }:
        raise MissionAnalysisError(
            "ANALYSIS Taskは実行可能状態ではありません。"
        )

    project = _get_project(mission["project_id"])

    if project is None:
        raise MissionAnalysisError(
            "対象プロジェクトが見つかりません。"
        )

    if analysis_task["status"] == "READY":
        mission = update_mission_task(
            mission_id=mission_id,
            task_id=analysis_task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

        analysis_task = next(
            task
            for task in mission["tasks"]
            if task["task_type"] == "ANALYSIS"
        )

    search_terms = _tokenize_objective(
        mission["objective"]
    )

    if not search_terms:
        search_terms = [
            "dashboard",
            "auth",
            "settings",
            "results",
        ]

    search_terms = search_terms[:12]

    search_results: list[dict[str, Any]] = []

    for term in search_terms:
        search_results.extend(
            _search_index(
                project_id=mission["project_id"],
                query=term,
                limit=25,
            )
        )

    candidates = _rank_candidate_files(
        search_results,
        max_candidates=12,
    )

    if not candidates:
        raise MissionAnalysisError(
            "Mission目的に関連するコード候補を取得できませんでした。"
        )

    analyzed = _analyze_candidates(
        project_path=project["path"],
        candidates=candidates,
    )

    summary = _build_analysis_summary(
        objective=mission["objective"],
        search_terms=search_terms,
        analyzed=analyzed,
    )

    result_text = json.dumps(
        summary,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        compact_summary = {
            "objective": summary["objective"],
            "search_terms": summary["search_terms"],
            "candidate_count": summary["candidate_count"],
            "high_risk_count": summary["high_risk_count"],
            "medium_risk_count": summary["medium_risk_count"],
            "api_files": summary["api_files"],
            "frontend_files": summary["frontend_files"],
            "backend_files": summary["backend_files"],
            "candidates": [
                {
                    "path": item["path"],
                    "score": item["score"],
                    "reasons": item["reasons"],
                    "role": item.get("role"),
                    "language": item.get("language"),
                    "metrics": item.get("metrics"),
                    "dependency": item.get("dependency"),
                }
                for item in summary["candidates"]
            ],
            "result_compacted": True,
        }

        result_text = json.dumps(
            compact_summary,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    target_path = (
        candidates[0]["path"]
        if candidates
        else None
    )

    mission = update_mission_task(
        mission_id=mission_id,
        task_id=analysis_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
            target_path=target_path,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="MISSION_ANALYSIS_COMPLETED",
        message=(
            f"コード候補{len(analyzed)}件を解析し、"
            "Mission調査を完了しました。"
        ),
        metadata={
            "search_terms": search_terms,
            "candidate_count": len(analyzed),
            "top_candidate": target_path,
        },
    )

    return {
        "mission": mission,
        "analysis": summary,
    }


def _recover_analysis_failure(
    *,
    mission_id: int,
    error: Exception,
) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    error_message = (
        f"{error.__class__.__name__}: {str(error)}"
    )

    with get_connection() as connection:
        task = connection.execute(
            """
            SELECT id, status
            FROM mission_tasks
            WHERE mission_id = ?
              AND task_type = 'ANALYSIS'
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
                target_path = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    {
                        "status": "FAILED_RETRYABLE",
                        "error": error_message,
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
                progress = 14,
                next_action =
                    '前回の解析失敗を確認し、対象コードの調査を再試行する',
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
        event_type="MISSION_ANALYSIS_FAILED",
        message=(
            "Missionコード解析に失敗したため、"
            "ANALYSIS TaskをREADYへ自動復旧しました。"
        ),
        metadata={
            "error_type": error.__class__.__name__,
            "error": str(error),
            "retryable": True,
        },
    )


def run_mission_analysis(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return _run_mission_analysis_impl(mission_id)

    except Exception as error:
        _recover_analysis_failure(
            mission_id=mission_id,
            error=error,
        )

        raise MissionAnalysisError(
            "Mission解析に失敗しました。"
            "Taskを再試行可能な状態へ復旧しました。"
            f" 原因: {error}"
        ) from error

