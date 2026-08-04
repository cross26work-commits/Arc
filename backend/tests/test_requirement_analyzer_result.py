import json

import pytest
from pydantic import ValidationError

from app.missions.models import (
    RequirementAnalyzerResult,
    RequirementRisk,
)


def _valid_payload() -> dict:
    return {
        "objective": (
            "Profit Radarの返信機能を改善する"
        ),
        "requirements": [
            "返信文を自動生成できること",
            "既存の下書きを編集できること",
        ],
        "success_criteria": [
            "返信文生成テストが成功すること",
            "既存テストが失敗しないこと",
        ],
        "in_scope": [
            "返信文生成処理",
            "返信画面",
        ],
        "out_of_scope": [
            "Gmail認証処理",
        ],
        "constraints": [
            "既存APIとの互換性を維持する",
        ],
        "ambiguities": [
            "返信品質の評価基準が未定義",
        ],
        "missing_information": [
            "期待する返信文の例",
        ],
        "risks": [
            {
                "category": "DATA_LOSS",
                "level": "HIGH",
                "description": (
                    "既存下書きを上書きする可能性"
                ),
                "mitigation": (
                    "保存前に確認処理を追加する"
                ),
            },
        ],
        "implementation_possible": True,
        "analysis_summary": (
            "実装可能だが、返信品質の基準確認が必要。"
        ),
    }


def test_requirement_result_is_valid() -> None:
    result = RequirementAnalyzerResult(
        **_valid_payload()
    )

    assert result.contract_version == (
        "requirement-contract-v0.1"
    )
    assert result.implementation_possible is True
    assert len(result.requirements) == 2
    assert result.risks[0].level == "HIGH"


def test_requirement_result_is_json_serializable() -> None:
    result = RequirementAnalyzerResult(
        **_valid_payload()
    )

    encoded = json.dumps(
        result.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
    )

    decoded = json.loads(encoded)

    assert decoded["objective"] == (
        "Profit Radarの返信機能を改善する"
    )
    assert decoded["risks"][0]["category"] == (
        "DATA_LOSS"
    )


def test_requirement_result_defaults_lists() -> None:
    result = RequirementAnalyzerResult(
        objective="小規模機能を追加する",
        implementation_possible=False,
        analysis_summary=(
            "必要情報が不足しているため実装不可。"
        ),
    )

    assert result.requirements == []
    assert result.success_criteria == []
    assert result.in_scope == []
    assert result.out_of_scope == []
    assert result.constraints == []
    assert result.ambiguities == []
    assert result.missing_information == []
    assert result.risks == []


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("objective", ""),
        ("analysis_summary", ""),
    ],
)
def test_requirement_result_rejects_empty_text(
    field_name: str,
    value: str,
) -> None:
    payload = _valid_payload()
    payload[field_name] = value

    with pytest.raises(ValidationError):
        RequirementAnalyzerResult(**payload)


def test_requirement_risk_rejects_invalid_level() -> None:
    with pytest.raises(ValidationError):
        RequirementRisk(
            category="SECURITY",
            level="CRITICAL",
            description="不正なRisk Level",
        )


def test_requirement_result_rejects_too_many_items() -> None:
    payload = _valid_payload()
    payload["requirements"] = [
        f"requirement-{index}"
        for index in range(101)
    ]

    with pytest.raises(ValidationError):
        RequirementAnalyzerResult(**payload)
