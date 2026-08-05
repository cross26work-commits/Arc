from __future__ import annotations

import json
import os
from typing import Any

from app.code_context.builder import (
    CodeContextError,
    build_code_context_safe,
)
from app.code_generation.contract import (
    CodeGenerationContract,
)
from app.code_generation.llm_adapter import (
    CodeGenerationLLMAdapterError,
    LLMGenerationRequest,
)
from app.code_generation.llm_pipeline import (
    CodeGenerationLLMPipelineError,
    run_code_generation_llm_pipeline_safe,
)
from app.code_generation.ollama_adapter import (
    OllamaAdapterConfig,
    OllamaCodeGenerationLLMAdapter,
    OllamaCodeGenerationLLMAdapterError,
)
from app.missions.code_generation_prompt_builder import (
    CodeGenerationPromptBuilderError,
    build_code_generation_prompt,
)
from app.missions.implementation_step_state import (
    ImplementationStepStateError,
    load_step_execution,
    start_current_step,
    update_current_step_status,
)
from app.missions.models import (
    ImplementationPlan,
    ImplementationStepExecution,
    MissionTaskUpdate,
    RequirementAnalyzerResult,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
    update_mission_task,
)


MISSION_CODE_GENERATION_RUNNER_VERSION = (
    "mission-code-generation-runner-v0.1"
)

DEFAULT_CODE_GENERATION_MODEL = "qwen2.5-coder:7b"


class MissionCodeGenerationError(RuntimeError):
    """MissionのCode Generation統合実行エラー。"""


def _require_text(
    value: Any,
    *,
    label: str,
) -> str:
    if not isinstance(value, str):
        raise MissionCodeGenerationError(
            f"{label}が文字列ではありません。"
        )

    normalized = value.strip()

    if not normalized:
        raise MissionCodeGenerationError(
            f"{label}が空です。"
        )

    return normalized



def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any] | None:
    return next(
        (
            task
            for task in mission.get("tasks", [])
            if str(
                task.get("task_type") or ""
            ).strip().upper()
            == task_type
        ),
        None,
    )


def _load_json_object(
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if not isinstance(value, str):
        raise MissionCodeGenerationError(
            f"{label}の形式が不正です。"
        )

    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise MissionCodeGenerationError(
            f"{label}のJSONを読み取れません。"
        ) from error

    if not isinstance(payload, dict):
        raise MissionCodeGenerationError(
            f"{label}はJSON Objectである必要があります。"
        )

    return payload


def _load_prompt_inputs(
    mission: dict[str, Any],
) -> tuple[
    RequirementAnalyzerResult,
    ImplementationPlan,
]:
    requirements_task = _task_by_type(
        mission,
        "REQUIREMENTS",
    )
    planning_task = _task_by_type(
        mission,
        "PLANNING",
    )

    if requirements_task is None:
        raise MissionCodeGenerationError(
            "REQUIREMENTS Taskが見つかりません。"
        )

    if planning_task is None:
        raise MissionCodeGenerationError(
            "PLANNING Taskが見つかりません。"
        )

    if str(
        requirements_task.get("status") or ""
    ).strip().upper() != "COMPLETED":
        raise MissionCodeGenerationError(
            "REQUIREMENTS Taskが完了していません。"
        )

    if str(
        planning_task.get("status") or ""
    ).strip().upper() != "COMPLETED":
        raise MissionCodeGenerationError(
            "PLANNING Taskが完了していません。"
        )

    requirement_payload = _load_json_object(
        requirements_task.get("result"),
        label="REQUIREMENTS結果",
    )

    planning_payload = _load_json_object(
        planning_task.get("result"),
        label="PLANNING結果",
    )

    typed_plan_payload = planning_payload.get(
        "typed_plan"
    )

    if not isinstance(
        typed_plan_payload,
        dict,
    ):
        raise MissionCodeGenerationError(
            "PLANNING結果にtyped_planがありません。"
        )

    try:
        requirement = (
            RequirementAnalyzerResult.model_validate(
                requirement_payload
            )
        )
    except Exception as error:
        raise MissionCodeGenerationError(
            "Requirement Contractの形式が不正です。"
        ) from error

    try:
        implementation_plan = (
            ImplementationPlan.model_validate(
                typed_plan_payload
            )
        )
    except Exception as error:
        raise MissionCodeGenerationError(
            "Typed Implementation Planの形式が不正です。"
        ) from error

    return requirement, implementation_plan


def _load_step_execution_state(
    mission: dict[str, Any],
) -> ImplementationStepExecution | None:
    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )

    if implementation_task is None:
        return None

    raw_result = implementation_task.get(
        "result"
    )

    if not raw_result:
        return None

    implementation_payload = _load_json_object(
        raw_result,
        label="IMPLEMENTATION結果",
    )

    step_execution_payload = (
        implementation_payload.get(
            "step_execution"
        )
    )

    if not isinstance(
        step_execution_payload,
        dict,
    ):
        return None

    try:
        return load_step_execution(
            step_execution_payload
        )
    except ImplementationStepStateError as error:
        raise MissionCodeGenerationError(
            str(error)
        ) from error


