from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.error import (
    HTTPError,
    URLError,
)
from urllib.parse import urlparse
from urllib.request import (
    Request,
    urlopen,
)

from app.code_generation.llm_adapter import (
    CodeGenerationLLMAdapter,
    CodeGenerationLLMAdapterError,
    LLMGenerationRequest,
    LLMGenerationResponse,
    calculate_generation_input_sha256,
    calculate_generation_response_sha256,
)


OLLAMA_ADAPTER_VERSION = (
    "mission-code-generation-ollama-adapter-v0.2"
)

DEFAULT_OLLAMA_BASE_URL = (
    "http://127.0.0.1:11434"
)

DEFAULT_OLLAMA_MODEL = "qwen3:4b"

DEFAULT_OLLAMA_TIMEOUT_SECONDS = 300.0

DEFAULT_OLLAMA_THINK = False

DEFAULT_OLLAMA_NUM_PREDICT = 1024

DEFAULT_OLLAMA_NUM_CTX = 4096

DEFAULT_OLLAMA_KEEP_ALIVE = "10m"

MAX_OLLAMA_RESPONSE_BYTES = 10_000_000


class OllamaCodeGenerationLLMAdapterError(
    CodeGenerationLLMAdapterError
):
    """Ollama Adapter固有エラー。"""


class OllamaConnectionError(
    OllamaCodeGenerationLLMAdapterError
):
    """Ollamaへ接続できない場合のエラー。"""


class OllamaTimeoutError(
    OllamaCodeGenerationLLMAdapterError
):
    """Ollama応答がTimeoutした場合のエラー。"""


class OllamaHTTPError(
    OllamaCodeGenerationLLMAdapterError
):
    """OllamaがHTTPエラーを返した場合のエラー。"""


class OllamaResponseError(
    OllamaCodeGenerationLLMAdapterError
):
    """Ollama応答形式が不正な場合のエラー。"""


@dataclass(frozen=True)
class OllamaAdapterConfig:
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model: str = DEFAULT_OLLAMA_MODEL
    timeout_seconds: float = (
        DEFAULT_OLLAMA_TIMEOUT_SECONDS
    )
    temperature: float = 0.0
    think: bool = DEFAULT_OLLAMA_THINK
    num_predict: int = (
        DEFAULT_OLLAMA_NUM_PREDICT
    )
    num_ctx: int = DEFAULT_OLLAMA_NUM_CTX
    keep_alive: str = (
        DEFAULT_OLLAMA_KEEP_ALIVE
    )

    def __post_init__(self) -> None:
        normalized_base_url = (
            self.base_url.strip().rstrip("/")
        )

        parsed = urlparse(normalized_base_url)

        if parsed.scheme not in {
            "http",
            "https",
        }:
            raise ValueError(
                "Ollama Base URLはhttpまたは"
                "httpsで指定してください。"
            )

        if not parsed.netloc:
            raise ValueError(
                "Ollama Base URLにHostがありません。"
            )

        normalized_model = self.model.strip()

        if not normalized_model:
            raise ValueError(
                "Ollama Modelは空にできません。"
            )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "Timeoutは0秒より大きく"
                "指定してください。"
            )

        if not 0 <= self.temperature <= 2:
            raise ValueError(
                "Temperatureは0以上2以下で"
                "指定してください。"
            )

        if not isinstance(self.think, bool):
            raise ValueError(
                "Thinkはboolで指定してください。"
            )

        if isinstance(self.num_predict, bool):
            raise ValueError(
                "num_predictは整数で"
                "指定してください。"
            )

        if not isinstance(self.num_predict, int):
            raise ValueError(
                "num_predictは整数で"
                "指定してください。"
            )

        if not 1 <= self.num_predict <= 8192:
            raise ValueError(
                "num_predictは1以上8192以下で"
                "指定してください。"
            )

        if isinstance(self.num_ctx, bool):
            raise ValueError(
                "num_ctxは整数で"
                "指定してください。"
            )

        if not isinstance(self.num_ctx, int):
            raise ValueError(
                "num_ctxは整数で"
                "指定してください。"
            )

        if not 512 <= self.num_ctx <= 262144:
            raise ValueError(
                "num_ctxは512以上262144以下で"
                "指定してください。"
            )

        if not isinstance(self.keep_alive, str):
            raise ValueError(
                "keep_aliveは文字列で"
                "指定してください。"
            )

        normalized_keep_alive = (
            self.keep_alive.strip()
        )

        if not normalized_keep_alive:
            raise ValueError(
                "keep_aliveは空にできません。"
            )

        object.__setattr__(
            self,
            "base_url",
            normalized_base_url,
        )

        object.__setattr__(
            self,
            "model",
            normalized_model,
        )

        object.__setattr__(
            self,
            "keep_alive",
            normalized_keep_alive,
        )


