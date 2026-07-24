from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


CODE_GENERATION_CONTRACT_VERSION = (
    "mission-code-generation-contract-v0.1"
)

SUPPORTED_OPERATIONS = {
    "REPLACE_UNIQUE",
    "APPEND",
    "INSERT_BEFORE",
    "INSERT_AFTER",
}

MAX_EDIT_COUNT = 100
MAX_TEXT_LENGTH = 100_000
MAX_PATH_LENGTH = 1_000


class CodeGenerationContractError(Exception):
    """Code Generation Contract検証失敗時の例外。"""


class CodeGenerationEdit(BaseModel):
    """AIが提案する単一ファイル編集。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
    )

    operation: Literal[
        "REPLACE_UNIQUE",
        "APPEND",
        "INSERT_BEFORE",
        "INSERT_AFTER",
    ]

    path: str = Field(
        min_length=1,
        max_length=MAX_PATH_LENGTH,
    )

    old_text: str | None = Field(
        default=None,
        max_length=MAX_TEXT_LENGTH,
    )

    new_text: str | None = Field(
        default=None,
        max_length=MAX_TEXT_LENGTH,
    )

    anchor: str | None = Field(
        default=None,
        max_length=MAX_TEXT_LENGTH,
    )

    text: str | None = Field(
        default=None,
        max_length=MAX_TEXT_LENGTH,
    )

    @field_validator("path")
    @classmethod
    def validate_path(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().replace(
            "\\",
            "/",
        )

        if not normalized:
            raise ValueError(
                "pathは空にできません。"
            )

        if normalized.startswith("/"):
            raise ValueError(
                "絶対Pathは使用できません。"
            )

        path = PurePosixPath(normalized)

        if ".." in path.parts:
            raise ValueError(
                "親Directory参照は使用できません。"
            )

        if "." == normalized:
            raise ValueError(
                "ファイルPathを指定してください。"
            )

        return path.as_posix()

    @model_validator(mode="after")
    def validate_operation_fields(
        self,
    ) -> "CodeGenerationEdit":
        operation = self.operation

        if operation == "REPLACE_UNIQUE":
            if self.old_text is None:
                raise ValueError(
                    "REPLACE_UNIQUEでは"
                    "old_textが必須です。"
                )

            if self.old_text == "":
                raise ValueError(
                    "old_textは空にできません。"
                )

            if self.new_text is None:
                raise ValueError(
                    "REPLACE_UNIQUEでは"
                    "new_textが必須です。"
                )

            if self.anchor is not None:
                raise ValueError(
                    "REPLACE_UNIQUEでは"
                    "anchorを指定できません。"
                )

            if self.text is not None:
                raise ValueError(
                    "REPLACE_UNIQUEでは"
                    "textを指定できません。"
                )

            if self.old_text == self.new_text:
                raise ValueError(
                    "変更前と変更後が同一です。"
                )

            return self

        if operation == "APPEND":
            if self.text is None:
                raise ValueError(
                    "APPENDではtextが必須です。"
                )

            if self.text == "":
                raise ValueError(
                    "textは空にできません。"
                )

            if self.old_text is not None:
                raise ValueError(
                    "APPENDではold_textを"
                    "指定できません。"
                )

            if self.new_text is not None:
                raise ValueError(
                    "APPENDではnew_textを"
                    "指定できません。"
                )

            if self.anchor is not None:
                raise ValueError(
                    "APPENDではanchorを"
                    "指定できません。"
                )

            return self

        if operation in {
            "INSERT_BEFORE",
            "INSERT_AFTER",
        }:
            if self.anchor is None:
                raise ValueError(
                    f"{operation}では"
                    "anchorが必須です。"
                )

            if self.anchor == "":
                raise ValueError(
                    "anchorは空にできません。"
                )

            if self.text is None:
                raise ValueError(
                    f"{operation}では"
                    "textが必須です。"
                )

            if self.text == "":
                raise ValueError(
                    "textは空にできません。"
                )

            if self.old_text is not None:
                raise ValueError(
                    f"{operation}では"
                    "old_textを指定できません。"
                )

            if self.new_text is not None:
                raise ValueError(
                    f"{operation}では"
                    "new_textを指定できません。"
                )

            return self

        raise ValueError(
            f"未対応の編集操作です: {operation}"
        )


class CodeGenerationContract(BaseModel):
    """AIコード変更案の正式Contract。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    contract_version: Literal[
        "mission-code-generation-contract-v0.1"
    ] = CODE_GENERATION_CONTRACT_VERSION

    mission_id: int = Field(
        ge=1,
    )

    context_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )

    summary: str = Field(
        min_length=1,
        max_length=3_000,
    )

    reasoning: str = Field(
        min_length=1,
        max_length=10_000,
    )

    edits: list[CodeGenerationEdit] = Field(
        min_length=1,
        max_length=MAX_EDIT_COUNT,
    )

    generated_by: str = Field(
        default="code-generation",
        min_length=1,
        max_length=200,
    )

    assumptions: list[str] = Field(
        default_factory=list,
        max_length=50,
    )

    warnings: list[str] = Field(
        default_factory=list,
        max_length=50,
    )

    @field_validator(
        "assumptions",
        "warnings",
    )
    @classmethod
    def validate_text_list(
        cls,
        values: list[str],
    ) -> list[str]:
        normalized: list[str] = []

        for index, value in enumerate(
            values,
            start=1,
        ):
            item = value.strip()

            if not item:
                raise ValueError(
                    f"項目{index}が空です。"
                )

            if len(item) > 2_000:
                raise ValueError(
                    f"項目{index}が長すぎます。"
                )

            normalized.append(item)

        return normalized

    @model_validator(mode="after")
    def validate_edit_duplicates(
        self,
    ) -> "CodeGenerationContract":
        signatures: set[str] = set()

        for edit in self.edits:
            canonical = json.dumps(
                edit.model_dump(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

            signature = hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest()

            if signature in signatures:
                raise ValueError(
                    "完全に同一の編集指示が"
                    "重複しています。"
                )

            signatures.add(signature)

        return self


def _canonical_payload(
    contract: CodeGenerationContract,
) -> dict[str, Any]:
    return contract.model_dump(
        mode="json",
    )


def _sha256_payload(
    payload: dict[str, Any],
) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def validate_code_generation_contract(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Contractを検証し、正規化結果を返す。"""

    if not isinstance(payload, dict):
        raise CodeGenerationContractError(
            "Code Generation出力は"
            "JSON Objectである必要があります。"
        )

    try:
        contract = (
            CodeGenerationContract.model_validate(
                payload
            )
        )
    except ValidationError as error:
        raise CodeGenerationContractError(
            "Code Generation Contractの"
            f"検証に失敗しました: {error}"
        ) from error

    normalized = _canonical_payload(
        contract
    )

    paths = sorted(
        {
            edit["path"]
            for edit in normalized["edits"]
        }
    )

    operations: dict[str, int] = {}

    for edit in normalized["edits"]:
        operation = edit["operation"]

        operations[operation] = (
            operations.get(operation, 0)
            + 1
        )

    return {
        "contract_version": (
            CODE_GENERATION_CONTRACT_VERSION
        ),
        "valid": True,
        "mission_id": contract.mission_id,
        "context_sha256": (
            contract.context_sha256
        ),
        "contract_sha256": (
            _sha256_payload(normalized)
        ),
        "edit_count": len(
            contract.edits
        ),
        "changed_file_count": len(paths),
        "changed_files": paths,
        "operation_counts": operations,
        "normalized_contract": normalized,
        "next_stage": (
            "MISSION_CONTEXT_VALIDATION"
        ),
    }


def validate_code_generation_contract_safe(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """例外を投げずContract検証結果を返す。"""

    try:
        return validate_code_generation_contract(
            payload
        )
    except CodeGenerationContractError as error:
        return {
            "contract_version": (
                CODE_GENERATION_CONTRACT_VERSION
            ),
            "valid": False,
            "error": str(error),
            "next_stage": "BLOCKED",
        }