def _persist_step_execution_state(
    *,
    mission_id: int,
    execution: ImplementationStepExecution,
) -> dict[str, Any]:
    latest_mission = get_mission(
        mission_id
    )

    implementation_task = _task_by_type(
        latest_mission,
        "IMPLEMENTATION",
    )

    if implementation_task is None:
        raise MissionCodeGenerationError(
            "IMPLEMENTATION Taskが見つかりません。"
        )

    implementation_payload = (
        _load_json_object(
            implementation_task.get("result"),
            label="IMPLEMENTATION結果",
        )
    )

    implementation_payload[
        "step_execution"
    ] = execution.model_dump(
        mode="json"
    )

    result_text = json.dumps(
        implementation_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionCodeGenerationError(
            "Step Execution更新後の"
            "IMPLEMENTATION結果が保存上限を超えました。"
        )

    return update_mission_task(
        mission_id=mission_id,
        task_id=implementation_task["id"],
        payload=MissionTaskUpdate(
            status=implementation_task["status"],
            result=result_text,
            target_path=(
                implementation_task.get(
                    "target_path"
                )
            ),
        ),
    )


def _start_generation_step(
    *,
    mission: dict[str, Any],
) -> ImplementationStepExecution | None:
    execution = _load_step_execution_state(
        mission
    )

    if execution is None:
        return None

    try:
        execution = start_current_step(
            execution
        )
    except ImplementationStepStateError as error:
        raise MissionCodeGenerationError(
            str(error)
        ) from error

    _persist_step_execution_state(
        mission_id=mission["id"],
        execution=execution,
    )

    return execution


def _mark_generation_step_patch_ready(
    *,
    execution: ImplementationStepExecution,
    prompt_version: str,
    context_sha256: str,
    integration: dict[str, Any],
) -> ImplementationStepExecution:
    try:
        execution = update_current_step_status(
            execution,
            status="PATCH_READY",
            metadata={
                "patch_request_sha256": (
                    integration.get(
                        "patch_request_sha256"
                    )
                ),
                "changed_file_count": (
                    integration.get(
                        "changed_file_count"
                    )
                ),
                "edit_count": (
                    integration.get(
                        "edit_count"
                    )
                ),
                "integration_version": (
                    integration.get(
                        "integration_version"
                    )
                ),
            },
        )
    except ImplementationStepStateError as error:
        raise MissionCodeGenerationError(
            str(error)
        ) from error

    step_id = execution.current_step_id

    if step_id is None:
        raise MissionCodeGenerationError(
            "PATCH_READY更新対象のStepがありません。"
        )

    step_result = execution.results.get(
        step_id
    )

    if step_result is None:
        raise MissionCodeGenerationError(
            f"Step Resultがありません: {step_id}"
        )

    step_result.prompt_version = (
        prompt_version
    )
    step_result.context_sha256 = (
        context_sha256
    )
    step_result.contract_sha256 = (
        integration.get(
            "contract_sha256"
        )
    )
    step_result.patch_sha256 = (
        integration.get(
            "patch_sha256"
        )
    )

    changed_files = integration.get(
        "changed_files"
    )

    step_result.changed_files = (
        [
            str(path)
            for path in changed_files
        ]
        if isinstance(
            changed_files,
            list,
        )
        else []
    )

    return execution


def _mark_generation_step_failed(
    *,
    execution: ImplementationStepExecution,
    error: str,
) -> ImplementationStepExecution:
    try:
        return update_current_step_status(
            execution,
            status="FAILED",
            error=error,
        )
    except ImplementationStepStateError as state_error:
        raise MissionCodeGenerationError(
            str(state_error)
        ) from state_error


def _load_current_step_id(
    mission: dict[str, Any],
) -> str | None:
    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )

    if implementation_task is None:
        return None

    raw_result = implementation_task.get(
        "result"
    )

    if not raw_result:
        return None

    try:
        implementation_payload = (
            _load_json_object(
                raw_result,
                label="IMPLEMENTATION結果",
            )
        )
    except MissionCodeGenerationError:
        return None

    step_execution_payload = (
        implementation_payload.get(
            "step_execution"
        )
    )

    if not isinstance(
        step_execution_payload,
        dict,
    ):
        return None

    try:
        execution = (
            ImplementationStepExecution.model_validate(
                step_execution_payload
            )
        )
    except Exception as error:
        raise MissionCodeGenerationError(
            "Step Execution Stateの形式が不正です。"
        ) from error

    if execution.execution_completed:
        raise MissionCodeGenerationError(
            "すべてのImplementation Stepが"
            "完了しているため、Code Generationを"
            "開始できません。"
        )

    return execution.current_step_id