def _decode_json_object(
    raw_bytes: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    if len(raw_bytes) > MAX_OLLAMA_RESPONSE_BYTES:
        raise OllamaResponseError(
            f"{label}が最大許容Sizeを"
            "超えています。 "
            f"size={len(raw_bytes)} "
            f"max={MAX_OLLAMA_RESPONSE_BYTES}"
        )

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OllamaResponseError(
            f"{label}をUTF-8として"
            "Decodeできません。"
        ) from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OllamaResponseError(
            f"{label}がJSONではありません。 "
            f"line={exc.lineno} "
            f"column={exc.colno}"
        ) from exc

    if not isinstance(payload, dict):
        raise OllamaResponseError(
            f"{label}がJSON Objectではありません。"
        )

    return payload


class OllamaCodeGenerationLLMAdapter(
    CodeGenerationLLMAdapter
):
    def __init__(
        self,
        *,
        config: OllamaAdapterConfig | None = None,
    ) -> None:
        self._config = (
            config
            if config is not None
            else OllamaAdapterConfig()
        )

    @property
    def provider(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def config(self) -> OllamaAdapterConfig:
        return self._config

    def _build_request_payload(
        self,
        request: LLMGenerationRequest,
    ) -> dict[str, Any]:
        return {
            "model": self._config.model,
            "stream": False,
            "format": "json",
            "think": self._config.think,
            "keep_alive": (
                self._config.keep_alive
            ),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        request.system_prompt
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        request.user_prompt
                    ),
                },
            ],
            "options": {
                "temperature": (
                    self._config.temperature
                ),
                "num_predict": (
                    self._config.num_predict
                ),
                "num_ctx": (
                    self._config.num_ctx
                ),
            },
        }

    def _post_chat(
        self,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        endpoint = (
            f"{self._config.base_url}/api/chat"
        )

        request_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        http_request = Request(
            endpoint,
            data=request_bytes,
            headers={
                "Content-Type":
                    "application/json",
                "Accept":
                    "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(
                http_request,
                timeout=(
                    self._config.timeout_seconds
                ),
            ) as response:
                status = getattr(
                    response,
                    "status",
                    None,
                )

                raw_bytes = response.read(
                    MAX_OLLAMA_RESPONSE_BYTES + 1
                )

        except HTTPError as exc:
            try:
                error_body = exc.read(
                    20_000
                ).decode(
                    "utf-8",
                    errors="replace",
                )
            except Exception:
                error_body = ""

            raise OllamaHTTPError(
                "OllamaがHTTPエラーを"
                "返しました。 "
                f"status={exc.code} "
                f"reason={exc.reason!r} "
                f"body={error_body!r}"
            ) from exc

        except (
            TimeoutError,
            socket.timeout,
        ) as exc:
            raise OllamaTimeoutError(
                "Ollama応答がTimeoutしました。 "
                f"timeout_seconds="
                f"{self._config.timeout_seconds}"
            ) from exc

        except URLError as exc:
            reason = exc.reason

            if isinstance(
                reason,
                (
                    TimeoutError,
                    socket.timeout,
                ),
            ):
                raise OllamaTimeoutError(
                    "Ollama応答がTimeoutしました。 "
                    f"timeout_seconds="
                    f"{self._config.timeout_seconds}"
                ) from exc

            raise OllamaConnectionError(
                "Ollamaへ接続できません。 "
                f"endpoint={endpoint} "
                f"reason={reason!r}"
            ) from exc

        except OSError as exc:
            raise OllamaConnectionError(
                "Ollamaとの通信に失敗しました。 "
                f"endpoint={endpoint} "
                f"error={exc}"
            ) from exc

        if status != 200:
            raise OllamaHTTPError(
                "Ollamaが成功以外のStatusを"
                "返しました。 "
                f"status={status}"
            )

        return _decode_json_object(
            raw_bytes,
            label="Ollama Response",
        )

    def generate(
        self,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        if not isinstance(
            request,
            LLMGenerationRequest,
        ):
            raise OllamaCodeGenerationLLMAdapterError(
                "Generation Requestが不正です。"
            )

        request_payload = (
            self._build_request_payload(
                request
            )
        )

        response_payload = self._post_chat(
            payload=request_payload
        )

        response_model = response_payload.get(
            "model"
        )

        if not isinstance(
            response_model,
            str,
        ):
            raise OllamaResponseError(
                "Ollama Responseに"
                "modelがありません。"
            )

        if not response_model.strip():
            raise OllamaResponseError(
                "Ollama Responseの"
                "modelが空です。"
            )

        message = response_payload.get(
            "message"
        )

        if not isinstance(message, dict):
            raise OllamaResponseError(
                "Ollama Responseの"
                "messageがObjectではありません。"
            )

        role = message.get("role")

        if role != "assistant":
            raise OllamaResponseError(
                "Ollama Responseの"
                "message.roleがassistantでは"
                "ありません。 "
                f"role={role!r}"
            )

        raw_text = message.get("content")

        if not isinstance(raw_text, str):
            raise OllamaResponseError(
                "Ollama Responseの"
                "message.contentが文字列では"
                "ありません。"
            )

        if not raw_text.strip():
            raise OllamaResponseError(
                "Ollama Responseの"
                "message.contentが空です。"
            )

        done = response_payload.get("done")

        if done is not True:
            raise OllamaResponseError(
                "Ollama Responseが完了状態では"
                "ありません。 "
                f"done={done!r}"
            )

        finish_reason = (
            response_payload.get(
                "done_reason"
            )
        )

        if not isinstance(
            finish_reason,
            str,
        ):
            finish_reason = "unknown"

        metadata = {
            "adapter_version":
                OLLAMA_ADAPTER_VERSION,
            "base_url":
                self._config.base_url,
            "requested_model":
                self._config.model,
            "response_model":
                response_model,
            "created_at":
                response_payload.get(
                    "created_at"
                ),
            "done":
                done,
            "done_reason":
                response_payload.get(
                    "done_reason"
                ),
            "total_duration":
                response_payload.get(
                    "total_duration"
                ),
            "load_duration":
                response_payload.get(
                    "load_duration"
                ),
            "prompt_eval_count":
                response_payload.get(
                    "prompt_eval_count"
                ),
            "prompt_eval_duration":
                response_payload.get(
                    "prompt_eval_duration"
                ),
            "eval_count":
                response_payload.get(
                    "eval_count"
                ),
            "eval_duration":
                response_payload.get(
                    "eval_duration"
                ),
            "temperature":
                self._config.temperature,
            "think":
                self._config.think,
            "num_predict":
                self._config.num_predict,
            "num_ctx":
                self._config.num_ctx,
            "keep_alive":
                self._config.keep_alive,
            "timeout_seconds":
                self._config.timeout_seconds,
        }

        return LLMGenerationResponse(
            provider=self.provider,
            model=response_model,
            raw_text=raw_text,
            finish_reason=finish_reason,
            input_sha256=(
                calculate_generation_input_sha256(
                    request
                )
            ),
            response_sha256=(
                calculate_generation_response_sha256(
                    raw_text
                )
            ),
            metadata=metadata,
        )
