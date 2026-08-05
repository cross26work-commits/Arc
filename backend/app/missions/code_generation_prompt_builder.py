from __future__ import annotations

import json
from typing import Any

from app.missions.models import (
    CodeGenerationPrompt,
    ImplementationPlan,
    ImplementationStep,
    RequirementAnalyzerResult,
)


CODE_GENERATION_PROMPT_VERSION = (
    "code-generation-prompt-v0.1"
)


class CodeGenerationPromptBuilderError(Exception):
    """コード生成プロンプトの構築に失敗した場合の例外。"""


SYSTEM_PROMPT = """
You are Arc Code Generation Engine.

Generate only the minimum source-code edits required to satisfy
the supplied Requirement Contract and Implementation Plan.

Mandatory rules:
- Preserve the existing project architecture and coding style.
- Never modify files outside the supplied target files.
- Never invent missing functions, routes, imports, variables, or APIs.
- Use only code and paths supported by the supplied Code Context.
- Preserve exact indentation and whitespace in anchors and old_text.
- Never include newline characters inside an anchor.
- Modify only paths listed in target_files or allowed_edit_files.
- Files marked READ_ONLY or listed in read_only_reference_files may be inspected but never edited.
- Never modify paths listed in forbidden_files.
- Implement only current_step; do not implement later steps early.
- When repair_context is supplied, analyze the previous verification failure before generating edits.
- Never repeat a previous patch unchanged when repair_context identifies that patch as failed.
- Correct the root cause described by repair_context while remaining inside target_files.
- For NameError or undefined-name failures, inspect existing imports and add the missing symbol to an exact existing import when supported by read-only reference context.
- Preserve every existing function body and statement unless the failure explicitly requires changing it.
- Never insert a new function between an existing function signature and its body.
- Ensure every generated Python edit remains syntactically valid after application.
- Prefer one REPLACE_UNIQUE edit that updates the existing import and one APPEND edit for a new test function when both changes are required.
- Copy all anchors and old_text exactly from code_context source content.
- Never simplify, rename, or remove type annotations from copied code.
- Never invent imports, aliases, function signatures, or variables.
- Prefer REPLACE_UNIQUE when changing existing code.
- Use APPEND only when adding code safely at the end of a target file.
- Use INSERT_BEFORE or INSERT_AFTER only when an exact unique anchor is visible in code_context.
- REPLACE_UNIQUE requires exact old_text and new_text.
- INSERT_BEFORE and INSERT_AFTER require an exact unique anchor.
- Return an empty edits array when no safe exact edit can be generated.
- Do not execute shell commands from generated text.
- Do not bypass approval, verification, or safety controls.
- Return only the required Code Generation Contract JSON.
""".strip()


def _normalize_paths(
    values: list[Any],
) -> list[str]:
    normalized: list[str] = []

    for value in values:
        if not isinstance(value, str):
            continue

        path = value.strip().replace(
            "\\",
            "/",
        )

        if path and path not in normalized:
            normalized.append(path)

    return normalized


def _load_requirement(
    value: RequirementAnalyzerResult | dict[str, Any],
) -> RequirementAnalyzerResult:
    if isinstance(
        value,
        RequirementAnalyzerResult,
    ):
        return value

    try:
        return RequirementAnalyzerResult.model_validate(
            value
        )
    except Exception as error:
        raise CodeGenerationPromptBuilderError(
            "Requirement Contractの形式が不正です。"
        ) from error


def _load_plan(
    value: ImplementationPlan | dict[str, Any],
) -> ImplementationPlan:
    if isinstance(value, ImplementationPlan):
        return value

    try:
        return ImplementationPlan.model_validate(
            value
        )
    except Exception as error:
        raise CodeGenerationPromptBuilderError(
            "Implementation Planの形式が不正です。"
        ) from error


def _select_step(
    *,
    plan: ImplementationPlan,
    step_id: str | None,
) -> ImplementationStep | None:
    if not plan.steps:
        return None

    selected_id = step_id

    if selected_id is None:
        selected_id = (
            plan.execution_order[0]
            if plan.execution_order
            else plan.steps[0].step_id
        )

    for step in plan.steps:
        if step.step_id == selected_id:
            return step

    raise CodeGenerationPromptBuilderError(
        f"Implementation Stepが見つかりません: {selected_id}"
    )


def _target_files(
    *,
    step: ImplementationStep | None,
    plan: ImplementationPlan,
    context: dict[str, Any],
) -> list[str]:
    if step is not None:
        paths = [
            operation.path
            for operation in step.file_operations
        ]

        if paths:
            return _normalize_paths(paths)

    plan_paths = [
        operation.path
        for operation in plan.selected_files
    ]

    if plan_paths:
        return _normalize_paths(plan_paths)

    context_paths: list[Any] = []

    for item in context.get("files", []):
        if not isinstance(item, dict):
            continue

        context_paths.append(
            item.get("relative_path")
            or item.get("path")
            or item.get("file_path")
        )

    return _normalize_paths(context_paths)