def _truncate_repair_text(
    value: object,
    *,
    limit: int = 4000,
) -> str:
    text = str(value or "").strip()

    if len(text) <= limit:
        return text

    return (
        text[:limit]
        + "\n...[repair output truncated]..."
    )


def _verification_failure_summary(
    mission: dict[str, Any],
) -> dict[str, Any] | None:
    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    if implementation_task is None:
        return None

    implementation_payload = _load_json_object(
        implementation_task.get("result"),
        label="IMPLEMENTATION結果",
    )

    step_execution = implementation_payload.get(
        "step_execution"
    )

    if not isinstance(step_execution, dict):
        return None

    current_step_id = step_execution.get(
        "current_step_id"
    )
    results = step_execution.get("results")

    if (
        not isinstance(current_step_id, str)
        or not isinstance(results, dict)
    ):
        return None

    current_result = results.get(
        current_step_id
    )

    if not isinstance(current_result, dict):
        return None

    attempt_count = current_result.get(
        "attempt_count"
    )

    previous_patch_sha256 = current_result.get(
        "patch_sha256"
    )

    changed_files = current_result.get(
        "changed_files"
    )

    verification_payload: dict[str, Any] = {}

    if (
        verification_task is not None
        and verification_task.get("result")
    ):
        try:
            verification_payload = (
                _load_json_object(
                    verification_task.get("result"),
                    label="VERIFICATION結果",
                )
            )
        except MissionCodeGenerationError:
            verification_payload = {}

    failure_category = (
        verification_payload.get(
            "failure_category"
        )
        or current_result.get(
            "error"
        )
        or implementation_payload.get(
            "last_verification_failure",
            {},
        ).get(
            "failure_category"
        )
    )

    failed_outputs: list[str] = []

    verification_results = (
        verification_payload.get("results")
    )

    if isinstance(verification_results, list):
        for command_result in verification_results:
            if not isinstance(
                command_result,
                dict,
            ):
                continue

            if command_result.get("passed") is True:
                continue

            steps = command_result.get("steps")

            if not isinstance(steps, list):
                continue

            for step_result in steps:
                if not isinstance(
                    step_result,
                    dict,
                ):
                    continue

                stdout = _truncate_repair_text(
                    step_result.get("stdout")
                )
                stderr = _truncate_repair_text(
                    step_result.get("stderr")
                )

                if stdout:
                    failed_outputs.append(stdout)

                if stderr:
                    failed_outputs.append(stderr)

    current_step_error = (
        _truncate_repair_text(
            current_result.get("error")
        )
    )

    verification_error = (
        _truncate_repair_text(
            "\n".join(failed_outputs)
        )
    )

    error_sections: list[str] = []

    if current_step_error:
        error_sections.append(
            "Latest generation feedback:\n"
            + current_step_error
        )

    if verification_error:
        error_sections.append(
            "Previous verification failure:\n"
            + verification_error
        )

    error_summary = _truncate_repair_text(
        "\n\n".join(error_sections)
        or failure_category
        or "Previous verification failed."
    )

    is_retry = (
        current_result.get("status")
        in {
            "FAILED",
            "GENERATING",
            "PATCH_READY",
        }
        and isinstance(attempt_count, int)
        and attempt_count > 1
        and bool(failure_category)
    )

    if not is_retry:
        return None

    return {
        "is_retry": True,
        "failed_step_id": current_step_id,
        "attempt_count": attempt_count,
        "failure_category": str(
            failure_category
        ),
        "error_summary": error_summary,
        "changed_files": (
            [
                str(value)
                for value in changed_files
            ]
            if isinstance(changed_files, list)
            else []
        ),
        "previous_patch_sha256": (
            str(previous_patch_sha256)
            if previous_patch_sha256
            else None
        ),
        "instruction": (
            "Analyze the previous verification "
            "failure and generate a different "
            "minimal patch that fixes its root "
            "cause. Do not repeat the failed "
            "patch unchanged."
        ),
    }


