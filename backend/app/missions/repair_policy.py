from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


REPAIR_POLICY_VERSION = "mission-repair-policy-v0.1"


class FailureCategory(StrEnum):
    TIMEOUT = "TIMEOUT"
    PERMISSION = "PERMISSION"
    DEPENDENCY = "DEPENDENCY"
    SYNTAX = "SYNTAX"
    IMPORT = "IMPORT"
    LINT = "LINT"
    TEST = "TEST"
    BUILD = "BUILD"
    GIT = "GIT"
    COMMAND = "COMMAND"
    UNKNOWN = "UNKNOWN"


class RepairAction(StrEnum):
    REGENERATE_CODE = "REGENERATE_CODE"
    REGENERATE_PATCH = "REGENERATE_PATCH"
    RETRY_COMMAND = "RETRY_COMMAND"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    STOP_AND_INSPECT = "STOP_AND_INSPECT"


class ResumeStage(StrEnum):
    RUN_CODE_GENERATION = "RUN_CODE_GENERATION"
    RUN_PATCH_GENERATION = "RUN_PATCH_GENERATION"
    RUN_VERIFICATION = "RUN_VERIFICATION"
    WAIT_REPAIR_APPROVAL = "WAIT_REPAIR_APPROVAL"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class RepairPolicyRule:
    category: FailureCategory
    action: RepairAction
    resume_stage: ResumeStage
    max_retries: int
    requires_approval: bool = False


REPAIR_POLICY_RULES: dict[
    FailureCategory,
    RepairPolicyRule,
] = {
    FailureCategory.SYNTAX: RepairPolicyRule(
        category=FailureCategory.SYNTAX,
        action=RepairAction.REGENERATE_CODE,
        resume_stage=ResumeStage.RUN_CODE_GENERATION,
        max_retries=3,
    ),
    FailureCategory.IMPORT: RepairPolicyRule(
        category=FailureCategory.IMPORT,
        action=RepairAction.REGENERATE_CODE,
        resume_stage=ResumeStage.RUN_CODE_GENERATION,
        max_retries=3,
    ),
    FailureCategory.TEST: RepairPolicyRule(
        category=FailureCategory.TEST,
        action=RepairAction.REGENERATE_CODE,
        resume_stage=ResumeStage.RUN_CODE_GENERATION,
        max_retries=3,
    ),
    FailureCategory.LINT: RepairPolicyRule(
        category=FailureCategory.LINT,
        action=RepairAction.REGENERATE_CODE,
        resume_stage=ResumeStage.RUN_CODE_GENERATION,
        max_retries=3,
    ),
    FailureCategory.BUILD: RepairPolicyRule(
        category=FailureCategory.BUILD,
        action=RepairAction.REGENERATE_CODE,
        resume_stage=ResumeStage.RUN_CODE_GENERATION,
        max_retries=2,
    ),
    FailureCategory.DEPENDENCY: RepairPolicyRule(
        category=FailureCategory.DEPENDENCY,
        action=RepairAction.REQUIRE_APPROVAL,
        resume_stage=ResumeStage.WAIT_REPAIR_APPROVAL,
        max_retries=1,
        requires_approval=True,
    ),
    FailureCategory.PERMISSION: RepairPolicyRule(
        category=FailureCategory.PERMISSION,
        action=RepairAction.REQUIRE_APPROVAL,
        resume_stage=ResumeStage.WAIT_REPAIR_APPROVAL,
        max_retries=1,
        requires_approval=True,
    ),
    FailureCategory.TIMEOUT: RepairPolicyRule(
        category=FailureCategory.TIMEOUT,
        action=RepairAction.RETRY_COMMAND,
        resume_stage=ResumeStage.RUN_VERIFICATION,
        max_retries=2,
    ),
    FailureCategory.GIT: RepairPolicyRule(
        category=FailureCategory.GIT,
        action=RepairAction.STOP_AND_INSPECT,
        resume_stage=ResumeStage.STOPPED,
        max_retries=1,
        requires_approval=True,
    ),
    FailureCategory.COMMAND: RepairPolicyRule(
        category=FailureCategory.COMMAND,
        action=RepairAction.RETRY_COMMAND,
        resume_stage=ResumeStage.RUN_VERIFICATION,
        max_retries=2,
    ),
    FailureCategory.UNKNOWN: RepairPolicyRule(
        category=FailureCategory.UNKNOWN,
        action=RepairAction.STOP_AND_INSPECT,
        resume_stage=ResumeStage.STOPPED,
        max_retries=1,
        requires_approval=True,
    ),
}


def normalize_failure_category(
    value: Any,
) -> FailureCategory:
    normalized = str(
        value or FailureCategory.UNKNOWN
    ).strip().upper()

    try:
        return FailureCategory(normalized)
    except ValueError:
        return FailureCategory.UNKNOWN


def get_repair_policy(
    value: Any,
) -> RepairPolicyRule:
    category = normalize_failure_category(value)
    return REPAIR_POLICY_RULES[category]


def serialize_repair_policy(
    rule: RepairPolicyRule,
) -> dict[str, Any]:
    return {
        "policy_version": REPAIR_POLICY_VERSION,
        "failure_category": rule.category.value,
        "repair_action": rule.action.value,
        "resume_stage": rule.resume_stage.value,
        "max_retries": rule.max_retries,
        "requires_approval": rule.requires_approval,
    }