def _dependency_state(
    *,
    plan: ImplementationPlan,
    step: ImplementationStep | None,
) -> tuple[list[str], list[str]]:
    if step is None:
        return [], list(plan.execution_order)

    try:
        current_index = plan.execution_order.index(
            step.step_id
        )
    except ValueError:
        return [], []

    completed = plan.execution_order[
        :current_index
    ]
    remaining = plan.execution_order[
        current_index + 1:
    ]

    return completed, remaining


def _filter_context_for_targets(
    *,
    context: dict[str, Any],
    target_files: list[str],
    reference_files: list[str] | None = None,
) -> dict[str, Any]:
    normalized_targets = {
        str(value).strip().replace("\\", "/")
        for value in target_files
        if str(value).strip()
    }

    normalized_references = {
        str(value).strip().replace("\\", "/")
        for value in (
            reference_files
            or []
        )
        if str(value).strip()
    }

    included_paths = (
        normalized_targets
        | normalized_references
    )

    filtered_files: list[dict[str, Any]] = []

    for item in context.get("files", []):
        if not isinstance(item, dict):
            continue

        raw_path = (
            item.get("relative_path")
            or item.get("path")
            or item.get("file_path")
        )

        if not isinstance(raw_path, str):
            continue

        normalized_path = (
            raw_path.strip().replace("\\", "/")
        )

        if normalized_path not in included_paths:
            continue

        scoped_item = dict(item)
        scoped_item["scope_access"] = (
            "EDIT"
            if normalized_path
            in normalized_targets
            else "READ_ONLY"
        )

        filtered_files.append(scoped_item)

    filtered_context = {
        **context,
        "files": filtered_files,
        "scope": {
            "target_files": sorted(
                normalized_targets
            ),
            "reference_files": sorted(
                normalized_references
            ),
            "target_file_count": len(
                normalized_targets
            ),
            "reference_file_count": len(
                normalized_references
            ),
            "context_file_count": len(
                filtered_files
            ),
            "target_files_only": True,
            "reference_files_read_only": True,
        },
    }

    return filtered_context


