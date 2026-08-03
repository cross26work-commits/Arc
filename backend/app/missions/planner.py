from __future__ import annotations

import re
from typing import Any


VALID_MISSION_TYPES = {
    "IMPLEMENTATION",
    "ANALYSIS",
}


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def build_mission_title(objective: str) -> str:
    compact = _compact_text(objective)

    if len(compact) <= 42:
        return compact

    return compact[:41].rstrip() + "…"


def _build_implementation_tasks() -> list[dict[str, Any]]:
    return [
        {
            "position": 1,
            "title": "目的と成功条件を整理",
            "description": (
                "マスターの指示を開発要件へ変換し、"
                "完成と判断する条件を明確にする。"
            ),
            "task_type": "REQUIREMENTS",
            "status": "READY",
        },
        {
            "position": 2,
            "title": "対象コードを調査",
            "description": (
                "コード検索・静的解析・依存関係解析を使い、"
                "変更候補と影響範囲を特定する。"
            ),
            "task_type": "ANALYSIS",
            "status": "PENDING",
        },
        {
            "position": 3,
            "title": "実装計画を作成",
            "description": (
                "変更対象、作業順、リスク、検証方法を"
                "実行可能な計画へ分解する。"
            ),
            "task_type": "PLANNING",
            "status": "PENDING",
        },
        {
            "position": 4,
            "title": "実行承認を取得",
            "description": (
                "ファイル変更前に、変更内容と影響範囲を"
                "マスターへ提示して承認を待つ。"
            ),
            "task_type": "APPROVAL",
            "status": "PENDING",
        },
        {
            "position": 5,
            "title": "実装を実行",
            "description": (
                "承認済み計画に従って小さな単位で変更し、"
                "差分と実行ログを保存する。"
            ),
            "task_type": "IMPLEMENTATION",
            "status": "PENDING",
        },
        {
            "position": 6,
            "title": "検証と再試行",
            "description": (
                "構文確認・Build・テストを実行し、"
                "失敗時はログを解析して修正・再検証する。"
            ),
            "task_type": "VERIFICATION",
            "status": "PENDING",
        },
        {
            "position": 7,
            "title": "完成判定と報告",
            "description": (
                "成功条件を満たしたことを確認し、"
                "変更・テスト・残存リスクを報告する。"
            ),
            "task_type": "REPORTING",
            "status": "PENDING",
        },
    ]


def _build_analysis_tasks() -> list[dict[str, Any]]:
    return [
        {
            "position": 1,
            "title": "目的と成功条件を整理",
            "description": (
                "マスターの指示を分析要件へ変換し、"
                "完成と判断する条件を明確にする。"
            ),
            "task_type": "REQUIREMENTS",
            "status": "READY",
        },
        {
            "position": 2,
            "title": "対象コードを調査",
            "description": (
                "コード検索・静的解析・依存関係解析を使い、"
                "現状、課題、影響範囲を特定する。"
            ),
            "task_type": "ANALYSIS",
            "status": "PENDING",
        },
        {
            "position": 3,
            "title": "分析結果を整理",
            "description": (
                "調査結果を構造化し、課題、優先順位、"
                "推奨対応を整理する。"
            ),
            "task_type": "PLANNING",
            "status": "PENDING",
        },
        {
            "position": 4,
            "title": "分析結果を報告",
            "description": (
                "現状、主要課題、影響範囲、"
                "推奨対応と残存リスクを報告する。"
            ),
            "task_type": "ANALYSIS_REPORTING",
            "status": "PENDING",
        },
    ]


def generate_initial_plan(
    *,
    objective: str,
    project_name: str,
    mission_type: str = "IMPLEMENTATION",
) -> dict[str, Any]:
    if mission_type not in VALID_MISSION_TYPES:
        raise ValueError(
            f"Unsupported mission_type: {mission_type}"
        )

    compact_objective = _compact_text(objective)

    if mission_type == "ANALYSIS":
        success_criteria = (
            f"{project_name}に対して「{compact_objective}」を分析し、"
            "現状、課題、影響範囲、推奨対応を整理して"
            "報告できること。"
        )
        tasks = _build_analysis_tasks()
    else:
        success_criteria = (
            f"{project_name}に対して「{compact_objective}」を実現し、"
            "必要な構文確認・Build・テストを通過させ、"
            "変更内容と検証結果を報告できること。"
        )
        tasks = _build_implementation_tasks()

    return {
        "title": build_mission_title(compact_objective),
        "success_criteria": success_criteria,
        "next_action": "目的と成功条件を整理する",
        "tasks": tasks,
    }
