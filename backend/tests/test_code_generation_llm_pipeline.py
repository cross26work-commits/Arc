from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.code_generation import (
    LLM_PIPELINE_VERSION,
    CodeGenerationLLMAdapter,
    CodeGenerationLLMPipelineError,
    DeterministicCodeGenerationLLMAdapter,
    LLMGenerationRequest,
    LLMGenerationResponse,
    run_code_generation_llm_pipeline,
    run_code_generation_llm_pipeline_safe,
)


MISSION_ID = 1
CONTEXT_SHA256 = "e" * 64
TARGET_PATH = "backend/app/api/auth.py"


def _context() -> dict[str, Any]:
    return {
        "mission_id": MISSION_ID,
        "sha256": CONTEXT_SHA256,
        "files": [
            {
                "relative_path":
                    TARGET_PATH,
                "content":
                    "def current_user():\n"
                    "    return {}\n",
            }
        ],
    }


def _request() -> LLMGenerationRequest:
    return LLMGenerationRequest(
        mission_id=MISSION_ID,
        system_prompt=(
            "Code Generation Contractを"
            "JSON Objectで生成してください。"
        ),
        user_prompt=(
            "current_user関数に"
            "戻り値型を追加してください。"
        ),
        context_sha256=CONTEXT_SHA256,
    )


def _contract_payload() -> dict[str, Any]:
    return {
        "contract_version":
            "mission-code-generation-contract-v0.1",
        "mission_id": MISSION_ID,
        "context_sha256": CONTEXT_SHA256,
        "summary":
            "current_user関数へ戻り値型を追加する。",
        "reasoning":
            "対象関数定義が一意であるため。",
        "edits": [
            {
                "operation":
                    "REPLACE_UNIQUE",
                "path": TARGET_PATH,
                "old_text":
                    "def current_user():\n",
                "new_text":
                    "def current_user() -> dict:\n",
                "anchor": None,
                "text": None,
            }
        ],
        "generated_by":
            "deterministic-llm-adapter",
        "assumptions": [],
        "warnings": [],
    }


def _adapter(
) -> DeterministicCodeGenerationLLMAdapter:
    return (
        DeterministicCodeGenerationLLMAdapter(
            response_payload=(
                _contract_payload()
            )
        )
    )


def _integration_result(
) -> dict[str, Any]:
    return {
        "integrated": True,
        "integration_version":
            "mission-code-generation-"
            "patch-integration-v0.1",
        "mission_id": MISSION_ID,
        "contract_sha256": "a" * 64,
        "context_sha256":
            CONTEXT_SHA256,
        "patch_request_sha256":
            "b" * 64,
        "patch_check": {
            "git_apply_check": {
                "applicable": True,
                "returncode": 0,
                "stderr": "",
            },
            "applied": False,
        },
        "implementation": {
            "mode": "PATCH_CHECKED",
        },
        "next_stage":
            "WAIT_PATCH_APPLY_APPROVAL",
    }


