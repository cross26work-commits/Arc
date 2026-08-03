from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence


LLM_ADAPTER_VERSION = (
    "mission-code-generation-llm-adapter-v0.1"
)


class CodeGenerationLLMAdapterError(
    RuntimeError
):
    """Code Generation向けLLM Adapterの共通例外。"""


@dataclass(frozen=True)
class LLMGenerationRequest:
    mission_id: int
    system_prompt: str
    user_prompt: str
    context_sha256: str
    response_format: str | dict[str, Any] = "json"

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, int):
            raise CodeGenerationLLMAdapterError(
                "Mission IDは整数で指定してください。"
            )

        if self.mission_id <= 0:
            raise CodeGenerationLLMAdapterError(
                "Mission IDは1以上で指定してください。"
            )

        if not isinstance(
            self.system_prompt,
            str,
        ):
            raise CodeGenerationLLMAdapterError(
                "System Promptは文字列で"
                "指定してください。"
            )

        if not self.system_prompt.strip():
            raise CodeGenerationLLMAdapterError(
                "System Promptが空です。"
            )

        if not isinstance(
            self.user_prompt,
            str,
        ):
            raise CodeGenerationLLMAdapterError(
                "User Promptは文字列で"
                "指定してください。"
            )

        if not self.user_prompt.strip():
            raise CodeGenerationLLMAdapterError(
                "User Promptが空です。"
            )

        if not isinstance(
            self.context_sha256,
            str,
        ):
            raise CodeGenerationLLMAdapterError(
                "Context SHA256は文字列で"
                "指定してください。"
            )

        if len(self.context_sha256) != 64:
            raise CodeGenerationLLMAdapterError(
                "Context SHA256は64文字で"
                "指定してください。"
            )

        if not isinstance(
            self.response_format,
            (
                str,
                dict,
            ),
        ):
            raise CodeGenerationLLMAdapterError(
                "Response Formatは文字列またはJSON Objectで"
                "指定してください。"
            )

        if isinstance(
            self.response_format,
            str,
        ) and not self.response_format.strip():
            raise CodeGenerationLLMAdapterError(
                "Response Formatが空です。"
            )

        try:
            int(
                self.context_sha256,
                16,
            )
        except ValueError as exc:
            raise CodeGenerationLLMAdapterError(
                "Context SHA256は16進数で"
                "指定してください。"
            ) from exc


@dataclass(frozen=True)
class LLMGenerationResponse:
    provider: str
    model: str
    raw_text: str
    finish_reason: str
    input_sha256: str
    response_sha256: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str):
            raise CodeGenerationLLMAdapterError(
                "Providerは文字列で"
                "指定してください。"
            )

        if not self.provider.strip():
            raise CodeGenerationLLMAdapterError(
                "Providerが空です。"
            )

        if not isinstance(self.model, str):
            raise CodeGenerationLLMAdapterError(
                "Modelは文字列で"
                "指定してください。"
            )

        if not self.model.strip():
            raise CodeGenerationLLMAdapterError(
                "Modelが空です。"
            )

        if not isinstance(self.raw_text, str):
            raise CodeGenerationLLMAdapterError(
                "LLM応答は文字列で"
                "指定してください。"
            )

        if not self.raw_text.strip():
            raise CodeGenerationLLMAdapterError(
                "LLM応答が空です。"
            )

        if not isinstance(
            self.finish_reason,
            str,
        ):
            raise CodeGenerationLLMAdapterError(
                "Finish Reasonは文字列で"
                "指定してください。"
            )