def _build_generation_prompts(
    *,
    mission: dict[str, Any],
    context: dict[str, Any],
    step_id: str | None = None,
) -> dict[str, Any]:
    repair_context = (
        _verification_failure_summary(
            mission
        )
    )

    try:
        requirement, implementation_plan = (
            _load_prompt_inputs(mission)
        )

        structured_prompt = (
            build_code_generation_prompt(
                mission=mission,
                requirement=requirement,
                implementation_plan=(
                    implementation_plan
                ),
                context=context,
                step_id=step_id,
                repair_context=repair_context,
            )
        )

        return {
            "mode": "STRUCTURED",
            "system_prompt": (
                structured_prompt.system_prompt
            ),
            "user_prompt": (
                structured_prompt.user_prompt
            ),
            "prompt_version": (
                structured_prompt.prompt_version
            ),
            "implementation_step_id": (
                structured_prompt
                .implementation_step_id
            ),
            "target_files": list(
                structured_prompt.target_files
            ),
            "dependency_order": list(
                structured_prompt.dependency_order
            ),
            "metadata": dict(
                structured_prompt.metadata
            ),
            "repair_context": (
                repair_context
                if isinstance(
                    repair_context,
                    dict,
                )
                else {
                    "is_retry": False,
                }
            ),
            "fallback_reason": None,
        }

    except (
        MissionCodeGenerationError,
        CodeGenerationPromptBuilderError,
    ) as error:
        return {
            "mode": "LEGACY_FALLBACK",
            "system_prompt": (
                _build_system_prompt()
            ),
            "user_prompt": (
                _build_user_prompt(
                    mission=mission,
                    context=context,
                )
            ),
            "prompt_version": (
                "legacy-code-generation-prompt-v0.1"
            ),
            "implementation_step_id": None,
            "target_files": [],
            "dependency_order": [],
            "metadata": {},
            "repair_context": (
                repair_context
                if isinstance(
                    repair_context,
                    dict,
                )
                else {
                    "is_retry": False,
                }
            ),
            "fallback_reason": str(error),
        }