def test_pipeline_connects_llm_to_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_integration(
        *,
        mission_id: int,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        captured["mission_id"] = mission_id
        captured["payload"] = payload
        captured["context"] = context

        return _integration_result()

    monkeypatch.setattr(
        "app.code_generation.llm_pipeline."
        "run_code_generation_patch_integration",
        fake_integration,
    )

    result = run_code_generation_llm_pipeline(
        adapter=_adapter(),
        request=_request(),
        context=_context(),
    )

    assert result[
        "pipeline_version"
    ] == LLM_PIPELINE_VERSION

    assert (
        result["pipeline_completed"]
        is True
    )

    assert result["mission_id"] == MISSION_ID

    assert result["provider"] == (
        "deterministic"
    )

    assert result["patch_applied"] is False

    assert result["next_stage"] == (
        "WAIT_PATCH_APPLY_APPROVAL"
    )

    assert captured["mission_id"] == (
        MISSION_ID
    )

    assert captured["payload"] == (
        _contract_payload()
    )

    assert captured["context"] == _context()


def test_pipeline_rejects_context_mission_mismatch(
) -> None:
    context = _context()
    context["mission_id"] = 999

    with pytest.raises(
        CodeGenerationLLMPipelineError,
        match="Mission ID",
    ):
        run_code_generation_llm_pipeline(
            adapter=_adapter(),
            request=_request(),
            context=context,
        )


def test_pipeline_rejects_context_hash_mismatch(
) -> None:
    context = _context()
    context["sha256"] = "f" * 64

    with pytest.raises(
        CodeGenerationLLMPipelineError,
        match="SHA-256",
    ):
        run_code_generation_llm_pipeline(
            adapter=_adapter(),
            request=_request(),
            context=context,
        )


def test_pipeline_rejects_contract_mission_mismatch(
) -> None:
    payload = _contract_payload()
    payload["mission_id"] = 999

    adapter = (
        DeterministicCodeGenerationLLMAdapter(
            response_payload=payload
        )
    )

    with pytest.raises(
        CodeGenerationLLMPipelineError,
        match="ContractのMission ID",
    ):
        run_code_generation_llm_pipeline(
            adapter=adapter,
            request=_request(),
            context=_context(),
        )


def test_pipeline_rejects_contract_hash_mismatch(
) -> None:
    payload = _contract_payload()
    payload["context_sha256"] = "f" * 64

    adapter = (
        DeterministicCodeGenerationLLMAdapter(
            response_payload=payload
        )
    )

    with pytest.raises(
        CodeGenerationLLMPipelineError,
        match="ContractのContext SHA-256",
    ):
        run_code_generation_llm_pipeline(
            adapter=adapter,
            request=_request(),
            context=_context(),
        )


class InvalidResponseAdapter(
    CodeGenerationLLMAdapter
):
    @property
    def provider(self) -> str:
        return "invalid"

    @property
    def model(self) -> str:
        return "invalid-response-v0.1"

    def generate(
        self,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        valid_response = _adapter().generate(
            request
        )

        return replace(
            valid_response,
            response_sha256="0" * 64,
        )


def test_pipeline_rejects_response_hash_mismatch(
) -> None:
    with pytest.raises(
        CodeGenerationLLMPipelineError,
        match="Response SHA-256",
    ):
        run_code_generation_llm_pipeline(
            adapter=InvalidResponseAdapter(),
            request=_request(),
            context=_context(),
        )


class InvalidJsonAdapter(
    CodeGenerationLLMAdapter
):
    @property
    def provider(self) -> str:
        return "invalid-json"

    @property
    def model(self) -> str:
        return "invalid-json-v0.1"

    def generate(
        self,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        valid_response = _adapter().generate(
            request
        )

        raw_text = "not-json"

        from app.code_generation import (
            calculate_generation_response_sha256,
        )

        return replace(
            valid_response,
            raw_text=raw_text,
            response_sha256=(
                calculate_generation_response_sha256(
                    raw_text
                )
            ),
        )


def test_pipeline_rejects_invalid_json(
) -> None:
    with pytest.raises(
        CodeGenerationLLMPipelineError,
        match="Contract JSON",
    ):
        run_code_generation_llm_pipeline(
            adapter=InvalidJsonAdapter(),
            request=_request(),
            context=_context(),
        )


def test_pipeline_wraps_integration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.code_generation import (
        CodeGenerationPatchIntegrationError,
    )

    def fake_integration(
        *,
        mission_id: int,
        payload: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        raise CodeGenerationPatchIntegrationError(
            "fixture integration error"
        )

    monkeypatch.setattr(
        "app.code_generation.llm_pipeline."
        "run_code_generation_patch_integration",
        fake_integration,
    )

    with pytest.raises(
        CodeGenerationLLMPipelineError,
        match="fixture integration error",
    ):
        run_code_generation_llm_pipeline(
            adapter=_adapter(),
            request=_request(),
            context=_context(),
        )


def test_safe_pipeline_returns_failure(
) -> None:
    context = _context()
    context["sha256"] = "f" * 64

    result = (
        run_code_generation_llm_pipeline_safe(
            adapter=_adapter(),
            request=_request(),
            context=context,
        )
    )

    assert (
        result["pipeline_completed"]
        is False
    )

    assert result["patch_applied"] is False

    assert result["next_stage"] == (
        "LLM_PIPELINE_FAILED"
    )

    assert isinstance(
        result["error"],
        str,
    )

    assert result["error"]
