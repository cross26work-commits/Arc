from app.missions.repair_policy import (
    FailureCategory,
    RepairAction,
    REPAIR_POLICY_RULES,
    REPAIR_POLICY_VERSION,
    ResumeStage,
    get_repair_policy,
    normalize_failure_category,
    serialize_repair_policy,
)


def test_all_failure_categories_have_policy_rule():
    assert set(REPAIR_POLICY_RULES) == set(
        FailureCategory
    )


def test_normalize_failure_category_accepts_known_value():
    assert (
        normalize_failure_category("syntax")
        == FailureCategory.SYNTAX
    )


def test_normalize_failure_category_maps_unknown_value():
    assert (
        normalize_failure_category("not-supported")
        == FailureCategory.UNKNOWN
    )


def test_syntax_policy_regenerates_code():
    rule = get_repair_policy("SYNTAX")

    assert rule.action == RepairAction.REGENERATE_CODE
    assert (
        rule.resume_stage
        == ResumeStage.RUN_CODE_GENERATION
    )
    assert rule.max_retries == 3
    assert rule.requires_approval is False


def test_dependency_policy_requires_approval():
    rule = get_repair_policy("DEPENDENCY")

    assert rule.action == RepairAction.REQUIRE_APPROVAL
    assert (
        rule.resume_stage
        == ResumeStage.WAIT_REPAIR_APPROVAL
    )
    assert rule.requires_approval is True


def test_unknown_policy_stops_safely():
    rule = get_repair_policy("UNKNOWN")

    assert rule.action == RepairAction.STOP_AND_INSPECT
    assert rule.resume_stage == ResumeStage.STOPPED
    assert rule.requires_approval is True


def test_policy_serialization():
    payload = serialize_repair_policy(
        get_repair_policy("BUILD")
    )

    assert payload == {
        "policy_version": REPAIR_POLICY_VERSION,
        "failure_category": "BUILD",
        "repair_action": "REGENERATE_CODE",
        "resume_stage": "RUN_CODE_GENERATION",
        "max_retries": 2,
        "requires_approval": False,
    }