def _build_ollama_response_schema(
    *,
    mission_id: int,
    context_sha256: str,
    target_files: list[str] | None = None,
) -> dict[str, object]:
    """Pydantic SchemaをOllama grammar向けに正規化する。"""

    unsupported_keys = {
        "title",
        "description",
        "default",
        "examples",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
    }

    def sanitize(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: sanitize(item)
                for key, item in value.items()
                if key not in unsupported_keys
            }

        if isinstance(value, list):
            return [
                sanitize(item)
                for item in value
            ]

        return value

    schema = sanitize(
        CodeGenerationContract.model_json_schema()
    )

    if not isinstance(schema, dict):
        raise MissionCodeGenerationError(
            "OllamaのResponse Schemaが不正です。"
        )

    properties = schema.get("properties")

    if not isinstance(properties, dict):
        raise MissionCodeGenerationError(
            "OllamaのResponse Schemaに"
            "propertiesがありません。"
        )

    mission_schema = properties.get("mission_id")
    context_schema = properties.get("context_sha256")

    if not isinstance(mission_schema, dict):
        raise MissionCodeGenerationError(
            "Mission ID Schemaが不正です。"
        )

    if not isinstance(context_schema, dict):
        raise MissionCodeGenerationError(
            "Context SHA-256 Schemaが不正です。"
        )

    mission_schema["const"] = mission_id
    context_schema["const"] = context_sha256

    definitions = schema.get("$defs")

    if not isinstance(definitions, dict):
        raise MissionCodeGenerationError(
            "OllamaのResponse Schemaに$defsがありません。"
        )

    edit_schema = definitions.get("CodeGenerationEdit")

    if not isinstance(edit_schema, dict):
        raise MissionCodeGenerationError(
            "CodeGenerationEdit Schemaが不正です。"
        )

    string_or_null = {
        "anyOf": [
            {"type": "string"},
            {"type": "null"},
        ],
    }

    def build_edit_variant(
        *,
        operation: str,
        required: list[str],
    ) -> dict[str, object]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "const": operation,
                    "type": "string",
                },
                "path": {
                    "type": "string",
                    **(
                        {
                            "enum": list(
                                dict.fromkeys(
                                    target_files
                                    or []
                                )
                            )
                        }
                        if target_files
                        else {}
                    ),
                },
                "old_text": string_or_null,
                "new_text": string_or_null,
                "anchor": string_or_null,
                "text": string_or_null,
            },
            "required": required,
        }

    edit_schema.clear()
    edit_schema.update(
        {
            "oneOf": [
                build_edit_variant(
                    operation="REPLACE_UNIQUE",
                    required=[
                        "operation",
                        "path",
                        "old_text",
                        "new_text",
                    ],
                ),
                build_edit_variant(
                    operation="APPEND",
                    required=[
                        "operation",
                        "path",
                        "text",
                    ],
                ),
                build_edit_variant(
                    operation="INSERT_BEFORE",
                    required=[
                        "operation",
                        "path",
                        "anchor",
                        "text",
                    ],
                ),
                build_edit_variant(
                    operation="INSERT_AFTER",
                    required=[
                        "operation",
                        "path",
                        "anchor",
                        "text",
                    ],
                ),
            ],
        }
    )

    return schema

