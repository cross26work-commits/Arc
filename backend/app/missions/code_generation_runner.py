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
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
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



def _build_ollama_response_schema(
    *,
    mission_id: int,
    context_sha256: str,
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

    request = LLMGenerationRequest(
        mission_id=mission_id,
        system_prompt=_build_system_prompt(),
        user_prompt=_build_user_prompt(
            mission={
                **mission,
                "objective": objective,
            },
            context=context,
        ),
        context_sha256=context_sha256,
        response_format=(
            _build_ollama_response_schema(
                mission_id=mission_id,
                context_sha256=context_sha256,
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

    result = {
        "runner_version": (
            MISSION_CODE_GENERATION_RUNNER_VERSION
        ),
        "mission_id": mission_id,
        "provider": adapter.provider,
        "model": adapter.model,
        "context_sha256": context_sha256,
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