class CodeGenerationLLMAdapter(
    ABC
):
    @property
    @abstractmethod
    def provider(self) -> str:
        """Adapterが接続するProvider名。"""

    @property
    @abstractmethod
    def model(self) -> str:
        """Adapterが利用するModel名。"""

    @abstractmethod
    def generate(
        self,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        """LLMからCode Generation候補を生成する。"""


def calculate_generation_input_sha256(
    request: LLMGenerationRequest,
) -> str:
    canonical_payload = {
        "mission_id": request.mission_id,
        "system_prompt": (
            request.system_prompt
        ),
        "user_prompt": request.user_prompt,
        "context_sha256": (
            request.context_sha256
        ),
        "response_format": request.response_format,
    }

    encoded = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return sha256(encoded).hexdigest()


def calculate_generation_response_sha256(
    raw_text: str,
) -> str:
    if not isinstance(raw_text, str):
        raise CodeGenerationLLMAdapterError(
            "LLM応答は文字列で"
            "指定してください。"
        )

    return sha256(
        raw_text.encode("utf-8")
    ).hexdigest()


def extract_json_object(
    raw_text: str,
) -> dict[str, Any]:
    if not isinstance(raw_text, str):
        raise CodeGenerationLLMAdapterError(
            "LLM応答は文字列で"
            "指定してください。"
        )

    stripped = raw_text.strip()

    if not stripped:
        raise CodeGenerationLLMAdapterError(
            "LLM応答が空です。"
        )

    candidates: list[str] = [stripped]

    if "```" in stripped:
        fence_parts = stripped.split("```")

        for index in range(
            1,
            len(fence_parts),
            2,
        ):
            candidate = fence_parts[
                index
            ].strip()

            if candidate.startswith("json"):
                candidate = candidate[
                    len("json"):
                ].lstrip()

            if candidate:
                candidates.append(candidate)

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")

    if (
        first_brace >= 0
        and last_brace > first_brace
    ):
        candidates.append(
            stripped[
                first_brace:
                last_brace + 1
            ]
        )

    errors: list[str] = []

    for candidate in _deduplicate(
        candidates
    ):
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue

        if not isinstance(decoded, dict):
            errors.append(
                "JSONルートがObjectではありません。"
            )
            continue

        return decoded

    detail = (
        errors[-1]
        if errors
        else "JSON候補がありません。"
    )

    raise CodeGenerationLLMAdapterError(
        "LLM応答からJSON Objectを"
        f"抽出できません。 detail={detail}"
    )


def _deduplicate(
    values: Sequence[str],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value in seen:
            continue

        seen.add(value)
        result.append(value)

    return result


class DeterministicCodeGenerationLLMAdapter(
    CodeGenerationLLMAdapter
):
    """
    外部通信を行わないテスト用Adapter。

    Phase30-3AではLLM接続前に、
    入出力契約・ハッシュ・JSON抽出を
    安定させるために使用する。
    """

    def __init__(
        self,
        *,
        response_payload: Mapping[str, Any],
        provider: str = "deterministic",
        model: str = "contract-fixture-v0.1",
    ) -> None:
        if not isinstance(
            response_payload,
            Mapping,
        ):
            raise CodeGenerationLLMAdapterError(
                "Response PayloadはMappingで"
                "指定してください。"
            )

        if not isinstance(provider, str):
            raise CodeGenerationLLMAdapterError(
                "Providerは文字列で"
                "指定してください。"
            )

        if not provider.strip():
            raise CodeGenerationLLMAdapterError(
                "Providerが空です。"
            )

        if not isinstance(model, str):
            raise CodeGenerationLLMAdapterError(
                "Modelは文字列で"
                "指定してください。"
            )

        if not model.strip():
            raise CodeGenerationLLMAdapterError(
                "Modelが空です。"
            )

        self._response_payload = dict(
            response_payload
        )
        self._provider = provider
        self._model = model

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def generate(
        self,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        if not isinstance(
            request,
            LLMGenerationRequest,
        ):
            raise CodeGenerationLLMAdapterError(
                "Generation Requestが不正です。"
            )

        raw_text = json.dumps(
            self._response_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        return LLMGenerationResponse(
            provider=self.provider,
            model=self.model,
            raw_text=raw_text,
            finish_reason="stop",
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
            metadata={
                "adapter_version":
                    LLM_ADAPTER_VERSION,
                "network_used": False,
                "deterministic": True,
            },
        )