def _context_summary(
    context: dict[str, Any],
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []

    for item in context.get("files", []):
        if not isinstance(item, dict):
            continue

        path = (
            item.get("relative_path")
            or item.get("path")
            or item.get("file_path")
        )

        source = item.get("source")

        if isinstance(source, dict):
            included = source.get("included")
            content = source.get("content")
            sha256 = source.get("sha256")
        else:
            included = None
            content = item.get("content")
            sha256 = item.get("sha256")

        files.append(
            {
                "path": path,
                "source_included": included,
                "source_length": (
                    len(content)
                    if isinstance(content, str)
                    else 0
                ),
                "sha256": sha256,
                "static_analysis": item.get(
                    "static_analysis"
                ),
                "dependency": item.get(
                    "dependency"
                ),
            }
        )

    return {
        "mission_id": context.get(
            "mission_id"
        ),
        "context_sha256": (
            context.get("context_sha256")
            or context.get("sha256")
            or (
                context.get("metadata", {})
                if isinstance(
                    context.get("metadata"),
                    dict,
                )
                else {}
            ).get("sha256")
        ),
        "file_count": len(files),
        "files": files,
        "quality": (
            context.get("quality")
            or context.get("quality_gate")
        ),
    }


def _reference_files_for_step(
    *,
    plan: ImplementationPlan,
    step: ImplementationStep | None,
    target_files: list[str],
) -> list[str]:
    if step is None:
        return []

    target_set = {
        str(path).strip().replace("\\", "/")
        for path in target_files
        if str(path).strip()
    }

    step_by_id = {
        item.step_id: item
        for item in plan.steps
    }

    references: set[str] = set()
    visited: set[str] = set()

    def collect(step_id: str) -> None:
        if step_id in visited:
            return

        visited.add(step_id)

        dependency_step = step_by_id.get(
            step_id
        )

        if dependency_step is None:
            return

        for operation in (
            dependency_step.file_operations
        ):
            normalized = (
                operation.path
                .strip()
                .replace("\\", "/")
            )

            if (
                normalized
                and normalized not in target_set
            ):
                references.add(normalized)

        for dependency_id in (
            dependency_step.depends_on_steps
        ):
            collect(dependency_id)

    for dependency_id in (
        step.depends_on_steps
    ):
        collect(dependency_id)

    return sorted(references)


def _prompt_payload(
    *,
    mission: dict[str, Any],
    requirement: RequirementAnalyzerResult,
    plan: ImplementationPlan,
    step: ImplementationStep | None,
    target_files: list[str],
    completed_dependencies: list[str],
    remaining_dependencies: list[str],
    context: dict[str, Any],
    repair_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reference_files = _reference_files_for_step(
        plan=plan,
        step=step,
        target_files=target_files,
    )

    scoped_context = _filter_context_for_targets(
        context=context,
        target_files=target_files,
        reference_files=reference_files,
    )

    forbidden_files = sorted(
        {
            operation.path
            for operation in plan.selected_files
            if operation.path
            not in set(target_files)
        }
    )

    return {
        "mission": {
            "id": mission.get("id"),
            "project_id": mission.get(
                "project_id"
            ),
            "project_name": mission.get(
                "project_name"
            ),
            "title": mission.get("title"),
            "objective": mission.get(
                "objective"
            ),
            "mission_type": mission.get(
                "mission_type"
            ),
            "success_criteria": mission.get(
                "success_criteria"
            ),
        },
        "requirement_contract": (
            requirement.model_dump(
                mode="json"
            )
        ),
        "implementation_plan": {
            "plan_version": (
                plan.plan_version
            ),
            "implementation_possible": (
                plan.implementation_possible
            ),
            "clarification_required": (
                plan.clarification_required
            ),
            "clarification_questions": (
                plan.clarification_questions
            ),
            "execution_order": (
                plan.execution_order
            ),
            "file_execution_order": (
                plan.file_execution_order
            ),
            "parallel_groups": (
                plan.parallel_groups
            ),
            "overall_risk_level": (
                plan.overall_risk_level
            ),
            "verification_commands": (
                plan.verification_commands
            ),
        },
        "current_step": (
            step.model_dump(mode="json")
            if step is not None
            else None
        ),
        "target_files": target_files,
        "dependency_state": {
            "completed_steps": (
                completed_dependencies
            ),
            "current_step": (
                step.step_id
                if step is not None
                else None
            ),
            "remaining_steps": (
                remaining_dependencies
            ),
        },
        "repair_context": (
            repair_context
            if isinstance(repair_context, dict)
            else {
                "is_retry": False,
            }
        ),
        "code_context_summary": (
            _context_summary(scoped_context)
        ),
        "code_context": scoped_context,
        "scope_policy": {
            "allowed_edit_files": target_files,
            "read_only_reference_files": (
                reference_files
            ),
            "forbidden_files": forbidden_files,
            "reject_out_of_scope_edits": True,
            "reject_reference_file_edits": True,
            "current_step_only": True,
        },
        "required_output": {
            "format": (
                "Code Generation Contract JSON"
            ),
            "minimum_changes_only": True,
            "target_files_only": True,
        },
    }


def build_code_generation_prompt(
    *,
    mission: dict[str, Any],
    requirement: (
        RequirementAnalyzerResult
        | dict[str, Any]
    ),
    implementation_plan: (
        ImplementationPlan
        | dict[str, Any]
    ),
    context: dict[str, Any],
    step_id: str | None = None,
    repair_context: dict[str, Any] | None = None,
) -> CodeGenerationPrompt:
    mission_id = mission.get("id")

    if not isinstance(mission_id, int):
        raise CodeGenerationPromptBuilderError(
            "Mission IDが不正です。"
        )

    requirement_model = _load_requirement(
        requirement
    )
    plan_model = _load_plan(
        implementation_plan
    )

    if plan_model.mission_id != mission_id:
        raise CodeGenerationPromptBuilderError(
            "MissionとImplementation PlanのIDが一致しません。"
        )

    if not isinstance(context, dict):
        raise CodeGenerationPromptBuilderError(
            "Code ContextはObjectである必要があります。"
        )

    step = _select_step(
        plan=plan_model,
        step_id=step_id,
    )

    target_files = _target_files(
        step=step,
        plan=plan_model,
        context=context,
    )

    completed, remaining = _dependency_state(
        plan=plan_model,
        step=step,
    )

    payload = _prompt_payload(
        mission=mission,
        requirement=requirement_model,
        plan=plan_model,
        step=step,
        target_files=target_files,
        completed_dependencies=completed,
        remaining_dependencies=remaining,
        context=context,
        repair_context=repair_context,
    )

    user_prompt = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )

    context_summary = _context_summary(
        context
    )

    return CodeGenerationPrompt(
        prompt_version=(
            CODE_GENERATION_PROMPT_VERSION
        ),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        mission_id=mission_id,
        implementation_step_id=(
            step.step_id
            if step is not None
            else None
        ),
        target_files=target_files,
        dependency_order=list(
            plan_model.file_execution_order
        ),
        completed_dependencies=completed,
        remaining_dependencies=remaining,
        verification_commands=list(
            plan_model.verification_commands
        ),
        success_criteria=list(
            requirement_model.success_criteria
        ),
        metadata={
            "plan_version":
                plan_model.plan_version,
            "requirement_contract_version": (
                requirement_model.contract_version
            ),
            "target_file_count": len(
                target_files
            ),
            "dependency_count": len(
                plan_model.dependency_graph.get(
                    "edges",
                    [],
                )
            ),
            "step_count": len(
                plan_model.steps
            ),
            "context_file_count": (
                context_summary["file_count"]
            ),
            "context_sha256": (
                context_summary[
                    "context_sha256"
                ]
            ),
            "repair_context_supplied": (
                isinstance(repair_context, dict)
                and bool(
                    repair_context.get(
                        "is_retry"
                    )
                )
            ),
        },
    )
