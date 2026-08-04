from __future__ import annotations

import re
from typing import Iterable

from app.missions.models import (
    RequirementAnalyzerResult,
    RequirementRisk,
)


REQUIREMENT_ANALYZER_VERSION = (
    "requirement-analyzer-v0.1"
)


class RequirementAnalyzerError(Exception):
    """要求分析に失敗した場合の例外。"""


_AMBIGUOUS_TERMS = {
    "改善": "改善内容と評価基準が明確ではありません。",
    "使いやすく": "使いやすさを判断する基準が明確ではありません。",
    "最適化": "最適化対象と評価指標が明確ではありません。",
    "高速化": "目標応答時間または性能基準が明確ではありません。",
    "強化": "強化対象と完了条件が明確ではありません。",
    "いい感じ": "期待する状態が具体的ではありません。",
    "きれい": "見た目または構造の評価基準が明確ではありません。",
    "便利": "必要な利用場面と操作要件が明確ではありません。",
    "自動化": "自動化する範囲と人の承認条件が明確ではありません。",
}


_SCOPE_HINTS = {
    "返信": "返信機能",
    "メール": "メール連携",
    "gmail": "Gmail連携",
    "ログイン": "認証・ログイン",
    "登録": "ユーザー登録",
    "顧客": "顧客管理",
    "案件": "案件管理",
    "dashboard": "ダッシュボード",
    "ダッシュボード": "ダッシュボード",
    "利益": "利益分析",
    "テスト": "テスト",
    "api": "API",
    "frontend": "Frontend",
    "フロントエンド": "Frontend",
    "backend": "Backend",
    "バックエンド": "Backend",
    "database": "Database",
    "db": "Database",
    "データベース": "Database",
}


_RISK_HINTS = {
    "削除": RequirementRisk(
        category="DATA_LOSS",
        level="HIGH",
        description=(
            "既存データまたはファイルを削除する可能性があります。"
        ),
        mitigation=(
            "削除前のバックアップと明示承認を必須にします。"
        ),
    ),
    "上書き": RequirementRisk(
        category="DATA_LOSS",
        level="HIGH",
        description=(
            "既存データを意図せず上書きする可能性があります。"
        ),
        mitigation=(
            "変更前の保存と差分確認を実施します。"
        ),
    ),
    "認証": RequirementRisk(
        category="SECURITY",
        level="HIGH",
        description=(
            "認証処理の変更によりアクセス制御へ影響する可能性があります。"
        ),
        mitigation=(
            "認証テストと権限確認を追加します。"
        ),
    ),
    "ログイン": RequirementRisk(
        category="SECURITY",
        level="HIGH",
        description=(
            "ログイン処理の変更により認証障害が発生する可能性があります。"
        ),
        mitigation=(
            "既存ログイン回帰テストを必須にします。"
        ),
    ),
    "メール送信": RequirementRisk(
        category="EXTERNAL_ACTION",
        level="HIGH",
        description=(
            "実メールを誤送信する可能性があります。"
        ),
        mitigation=(
            "送信前承認とテスト送信環境を使用します。"
        ),
    ),
    "migration": RequirementRisk(
        category="DATABASE",
        level="HIGH",
        description=(
            "DB Migrationにより既存データへ影響する可能性があります。"
        ),
        mitigation=(
            "Migration前バックアップとRollback手順を用意します。"
        ),
    ),
    "データベース": RequirementRisk(
        category="DATABASE",
        level="MEDIUM",
        description=(
            "データベース構造または保存処理へ影響する可能性があります。"
        ),
        mitigation=(
            "既存データ互換性とMigration要否を確認します。"
        ),
    ),
    "api": RequirementRisk(
        category="COMPATIBILITY",
        level="MEDIUM",
        description=(
            "API変更により既存クライアントとの互換性が失われる可能性があります。"
        ),
        mitigation=(
            "既存Response形式を維持し、API回帰テストを実施します。"
        ),
    ),
}


def _compact_text(value: str) -> str:
    if not isinstance(value, str):
        raise RequirementAnalyzerError(
            "要求は文字列で指定してください。"
        )

    compact = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    if len(compact) < 3:
        raise RequirementAnalyzerError(
            "要求は3文字以上で指定してください。"
        )

    return compact


