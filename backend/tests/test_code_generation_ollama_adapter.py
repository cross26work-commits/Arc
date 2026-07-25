from __future__ import annotations

import io
import json
import socket
from typing import Any
from urllib.error import (
    HTTPError,
    URLError,
)

import pytest

from app.code_generation import (
    OLLAMA_ADAPTER_VERSION,
    LLMGenerationRequest,
    OllamaAdapterConfig,
    OllamaCodeGenerationLLMAdapter,
    OllamaConnectionError,
    OllamaHTTPError,
    OllamaResponseError,
    OllamaTimeoutError,
    calculate_generation_input_sha256,
    calculate_generation_response_sha256,
)


MISSION_ID = 1
CONTEXT_SHA256 = "a" * 64


def _request() -> LLMGenerationRequest:
    return LLMGenerationRequest(
        mission_id=MISSION_ID,
        system_prompt=(
            "Return only a valid JSON object."
        ),
        user_prompt=(
            "Generate a code generation contract."
        ),
        context_sha256=CONTEXT_SHA256,
    )


def _response_payload(
    *,
    content: str = (
        '{"status":"ok"}'
    ),
) -> dict[str, Any]:
    return {
        "model": "qwen3:4b",
        "created_at":
            "2026-07-25T12:46:40Z",
        "message": {
            "role": "assistant",
            "content": content,
        },
        "done": True,
        "done_reason": "stop",
        "total_duration": 100,
        "load_duration": 10,
        "prompt_eval_count": 20,
        "prompt_eval_duration": 30,
        "eval_count": 40,
        "eval_duration": 50,
    }


class FakeHTTPResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status: int = 200,
    ) -> None:
        self.status = status
        self._body = json.dumps(
            payload
        ).encode("utf-8")

    def __enter__(
        self,
    ) -> "FakeHTTPResponse":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None

    def read(
        self,
        amount: int = -1,
    ) -> bytes:
        return self._body[:amount]


def test_config_normalizes_values() -> None:
    config = OllamaAdapterConfig(
        base_url=(
            "http://127.0.0.1:11434/"
        ),
        model=" qwen3:4b ",
        timeout_seconds=300,
        temperature=0,
    )

    assert config.base_url == (
        "http://127.0.0.1:11434"
    )

    assert config.model == "qwen3:4b"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "base_url": "ftp://host",
            },
            "http",
        ),
        (
            {
                "model": " ",
            },
            "Model",
        ),
        (
            {
                "timeout_seconds": 0,
            },
            "Timeout",
        ),
        (
            {
                "temperature": 3,
            },
            "Temperature",
        ),
    ],
)
def test_config_rejects_invalid_values(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        OllamaAdapterConfig(**kwargs)


def test_generate_builds_valid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(
        request: Any,
        *,
        timeout: float,
    ) -> FakeHTTPResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(
            request.header_items()
        )

        request_body = json.loads(
            request.data.decode("utf-8")
        )

        captured["body"] = request_body

        return FakeHTTPResponse(
            _response_payload()
        )

    monkeypatch.setattr(
        "app.code_generation.ollama_adapter."
        "urlopen",
        fake_urlopen,
    )

    adapter = (
        OllamaCodeGenerationLLMAdapter(
            config=OllamaAdapterConfig(
                model="qwen3:4b",
                timeout_seconds=300,
                temperature=0,
            )
        )
    )

    request = _request()

    response = adapter.generate(request)

    assert response.provider == "ollama"
    assert response.model == "qwen3:4b"
    assert response.raw_text == (
        '{"status":"ok"}'
    )
    assert response.finish_reason == "stop"

    assert response.input_sha256 == (
        calculate_generation_input_sha256(
            request
        )
    )

    assert response.response_sha256 == (
        calculate_generation_response_sha256(
            response.raw_text
        )
    )

    assert response.metadata[
        "adapter_version"
    ] == OLLAMA_ADAPTER_VERSION

    assert captured["url"] == (
        "http://127.0.0.1:11434/api/chat"
    )

    assert captured["timeout"] == 300

    assert captured["body"]["model"] == (
        "qwen3:4b"
    )

    assert captured["body"]["stream"] is False

    assert captured["body"]["format"] == (
        "json"
    )

    assert captured["body"]["options"][
        "temperature"
    ] == 0

    assert captured["body"]["messages"] == [
        {
            "role": "system",
            "content":
                request.system_prompt,
        },
        {
            "role": "user",
            "content":
                request.user_prompt,
        },
    ]


def test_generate_rejects_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: Any,
        *,
        timeout: float,
    ) -> Any:
        raise HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            {},
            io.BytesIO(
                b'{"error":"failure"}'
            ),
        )

    monkeypatch.setattr(
        "app.code_generation.ollama_adapter."
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        OllamaHTTPError,
        match="status=500",
    ):
        (
            OllamaCodeGenerationLLMAdapter()
            .generate(_request())
        )


def test_generate_rejects_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: Any,
        *,
        timeout: float,
    ) -> Any:
        raise URLError(
            ConnectionRefusedError(
                "connection refused"
            )
        )

    monkeypatch.setattr(
        "app.code_generation.ollama_adapter."
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        OllamaConnectionError,
        match="接続できません",
    ):
        (
            OllamaCodeGenerationLLMAdapter()
            .generate(_request())
        )


def test_generate_rejects_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: Any,
        *,
        timeout: float,
    ) -> Any:
        raise socket.timeout(
            "timed out"
        )

    monkeypatch.setattr(
        "app.code_generation.ollama_adapter."
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        OllamaTimeoutError,
        match="Timeout",
    ):
        (
            OllamaCodeGenerationLLMAdapter()
            .generate(_request())
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                **_response_payload(),
                "message": "invalid",
            },
            "message",
        ),
        (
            {
                **_response_payload(),
                "message": {
                    "role": "user",
                    "content":
                        '{"status":"ok"}',
                },
            },
            "assistant",
        ),
        (
            {
                **_response_payload(),
                "message": {
                    "role": "assistant",
                    "content": "",
                },
            },
            "空",
        ),
        (
            {
                **_response_payload(),
                "done": False,
            },
            "完了状態",
        ),
        (
            {
                key: value
                for key, value
                in _response_payload().items()
                if key != "model"
            },
            "model",
        ),
    ],
)
def test_generate_rejects_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    message: str,
) -> None:
    def fake_urlopen(
        request: Any,
        *,
        timeout: float,
    ) -> FakeHTTPResponse:
        return FakeHTTPResponse(payload)

    monkeypatch.setattr(
        "app.code_generation.ollama_adapter."
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        OllamaResponseError,
        match=message,
    ):
        (
            OllamaCodeGenerationLLMAdapter()
            .generate(_request())
        )


def test_generate_rejects_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidResponse:
        status = 200

        def __enter__(
            self,
        ) -> "InvalidResponse":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            return None

        def read(
            self,
            amount: int = -1,
        ) -> bytes:
            return b"not-json"

    def fake_urlopen(
        request: Any,
        *,
        timeout: float,
    ) -> InvalidResponse:
        return InvalidResponse()

    monkeypatch.setattr(
        "app.code_generation.ollama_adapter."
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        OllamaResponseError,
        match="JSON",
    ):
        (
            OllamaCodeGenerationLLMAdapter()
            .generate(_request())
        )
