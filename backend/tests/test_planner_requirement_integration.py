from app.missions.requirement_analyzer import (
    analyze_requirement,
)


def _build_plan_requirement_fields(
    *,
    objective: str,
    success_criteria: str,
) -> dict:
    requirement = analyze_requirement(
        objective=objective,
        success_criteria=success_criteria,
    )

    return {
        "requirement_contract_version": (
            requirement.contract_version
        ),
        "requirement_contract": (
            requirement.model_dump(
                mode="json"
            )
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
    }


def test_planner_requirement_fields_are_built() -> None:
    fields = _build_plan_requirement_fields(
        objective=(
            "Profit Radarの返信画面を改善する"
        ),
        success_criteria=(
            "返信画面が正常に動作すること"
        ),
    )

    assert fields[
        "requirement_contract_version"
    ] == "requirement-contract-v0.1"

    assert fields[
        "implementation_possible"
    ] is True

    assert fields["ambiguity_count"] >= 1

    contract = fields[
        "requirement_contract"
    ]

    assert contract["objective"] == (
        "Profit Radarの返信画面を改善する"
    )

    assert (
        "返信画面が正常に動作すること"
        in contract["success_criteria"]
    )


def test_planner_requirement_fields_include_risk() -> None:
    fields = _build_plan_requirement_fields(
        objective=(
            "ログイン認証APIを変更する"
        ),
        success_criteria=(
            "ログインテストが成功すること"
        ),
    )

    assert fields["requirement_risk_count"] >= 2

    categories = {
        risk["category"]
        for risk in fields[
            "requirement_contract"
        ]["risks"]
    }

    assert "SECURITY" in categories
    assert "COMPATIBILITY" in categories


def test_planner_requirement_contract_is_json_ready() -> None:
    fields = _build_plan_requirement_fields(
        objective=(
            "顧客管理機能を追加する"
        ),
        success_criteria=(
            "顧客登録が成功すること"
        ),
    )

    contract = fields[
        "requirement_contract"
    ]

    assert isinstance(contract, dict)
    assert isinstance(
        contract["requirements"],
        list,
    )
    assert isinstance(
        contract["risks"],
        list,
    )