def _deduplicate(
    values: Iterable[str],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = value.strip()

        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return result


def _extract_in_scope(
    objective: str,
) -> list[str]:
    lowered = objective.lower()

    scopes = [
        label
        for keyword, label in _SCOPE_HINTS.items()
        if keyword in lowered
    ]

    if not scopes:
        scopes.append(
            "要求に直接関係する最小変更範囲"
        )

    return _deduplicate(scopes)


def _extract_ambiguities(
    objective: str,
) -> list[str]:
    return _deduplicate(
        message
        for keyword, message
        in _AMBIGUOUS_TERMS.items()
        if keyword in objective
    )


def _extract_risks(
    objective: str,
) -> list[RequirementRisk]:
    lowered = objective.lower()
    result: list[RequirementRisk] = []
    seen_categories: set[str] = set()

    for keyword, risk in _RISK_HINTS.items():
        if keyword not in lowered:
            continue

        key = (
            f"{risk.category}:"
            f"{risk.description}"
        )

        if key in seen_categories:
            continue

        seen_categories.add(key)
        result.append(
            risk.model_copy(deep=True)
        )

    return result


def _build_requirements(
    objective: str,
    in_scope: list[str],
) -> list[str]:
    requirements = [
        f"要求「{objective}」を実現すること",
        "既存機能との互換性を可能な限り維持すること",
        "変更内容を検証可能な状態にすること",
    ]

    requirements.extend(
        f"{scope}に必要な変更だけを実施すること"
        for scope in in_scope
    )

    return _deduplicate(requirements)


def _build_success_criteria(
    *,
    objective: str,
    provided_success_criteria: str | None,
) -> list[str]:
    criteria: list[str] = []

    if (
        provided_success_criteria
        and provided_success_criteria.strip()
    ):
        criteria.append(
            provided_success_criteria.strip()
        )

    criteria.extend(
        [
            f"要求「{objective}」が実現されていること",
            "Python構文確認または対象Buildが成功すること",
            "関連テストが成功すること",
            "既存テストに回帰がないこと",
            "変更内容と残存リスクが報告されること",
        ]
    )

    return _deduplicate(criteria)


def analyze_requirement(
    *,
    objective: str,
    success_criteria: str | None = None,
) -> RequirementAnalyzerResult:
    normalized_objective = _compact_text(
        objective
    )

    in_scope = _extract_in_scope(
        normalized_objective
    )

    ambiguities = _extract_ambiguities(
        normalized_objective
    )

    risks = _extract_risks(
        normalized_objective
    )

    missing_information = [
        (
            "曖昧な要求について、具体的な完成状態または"
            "評価基準を確認する必要があります。"
        )
        for _ in ambiguities[:1]
    ]

    implementation_possible = not (
        len(normalized_objective) < 5
        or len(missing_information) >= 3
    )

    constraints = [
        "既存機能を不必要に変更しないこと",
        "変更対象をMission目的に必要な範囲へ限定すること",
        "検証条件を弱体化しないこと",
        "テスト削除によって成功扱いにしないこと",
    ]

    if risks:
        constraints.append(
            "高リスク変更はマスターの承認後に実行すること"
        )

    out_of_scope = [
        "要求に直接関係しない機能追加",
        "承認されていない大規模リファクタリング",
        "検証目的に不要な依存関係更新",
    ]

    summary_parts = [
        (
            "要求を構造化し、対象範囲、成功条件、"
            "制約およびリスクを抽出しました。"
        )
    ]

    if ambiguities:
        summary_parts.append(
            f"曖昧な表現を{len(ambiguities)}件検出しました。"
        )
    else:
        summary_parts.append(
            "重大な曖昧表現は検出されませんでした。"
        )

    if risks:
        summary_parts.append(
            f"事前確認が必要なリスクを{len(risks)}件検出しました。"
        )
    else:
        summary_parts.append(
            "明示的な高リスク要素は検出されませんでした。"
        )

    return RequirementAnalyzerResult(
        objective=normalized_objective,
        requirements=_build_requirements(
            normalized_objective,
            in_scope,
        ),
        success_criteria=_build_success_criteria(
            objective=normalized_objective,
            provided_success_criteria=(
                success_criteria
            ),
        ),
        in_scope=in_scope,
        out_of_scope=out_of_scope,
        constraints=_deduplicate(constraints),
        ambiguities=ambiguities,
        missing_information=(
            missing_information
        ),
        risks=risks,
        implementation_possible=(
            implementation_possible
        ),
        analysis_summary=" ".join(
            summary_parts
        ),
    )


def analyze_requirement_safe(
    *,
    objective: str,
    success_criteria: str | None = None,
) -> dict:
    try:
        result = analyze_requirement(
            objective=objective,
            success_criteria=success_criteria,
        )

        return {
            "ok": True,
            "analyzer_version":
                REQUIREMENT_ANALYZER_VERSION,
            "result": result.model_dump(),
            "error": None,
        }

    except Exception as error:
        return {
            "ok": False,
            "analyzer_version":
                REQUIREMENT_ANALYZER_VERSION,
            "result": None,
            "error": {
                "type":
                    type(error).__name__,
                "message":
                    str(error),
            },
        }
