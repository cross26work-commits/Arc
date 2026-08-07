from __future__ import annotations

from typing import Any

from app.code_generation.llm_adapter import (
    CodeGenerationLLMAdapter,
    CodeGenerationLLMAdapterError,
    LLMGenerationRequest,
    LLMGenerationResponse,
    calculate_generation_input_sha256,
    calculate_generation_response_sha256,
    extract_json_object,
)
from app.code_generation.patch_integration import (
    CodeGenerationPatchIntegrationError,
    run_code_generation_patch_integration_safe,
)


def run_code_generation_patch_integration(
    *,
    mission_id: int,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Backward-compatible integration entry point."""
    return run_code_generation_patch_integration_safe(
        mission_id=mission_id,
        payload=payload,
        context=context,
    )


LLM_PIPELINE_VERSION = (
    "mission-code-generation-llm-pipeline-v0.1"
)


class CodeGenerationLLMPipelineError(
    RuntimeError
):
    """LLM生成からPatch Checkまでの統合エラー。"""


def _require_mapping(
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CodeGenerationLLMPipelineError(
            f"{label}の形式が不正です。"
        )

    return value


def _extract_context_mission_id(
    context: dict[str, Any],
) -> int | None:
    mission_id = context.get("mission_id")

    if isinstance(mission_id, int):
        return mission_id

    mission = context.get("mission")

    if isinstance(mission, dict):
        nested_id = mission.get("id")

        if isinstance(nested_id, int):
            return nested_id

    return None


def _extract_context_sha256(
    context: dict[str, Any],
) -> str | None:
    for key in (
        "sha256",
        "context_sha256",
        "content_sha256",
    ):
        value = context.get(key)

        if isinstance(value, str):
            return value

    metadata = context.get("metadata")

    if isinstance(metadata, dict):
        for key in (
            "sha256",
            "context_sha256",
            "content_sha256",
        ):
            value = metadata.get(key)

            if isinstance(value, str):
                return value

    return None


def _validate_request_against_context(
    *,
    request: LLMGenerationRequest,
    context: dict[str, Any],
) -> None:
    context_mission_id = (
        _extract_context_mission_id(
            context
        )
    )

    if context_mission_id is None:
        raise CodeGenerationLLMPipelineError(
            "Code ContextにMission IDがありません。"
        )

    if (
        context_mission_id
        != request.mission_id
    ):
        raise CodeGenerationLLMPipelineError(
            "Generation RequestとCode Contextの"
            "Mission IDが一致しません。 "
            f"request={request.mission_id} "
            f"context={context_mission_id}"
        )

    context_sha256 = _extract_context_sha256(
        context
    )

    if context_sha256 is None:
        raise CodeGenerationLLMPipelineError(
            "Code ContextにSHA-256がありません。"
        )

    if (
        context_sha256
        != request.context_sha256
    ):
        raise CodeGenerationLLMPipelineError(
            "Generation RequestとCode Contextの"
            "SHA-256が一致しません。 "
            f"request={request.context_sha256} "
            f"context={context_sha256}"
        )


def _validate_generation_response(
    *,
    request: LLMGenerationRequest,
    response: LLMGenerationResponse,
) -> None:
    expected_input_sha256 = (
        calculate_generation_input_sha256(
            request
        )
    )

    if (
        response.input_sha256
        != expected_input_sha256
    ):
        raise CodeGenerationLLMPipelineError(
            "LLM応答のInput SHA-256が"
            "Generation Requestと一致しません。 "
            f"expected={expected_input_sha256} "
            f"actual={response.input_sha256}"
        )

    expected_response_sha256 = (
        calculate_generation_response_sha256(
            response.raw_text
        )
    )

    if (
        response.response_sha256
        != expected_response_sha256
    ):
        raise CodeGenerationLLMPipelineError(
            "LLM応答のResponse SHA-256が"
            "Raw Textと一致しません。 "
            f"expected={expected_response_sha256} "
            f"actual={response.response_sha256}"
        )


def run_code_generation_llm_pipeline(
    *,
    adapter: CodeGenerationLLMAdapter,
    request: LLMGenerationRequest,
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    LLM生成結果を既存の安全なPatch Integrationへ接続する。

    この関数はPatchを適用しない。
    最終状態はPATCH_CHECKEDかつ承認待ちである。
    """

    if not isinstance(
        adapter,
        CodeGenerationLLMAdapter,
    ):
        raise CodeGenerationLLMPipelineError(
            "LLM Adapterが不正です。"
        )

    if not isinstance(
        request,
        LLMGenerationRequest,
    ):
        raise CodeGenerationLLMPipelineError(
            "Generation Requestが不正です。"
        )

    context_payload = _require_mapping(
        context,
        label="Code Context",
    )

    _validate_request_against_context(
        request=request,
        context=context_payload,
    )

    try:
        response = adapter.generate(request)
    except CodeGenerationLLMAdapterError as exc:
        raise CodeGenerationLLMPipelineError(
            "LLM生成に失敗しました: "
            f"{exc}"
        ) from exc
    except Exception as exc:
        raise CodeGenerationLLMPipelineError(
            "LLM Adapterで予期しない"
            "エラーが発生しました: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(
        response,
        LLMGenerationResponse,
    ):
        raise CodeGenerationLLMPipelineError(
            "LLM Adapterの応答型が不正です。"
        )

    _validate_generation_response(
        request=request,
        response=response,
    )

    try:
        contract_payload = extract_json_object(
            response.raw_text
        )
        print(
            "DEBUG_CONTRACT_PAYLOAD:",
            repr(contract_payload),
        )
    except CodeGenerationLLMAdapterError as exc:
        raise CodeGenerationLLMPipelineError(
            "LLM応答からContract JSONを"
            f"抽出できませんでした: {exc}"
        ) from exc

    payload_mission_id = (
        contract_payload.get("mission_id")
    )

    if (
        payload_mission_id
        != request.mission_id
    ):
        raise CodeGenerationLLMPipelineError(
            "LLM生成ContractのMission IDが"
            "Generation Requestと一致しません。 "
            f"request={request.mission_id} "
            f"contract={payload_mission_id}"
        )

    payload_context_sha256 = (
        contract_payload.get(
            "context_sha256"
        )
    )

    if (
        payload_context_sha256
        != request.context_sha256
    ):
        raise CodeGenerationLLMPipelineError(
            "LLM生成ContractのContext SHA-256が"
            "Generation Requestと一致しません。 "
            f"request={request.context_sha256} "
            f"contract={payload_context_sha256}"
        )

    try:
        integration_result = (
            run_code_generation_patch_integration(
                mission_id=request.mission_id,
                payload=contract_payload,
                context=context_payload,
            )
        )
    except (
        CodeGenerationPatchIntegrationError
    ) as exc:
        raise CodeGenerationLLMPipelineError(
            "LLM生成ContractのPatch Integrationに"
            f"失敗しました: {exc}"
        ) from exc

    integration_result = _require_mapping(
        integration_result,
        label="Patch Integration結果",
    )

    if (
        integration_result.get("integrated")
        is not True
    ):
        raise CodeGenerationLLMPipelineError(
            "Patch Integrationが成功状態では"
            "ありません。"
        )

    return {
        "pipeline_version":
            LLM_PIPELINE_VERSION,
        "pipeline_completed": True,
        "mission_id": request.mission_id,
        "provider": response.provider,
        "model": response.model,
        "finish_reason":
            response.finish_reason,
        "generation_input_sha256":
            response.input_sha256,
        "generation_response_sha256":
            response.response_sha256,
        "contract_payload":
            contract_payload,
        "integration":
            integration_result,
        "patch_applied": False,
        "next_stage":
            "WAIT_PATCH_APPLY_APPROVAL",
        "metadata": dict(response.metadata),
    }


def run_code_generation_llm_pipeline_safe(
    *,
    adapter: CodeGenerationLLMAdapter,
    request: LLMGenerationRequest,
    context: dict[str, Any],
) -> dict[str, Any]:
    try:
        return run_code_generation_llm_pipeline(
            adapter=adapter,
            request=request,
            context=context,
        )
    except CodeGenerationLLMPipelineError as exc:
        return {
            "pipeline_version":
                LLM_PIPELINE_VERSION,
            "pipeline_completed": False,
            "mission_id": getattr(
                request,
                "mission_id",
                None,
            ),
            "error": str(exc),
            "patch_applied": False,
            "next_stage":
                "LLM_PIPELINE_FAILED",
        }
