import pytest

from app.missions.requirement_analyzer import (
    REQUIREMENT_ANALYZER_VERSION,
    RequirementAnalyzerError,
    analyze_requirement,
    analyze_requirement_safe,
)


def test_analyze_requirement_builds_contract() -> None:
    result = analyze_requirement(
        objective=(
            "Profit Radarの返信機能を改善する"
        ),
    )

    assert result.objective == (
        "Profit Radarの返信機能を改善する"
    )
    assert result.implementation_possible is True
    assert "返信機能" in result.in_scope
    assert result.requirements
    assert result.success_criteria
    assert result.constraints


def test_analyze_requirement_detects_ambiguity() -> None:
    result = analyze_requirement(
        objective=(
            "返信画面を使いやすく改善する"
        ),
    )

    assert len(result.ambiguities) >= 2
    assert result.missing_information


def test_analyze_requirement_detects_security_risk() -> None:
    result = analyze_requirement(
        objective=(
            "ログイン認証APIを変更する"
        ),
    )

    categories = {
        risk.category
        for risk in result.risks
    }

    assert "SECURITY" in categories
    assert "COMPATIBILITY" in categories


def test_analyze_requirement_uses_success_criteria() -> None:
    result = analyze_requirement(
        objective="顧客管理機能を追加する",
        success_criteria=(
            "顧客登録APIが正常に動作すること"
        ),
    )

    assert (
        "顧客登録APIが正常に動作すること"
        in result.success_criteria
    )


def test_analyze_requirement_deduplicates_scope() -> None:
    result = analyze_requirement(
        objective=(
            "APIとapiの互換性を確認する"
        ),
    )

    assert result.in_scope.count("API") == 1


@pytest.mark.parametrize(
    "objective",
    [
        "",
        " ",
        "ab",
    ],
)
def test_analyze_requirement_rejects_short_objective(
    objective: str,
) -> None:
    with pytest.raises(
        RequirementAnalyzerError
    ):
        analyze_requirement(
            objective=objective
        )


def test_analyze_requirement_safe_returns_success() -> None:
    response = analyze_requirement_safe(
        objective=(
            "利益分析画面を改善する"
        ),
    )

    assert response["ok"] is True
    assert response["analyzer_version"] == (
        REQUIREMENT_ANALYZER_VERSION
    )
    assert response["result"] is not None
    assert response["error"] is None


def test_analyze_requirement_safe_returns_error() -> None:
    response = analyze_requirement_safe(
        objective="",
    )

    assert response["ok"] is False
    assert response["result"] is None
    assert response["error"]["type"] == (
        "RequirementAnalyzerError"
    )


def test_contract_is_json_serializable() -> None:
    result = analyze_requirement(
        objective=(
            "メール送信処理を自動化する"
        ),
    )

    dumped = result.model_dump(
        mode="json"
    )

    assert dumped["objective"] == (
        "メール送信処理を自動化する"
    )
    assert isinstance(
        dumped["risks"],
        list,
    )



def test_analyze_requirement_excludes_negated_database_scope() -> None:
    result = analyze_requirement(
        objective=(
            "Resolve the authentication issue without changing "
            "the database. Do not make database changes or "
            "schema changes."
        ),
    )

    assert "Database" not in result.in_scope
    assert not any(
        "Database" in requirement
        for requirement in result.requirements
    )


def test_analyze_requirement_keeps_positive_database_scope() -> None:
    result = analyze_requirement(
        objective=(
            "Update the database schema for customer records."
        ),
    )

    assert "Database" in result.in_scope
    assert any(
        "Database" in requirement
        for requirement in result.requirements
    )
