from __future__ import annotations

import json

import pytest

from app.code_generation import (
    LLM_ADAPTER_VERSION,
    CodeGenerationLLMAdapterError,
    DeterministicCodeGenerationLLMAdapter,
    LLMGenerationRequest,
    calculate_generation_input_sha256,
    calculate_generation_response_sha256,
    extract_json_object,
)


CONTEXT_SHA256 = "d" * 64


def _request() -> LLMGenerationRequest:
    return LLMGenerationRequest(
        mission_id=1,
        system_prompt=(
            "Code Generation Contractを"
            "JSONで生成してください。"
        ),
        user_prompt=(
            "current_user関数へ"
            "戻り値型を追加してください。"
        ),
        context_sha256=CONTEXT_SHA256,
    )


def _contract_payload() -> dict:
    return {
        "contract_version":
            "mission-code-generation-contract-v0.1",
        "mission_id": 1,
        "context_sha256": CONTEXT_SHA256,
        "summary":
            "current_user関数へ戻り値型を追加する。",
        "reasoning":
            "対象関数定義が一意であるため。",
        "edits": [
            {
                "operation": "REPLACE_UNIQUE",
                "path":
                    "backend/app/api/auth.py",
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


def test_request_is_valid() -> None:
    request = _request()

    assert request.mission_id == 1
    assert (
        request.context_sha256
        == CONTEXT_SHA256
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mission_id", 0),
        ("system_prompt", ""),
        ("user_prompt", ""),
        ("context_sha256", "invalid"),
    ],
)
def test_request_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    values = {
        "mission_id": 1,
        "system_prompt": "system",
        "user_prompt": "user",
        "context_sha256": CONTEXT_SHA256,
    }

    values[field] = value

    with pytest.raises(
        CodeGenerationLLMAdapterError
    ):
        LLMGenerationRequest(**values)


def test_input_sha256_is_deterministic() -> None:
    first = calculate_generation_input_sha256(
        _request()
    )

    second = calculate_generation_input_sha256(
        _request()
    )

    assert first == second
    assert len(first) == 64


def test_response_sha256_is_deterministic() -> None:
    raw_text = '{"status":"ok"}'

    first = (
        calculate_generation_response_sha256(
            raw_text
        )
    )

    second = (
        calculate_generation_response_sha256(
            raw_text
        )
    )

    assert first == second
    assert len(first) == 64


def test_extract_json_object_from_plain_json() -> None:
    result = extract_json_object(
        '{"status":"ok"}'
    )

    assert result == {
        "status": "ok"
    }


def test_extract_json_object_from_json_fence() -> None:
    result = extract_json_object(
        "説明です。\n"
        "```json\n"
        '{"status":"ok"}\n'
        "```\n"
    )

    assert result == {
        "status": "ok"
    }


def test_extract_json_object_from_surrounding_text() -> None:
    result = extract_json_object(
        "生成結果:\n"
        '{"status":"ok"}\n'
        "以上です。"
    )

    assert result == {
        "status": "ok"
    }


@pytest.mark.parametrize(
    "raw_text",
    [
        "",
        "not-json",
        "[]",
        "```json\n[]\n```",
    ],
)
def test_extract_json_object_rejects_invalid_text(
    raw_text: str,
) -> None:
    with pytest.raises(
        CodeGenerationLLMAdapterError
    ):
        extract_json_object(raw_text)


def test_deterministic_adapter_generates_response() -> None:
    payload = _contract_payload()

    adapter = (
        DeterministicCodeGenerationLLMAdapter(
            response_payload=payload
        )
    )

    response = adapter.generate(
        _request()
    )

    assert response.provider == "deterministic"

    assert response.model == (
        "contract-fixture-v0.1"
    )

    assert response.finish_reason == "stop"

    assert (
        response.metadata["adapter_version"]
        == LLM_ADAPTER_VERSION
    )

    assert (
        response.metadata["network_used"]
        is False
    )

    assert (
        response.metadata["deterministic"]
        is True
    )

    assert len(response.input_sha256) == 64

    assert len(response.response_sha256) == 64

    decoded = extract_json_object(
        response.raw_text
    )

    assert decoded == payload


def test_deterministic_adapter_is_repeatable() -> None:
    adapter = (
        DeterministicCodeGenerationLLMAdapter(
            response_payload=(
                _contract_payload()
            )
        )
    )

    first = adapter.generate(
        _request()
    )

    second = adapter.generate(
        _request()
    )

    assert first.raw_text == second.raw_text

    assert (
        first.input_sha256
        == second.input_sha256
    )

    assert (
        first.response_sha256
        == second.response_sha256
    )


def test_adapter_output_is_json_serializable() -> None:
    adapter = (
        DeterministicCodeGenerationLLMAdapter(
            response_payload=(
                _contract_payload()
            )
        )
    )

    response = adapter.generate(
        _request()
    )

    serialized = json.dumps(
        {
            "provider": response.provider,
            "model": response.model,
            "raw_text": response.raw_text,
            "finish_reason":
                response.finish_reason,
            "input_sha256":
                response.input_sha256,
            "response_sha256":
                response.response_sha256,
            "metadata":
                dict(response.metadata),
        },
        ensure_ascii=False,
    )

    assert isinstance(serialized, str)
    assert serialized