def _build_system_prompt() -> str:
    return """
あなたはArcのCode Generation Engineです。

与えられたMissionとCode Contextを解析し、
変更内容をCode Generation Contractとして生成してください。

必ず有効なJSON Objectのみを返してください。
Markdown、説明文、コードフェンスは出力しないでください。

返却JSONは次の条件を満たしてください。

- contract_version:
  "mission-code-generation-contract-v0.1"
- mission_id:
  入力されたMission ID
- context_sha256:
  入力されたContext SHA256
- summary:
  実装内容の要約
- reasoning:
  変更理由
- edits:
  編集操作の配列
- generated_by:
  使用したモデルまたは生成主体
- assumptions:
  仮定の配列
- warnings:
  警告の配列

各editでは、既存Contractが対応する操作だけを使用してください。

- REPLACE_UNIQUE
- APPEND
- INSERT_BEFORE
- INSERT_AFTER

対象コードに存在しない内容を推測して編集してはいけません。
変更はMission達成に必要な最小範囲に限定してください。

ANCHOR AND EDIT RULES:

- Copy every anchor exactly from the provided Code Context.
- Every anchor must contain exactly one line.
- Never include newline characters in an anchor.
- Preserve all indentation and whitespace in an anchor.
- Use an anchor that occurs exactly once in the target file.
- Never invent functions, routes, imports, variables, or code.
- INSERT_BEFORE and INSERT_AFTER require both anchor and text.
- REPLACE_UNIQUE requires both old_text and new_text.
- Copy old_text exactly from the provided Code Context.
- Do not generate edits outside the supplied Code Context.
- If the Mission requests only analysis, investigation, or planning
  and does not request source-code modification, return an empty edits array.
- Generate only the minimum edits required to achieve the Mission.
""".strip()


