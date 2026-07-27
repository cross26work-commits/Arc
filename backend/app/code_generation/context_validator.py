from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.code_generation.contract import (
    CodeGenerationContract,
    CodeGenerationContractError,
)


CONTEXT_VALIDATOR_VERSION = (
    "mission-code-generation-context-validator-v0.1"
)


class CodeGenerationContextValidationError(Exception):
    """Mission Code Contextとの整合性検証失敗。"""


def _extract_context_mission_id(
    context: dict[str, Any],
) -> int | None:
    value = context.get("mission_id")

    if isinstance(value, int):
        return value

    mission = context.get("mission")

    if isinstance(mission, dict):
        nested_value = mission.get("id")

        if isinstance(nested_value, int):
            return nested_value

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


def _extract_context_files(
    context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    files = context.get("files")

    if not isinstance(files, list):
        raise CodeGenerationContextValidationError(
            "Code ContextのfilesがListではありません。"
        )

    result: dict[str, dict[str, Any]] = {}

    for index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            raise CodeGenerationContextValidationError(
                f"Code Context files[{index}]が"
                "Objectではありません。"
            )

        path: str | None = None

        for key in (
            "relative_path",
            "path",
            "file_path",
        ):
            value = item.get(key)

            if isinstance(value, str) and value:
                path = value.replace("\\", "/")
                break

        if path is None:
            raise CodeGenerationContextValidationError(
                f"Code Context files[{index}]に"
                "ファイルPathがありません。"
            )

        if path in result:
            raise CodeGenerationContextValidationError(
                "Code Context内でPathが重複しています:"
                f" {path}"
            )

        result[path] = item

    return result


def _extract_source(
    *,
    path: str,
    file_context: dict[str, Any],
) -> str:
    for key in (
        "content",
        "source",
        "text",
        "file_content",
    ):
        value = file_context.get(key)

        if isinstance(value, str):
            return value

        if (
            key == "source"
            and isinstance(value, dict)
        ):
            nested_content = value.get("content")

            if isinstance(nested_content, str):
                return nested_content

    raise CodeGenerationContextValidationError(
        "Code Contextにソース本文がありません:"
        f" {path}"
    )


def _validate_context_identity(
    *,
    contract: CodeGenerationContract,
    context: dict[str, Any],
) -> None:
    context_mission_id = _extract_context_mission_id(
        context
    )

    if context_mission_id is None:
        raise CodeGenerationContextValidationError(
            "Code Contextにmission_idがありません。"
        )

    if context_mission_id != contract.mission_id:
        raise CodeGenerationContextValidationError(
            "Mission IDが一致しません。"
            f" contract={contract.mission_id}"
            f" context={context_mission_id}"
        )

    context_sha256 = _extract_context_sha256(
        context
    )

    if context_sha256 is None:
        raise CodeGenerationContextValidationError(
            "Code ContextにSHA-256がありません。"
        )

    if context_sha256 != contract.context_sha256:
        raise CodeGenerationContextValidationError(
            "Context SHA-256が一致しません。"
            f" contract={contract.context_sha256}"
            f" context={context_sha256}"
        )


def validate_contract_against_context(
    *,
    contract: CodeGenerationContract,
    context: dict[str, Any],
) -> dict[str, Any]:
    """ContractをMission Code Contextと照合する。"""

    if not isinstance(context, dict):
        raise CodeGenerationContextValidationError(
            "Code ContextはJSON Objectで"
            "ある必要があります。"
        )

    _validate_context_identity(
        contract=contract,
        context=context,
    )

    context_files = _extract_context_files(context)

    checks: list[dict[str, Any]] = []
    changed_files: set[str] = set()

    for index, edit in enumerate(
        contract.edits,
        start=1,
    ):
        path = edit.path
        changed_files.add(path)

        file_context = context_files.get(path)

        if file_context is None:
            raise CodeGenerationContextValidationError(
                "編集対象PathがCode Context内に"
                f"ありません: {path}"
            )

        source = _extract_source(
            path=path,
            file_context=file_context,
        )

        check: dict[str, Any] = {
            "edit_index": index,
            "operation": edit.operation,
            "path": path,
            "source_length": len(source),
            "passed": True,
        }

        if edit.operation == "REPLACE_UNIQUE":
            assert edit.old_text is not None

            occurrence_count = source.count(
                edit.old_text
            )

            check["match_type"] = "old_text"
            check["occurrence_count"] = (
                occurrence_count
            )

            if occurrence_count == 0:
                raise CodeGenerationContextValidationError(
                    "REPLACE_UNIQUEのold_textが"
                    f"見つかりません: {path}"
                )

            if occurrence_count > 1:
                raise CodeGenerationContextValidationError(
                    "REPLACE_UNIQUEのold_textが"
                    "一意ではありません:"
                    f" {path}"
                    f" count={occurrence_count}"
                )

        elif edit.operation in {
            "INSERT_BEFORE",
            "INSERT_AFTER",
        }:
            assert edit.anchor is not None

            occurrence_count = source.count(
                edit.anchor
            )

            check["match_type"] = "anchor"
            check["occurrence_count"] = (
                occurrence_count
            )

            if occurrence_count == 0:
                raise CodeGenerationContextValidationError(
                    f"{edit.operation}のanchorが"
                    f"見つかりません: {path}"
                )

            if occurrence_count > 1:
                raise CodeGenerationContextValidationError(
                    f"{edit.operation}のanchorが"
                    "一意ではありません:"
                    f" {path}"
                    f" count={occurrence_count}"
                )

        elif edit.operation == "APPEND":
            check["match_type"] = "file_exists"
            check["occurrence_count"] = 1

        checks.append(check)

    return {
        "validator_version": (
            CONTEXT_VALIDATOR_VERSION
        ),
        "valid": True,
        "mission_id": contract.mission_id,
        "context_sha256": (
            contract.context_sha256
        ),
        "edit_count": len(contract.edits),
        "changed_file_count": len(
            changed_files
        ),
        "changed_files": sorted(
            changed_files
        ),
        "check_count": len(checks),
        "checks": checks,
        "next_stage": "PATCH_CONVERSION",
    }


def validate_payload_against_context(
    *,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Raw Contract Payloadを検証後、Contextと照合する。"""

    if not isinstance(payload, dict):
        raise CodeGenerationContractError(
            "Code Generation出力はJSON Objectで"
            "ある必要があります。"
        )

    try:
        contract = CodeGenerationContract.model_validate(
            payload
        )
    except ValidationError as error:
        raise CodeGenerationContractError(
            "Code Generation Contractの"
            f"検証に失敗しました: {error}"
        ) from error

    return validate_contract_against_context(
        contract=contract,
        context=context,
    )


def validate_contract_against_context_safe(
    *,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """例外を投げずContext照合結果を返す。"""

    try:
        return validate_payload_against_context(
            payload=payload,
            context=context,
        )
    except (
        CodeGenerationContractError,
        CodeGenerationContextValidationError,
    ) as error:
        return {
            "validator_version": (
                CONTEXT_VALIDATOR_VERSION
            ),
            "valid": False,
            "error": str(error),
            "next_stage": "BLOCKED",
        }
