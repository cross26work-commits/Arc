from app.missions.models import (
    FileOperation,
    ImplementationPlan,
    ImplementationStep,
    RequirementAnalyzerResult,
)


def test_file_operation_model() -> None:
    operation = FileOperation(
        path="backend/app/example.py",
        operation="UPDATE",
        purpose="既存API処理を更新する。",
        category="BACKEND",
        language="python",
        risk_level="LOW",
    )

    assert operation.path == "backend/app/example.py"
    assert operation.operation == "UPDATE"
    assert operation.category == "BACKEND"


def test_implementation_step_model() -> None:
    step = ImplementationStep(
        step_id="step-1",
        position=1,
        title="Backendを更新",
        description="対象サービスの処理を変更する。",
        category="BACKEND",
        file_operations=[
            FileOperation(
                path="backend/app/example.py",
                operation="UPDATE",
                purpose="処理を更新する。",
                category="BACKEND",
            )
        ],
        completion_criteria=[
            "Python構文確認を通過する。"
        ],
    )

    assert step.step_id == "step-1"
    assert step.position == 1
    assert len(step.file_operations) == 1


def test_implementation_plan_model() -> None:
    requirement = RequirementAnalyzerResult(
        objective="既存APIへ新しい処理を追加する。",
        requirements=[
            "API処理を追加する。"
        ],
        success_criteria=[
            "テストが成功する。"
        ],
        implementation_possible=True,
        analysis_summary=(
            "実装可能な要求として整理された。"
        ),
    )

    operation = FileOperation(
        path="backend/app/example.py",
        operation="UPDATE",
        purpose="API処理を追加する。",
        category="BACKEND",
    )

    step = ImplementationStep(
        step_id="step-1",
        position=1,
        title="API処理を実装",
        description="対象ファイルへ処理を追加する。",
        category="BACKEND",
        file_operations=[operation],
        completion_criteria=[
            "構文確認が成功する。"
        ],
    )

    plan = ImplementationPlan(
        mission_id=1,
        project_id=1,
        project_name="Example",
        objective=requirement.objective,
        success_criteria=(
            requirement.success_criteria
        ),
        requirement_contract_version=(
            requirement.contract_version
        ),
        requirement_contract=requirement,
        implementation_possible=True,
        selected_files=[operation],
        steps=[step],
        execution_order=["step-1"],
        verification_commands=[
            "python -m py_compile backend/app/example.py"
        ],
        overall_risk_level="LOW",
        estimated_effort_level="SMALL",
        approval_summary=(
            "1ファイルを更新し、構文確認を実行する。"
        ),
    )

    payload = plan.model_dump(
        mode="json"
    )

    assert payload["plan_version"] == (
        "implementation-plan-v0.1"
    )
    assert payload["mission_id"] == 1
    assert payload["steps"][0]["step_id"] == "step-1"
    assert (
        payload["requirement_contract"]
        ["implementation_possible"]
        is True
    )


def test_plan_supports_clarification_questions() -> None:
    requirement = RequirementAnalyzerResult(
        objective="認証機能を改善する。",
        ambiguities=[
            "改善内容が明確ではない。"
        ],
        missing_information=[
            "対象認証方式が不明。"
        ],
        implementation_possible=False,
        analysis_summary=(
            "追加情報が必要である。"
        ),
    )

    plan = ImplementationPlan(
        mission_id=1,
        project_id=1,
        project_name="Example",
        objective=requirement.objective,
        requirement_contract_version=(
            requirement.contract_version
        ),
        requirement_contract=requirement,
        implementation_possible=False,
        clarification_required=True,
        clarification_questions=[
            "対象の認証方式は何ですか？"
        ],
        approval_summary=(
            "実装前に追加確認が必要である。"
        ),
    )

    assert plan.clarification_required is True
    assert len(plan.clarification_questions) == 1