def _build_user_prompt(
    *,
    mission: dict[str, Any],
    context: dict[str, Any],
) -> str:
    mission_payload = {
        "id": mission.get("id"),
        "project_id": mission.get("project_id"),
        "project_name": mission.get("project_name"),
        "title": mission.get("title"),
        "objective": mission.get("objective"),
        "success_criteria": mission.get(
            "success_criteria"
        ),
    }

    prompt_payload = {
        "instruction": (
            "以下のMissionを達成するための"
            "Code Generation Contractを生成してください。"
        ),
        "mission": mission_payload,
        "code_context": context,
    }

    return json.dumps(
        prompt_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def run_mission_code_generation(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    objective = _require_text(
        mission.get("objective"),
        label="Mission objective",
    )

    context = build_code_context_safe(
        mission_id
    )

    context_sha256 = _require_text(
        context.get("context_sha256"),
        label="Context SHA256",
    )

    model = (
        os.getenv(
            "ARC_CODE_GENERATION_MODEL",
            DEFAULT_CODE_GENERATION_MODEL,
        ).strip()
        or DEFAULT_CODE_GENERATION_MODEL
    )

    base_url = (
        os.getenv(
            "ARC_OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        ).strip()
        or "http://127.0.0.1:11434"
    )

    step_execution = (
        _start_generation_step(
            mission=mission
        )
    )

    current_step_id = (
        step_execution.current_step_id
        if step_execution is not None
        else _load_current_step_id(
            mission
        )
    )

    prompt_bundle = _build_generation_prompts(
        mission={
            **mission,
            "objective": objective,
        },
        context=context,
        step_id=current_step_id,
    )

    request = LLMGenerationRequest(
        mission_id=mission_id,
        system_prompt=prompt_bundle[
            "system_prompt"
        ],
        user_prompt=prompt_bundle[
            "user_prompt"
        ],
        context_sha256=context_sha256,
        response_format=(
            _build_ollama_response_schema(
                mission_id=mission_id,
                context_sha256=context_sha256,
                target_files=prompt_bundle[
                    "target_files"
                ],
            )
        ),
    )

    adapter = OllamaCodeGenerationLLMAdapter(
        config=OllamaAdapterConfig(
            base_url=base_url,
            model=model,
            timeout_seconds=600.0,
            temperature=0.0,
            think=False,
            num_predict=2048,
            num_ctx=8192,
            keep_alive="15m",
        )
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="CODE_GENERATION_STARTED",
        message=(
            "Mission Code Generationを開始しました。"
        ),
        metadata={
            "runner_version": (
                MISSION_CODE_GENERATION_RUNNER_VERSION
            ),
            "provider": adapter.provider,
            "model": adapter.model,
            "context_sha256": context_sha256,
            "prompt_mode": (
                prompt_bundle["mode"]
            ),
            "prompt_version": (
                prompt_bundle[
                    "prompt_version"
                ]
            ),
            "implementation_step_id": (
                prompt_bundle[
                    "implementation_step_id"
                ]
            ),
            "step_state_source": (
                "IMPLEMENTATION_TASK"
                if current_step_id is not None
                else "PLAN_DEFAULT"
            ),
            "step_execution_status": (
                (
                    step_execution.results[
                        step_execution.current_step_id
                    ].status
                )
                if (
                    step_execution is not None
                    and step_execution.current_step_id
                    is not None
                )
                else None
            ),
            "step_attempt_count": (
                (
                    step_execution.results[
                        step_execution.current_step_id
                    ].attempt_count
                )
                if (
                    step_execution is not None
                    and step_execution.current_step_id
                    is not None
                )
                else 0
            ),
            "target_file_count": len(
                prompt_bundle[
                    "target_files"
                ]
            ),
            "dependency_order_count": len(
                prompt_bundle[
                    "dependency_order"
                ]
            ),
            "prompt_fallback_reason": (
                prompt_bundle[
                    "fallback_reason"
                ]
            ),
        },
    )

    pipeline_result = (
        run_code_generation_llm_pipeline_safe(
            adapter=adapter,
            request=request,
            context=context,
        )
    )

    if pipeline_result.get(
        "pipeline_completed"
    ) is not True:
        error = str(
            pipeline_result.get("error")
            or "LLM Pipelineが完了しませんでした。"
        )

        if step_execution is not None:
            step_execution = (
                _mark_generation_step_failed(
                    execution=step_execution,
                    error=error,
                )
            )

            _persist_step_execution_state(
                mission_id=mission_id,
                execution=step_execution,
            )

        add_mission_log(
            mission_id=mission_id,
            level="ERROR",
            event_type="CODE_GENERATION_FAILED",
            message=error,
            metadata={
                "runner_version": (
                    MISSION_CODE_GENERATION_RUNNER_VERSION
                ),
                "provider": adapter.provider,
                "model": adapter.model,
                "context_sha256": context_sha256,
                "pipeline_result": pipeline_result,
            },
        )

        raise MissionCodeGenerationError(error)

    integration = pipeline_result.get(
        "integration"
    )

    if not isinstance(integration, dict):
        raise MissionCodeGenerationError(
            "Patch Integration結果が不正です。"
        )

    repair_context = prompt_bundle.get(
        "repair_context"
    )

    previous_patch_sha256 = None

    if isinstance(repair_context, dict):
        previous_patch_sha256 = (
            repair_context.get(
                "previous_patch_sha256"
            )
        )

    generated_patch_sha256 = integration.get(
        "patch_sha256"
    )

    repeated_failed_patch = (
        isinstance(previous_patch_sha256, str)
        and bool(previous_patch_sha256)
        and isinstance(
            generated_patch_sha256,
            str,
        )
        and generated_patch_sha256
        == previous_patch_sha256
    )

    if repeated_failed_patch:
        error_message = (
            "Generated repair patch matches "
            "the previously failed patch SHA256: "
            f"{generated_patch_sha256}"
        )

        if step_execution is not None:
            step_execution = (
                _mark_generation_step_failed(
                    execution=step_execution,
                    error=error_message,
                )
            )

            _persist_step_execution_state(
                mission_id=mission_id,
                execution=step_execution,
            )

        add_mission_log(
            mission_id=mission_id,
            level="ERROR",
            event_type=(
                "CODE_GENERATION_REPEATED_PATCH_REJECTED"
            ),
            message=error_message,
            metadata={
                "runner_version": (
                    MISSION_CODE_GENERATION_RUNNER_VERSION
                ),
                "implementation_step_id": (
                    current_step_id
                ),
                "previous_patch_sha256": (
                    previous_patch_sha256
                ),
                "generated_patch_sha256": (
                    generated_patch_sha256
                ),
                "repair_context_supplied": True,
            },
        )

        raise MissionCodeGenerationError(
            error_message
        )

    if step_execution is not None:
        step_execution = (
            _mark_generation_step_patch_ready(
                execution=step_execution,
                prompt_version=(
                    prompt_bundle[
                        "prompt_version"
                    ]
                ),
                context_sha256=context_sha256,
                integration=integration,
            )
        )

        _persist_step_execution_state(
            mission_id=mission_id,
            execution=step_execution,
        )

    result = {
        "runner_version": (
            MISSION_CODE_GENERATION_RUNNER_VERSION
        ),
        "mission_id": mission_id,
        "provider": adapter.provider,
        "model": adapter.model,
        "context_sha256": context_sha256,
        "prompt_mode": prompt_bundle["mode"],
        "prompt_version": (
            prompt_bundle["prompt_version"]
        ),
        "implementation_step_id": (
            prompt_bundle[
                "implementation_step_id"
            ]
        ),
        "step_state_source": (
            "IMPLEMENTATION_TASK"
            if current_step_id is not None
            else "PLAN_DEFAULT"
        ),
        "target_files": (
            prompt_bundle["target_files"]
        ),
        "dependency_order": (
            prompt_bundle[
                "dependency_order"
            ]
        ),
        "prompt_metadata": (
            prompt_bundle["metadata"]
        ),
        "prompt_fallback_reason": (
            prompt_bundle[
                "fallback_reason"
            ]
        ),
        "step_execution_status": (
            (
                step_execution.results[
                    step_execution.current_step_id
                ].status
            )
            if (
                step_execution is not None
                and step_execution.current_step_id
                is not None
            )
            else None
        ),
        "code_generation_completed": True,
        **pipeline_result,
    }

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="CODE_GENERATION_COMPLETED",
        message=(
            "Mission Code Generationと"
            "Patch Checkを完了しました。"
        ),
        metadata={
            "runner_version": (
                MISSION_CODE_GENERATION_RUNNER_VERSION
            ),
            "provider": adapter.provider,
            "model": adapter.model,
            "context_sha256": context_sha256,
            "prompt_mode": (
                prompt_bundle["mode"]
            ),
            "prompt_version": (
                prompt_bundle[
                    "prompt_version"
                ]
            ),
            "implementation_step_id": (
                prompt_bundle[
                    "implementation_step_id"
                ]
            ),
            "target_file_count": len(
                prompt_bundle[
                    "target_files"
                ]
            ),
            "step_execution_status": (
                (
                    step_execution.results[
                        step_execution.current_step_id
                    ].status
                )
                if (
                    step_execution is not None
                    and step_execution.current_step_id
                    is not None
                )
                else None
            ),
            "contract_sha256": (
                integration.get(
                    "contract_sha256"
                )
            ),
            "patch_sha256": (
                integration.get(
                    "patch_sha256"
                )
            ),
            "changed_file_count": (
                integration.get(
                    "changed_file_count"
                )
            ),
            "next_stage": result.get("next_stage"),
        },
    )

    return result


def run_mission_code_generation_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_mission_code_generation(
            mission_id
        )
    except MissionCodeGenerationError:
        raise
    except (
        MissionError,
        CodeContextError,
        CodeGenerationLLMAdapterError,
        OllamaCodeGenerationLLMAdapterError,
        CodeGenerationLLMPipelineError,
    ) as error:
        raise MissionCodeGenerationError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionCodeGenerationError(
            "Mission Code Generation実行に"
            f"失敗しました: {error}"
        ) from error
