from __future__ import annotations

import hashlib
import json
from typing import Any

from app.code_generation.contract import (
    CodeGenerationContract,
    CodeGenerationContractError,
)
from app.code_generation.context_validator import (
    CodeGenerationContextValidationError,
    validate_payload_against_context,
)
from app.missions.models import (
    MissionPatchEdit,
    MissionPatchGenerateRequest,
)


PATCH_REQUEST_CONVERTER_VERSION = (
    "mission-code-generation-patch-request-converter-v0.1"
)

DEFAULT_GENERATED_BY = (
    "code-generation-patch-converter-v0.1"
)


class CodeGenerationPatchConversionError(Exception):
    """ContractからPatch Requestへの変換失敗。"""


def _canonical_json_sha256(
    value: dict[str, Any],
) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()


def _build_patch_edit(
    *,
    edit: Any,
) -> MissionPatchEdit:
    operation = edit.operation

    common: dict[str, Any] = {
        "operation": operation,
        "path": edit.path,
    }

    if operation == "REPLACE_UNIQUE":
        common["old_text"] = edit.old_text
        common["new_text"] = edit.new_text

    elif operation == "APPEND":
        common["text"] = edit.text

    elif operation in {
        "INSERT_BEFORE",
        "INSERT_AFTER",
    }:
        common["anchor"] = edit.anchor
        common["text"] = edit.text

    else:
        raise CodeGenerationPatchConversionError(
            f"未対応の編集操作です: {operation}"
        )

    try:
        return MissionPatchEdit.model_validate(
            common
        )
    except Exception as error:
        raise CodeGenerationPatchConversionError(
            "MissionPatchEditへの変換に"
            f"失敗しました: {error}"
        ) from error


def _build_note(
    *,
    contract: CodeGenerationContract,
    contract_sha256: str,
) -> str:
    note = (
        f"summary: {contract.summary}\n"
        f"reasoning: {contract.reasoning}\n"
        f"context_sha256: "
        f"{contract.context_sha256}\n"
        f"contract_sha256: "
        f"{contract_sha256}\n"
        f"converter_version: "
        f"{PATCH_REQUEST_CONVERTER_VERSION}"
    )

    if len(note) > 3000:
        raise CodeGenerationPatchConversionError(
            "Patch Requestのnoteが"
            "上限3000文字を超えています。"
        )

    return note


def build_patch_generate_request(
    *,
    contract: CodeGenerationContract,
    generated_by: str = DEFAULT_GENERATED_BY,
) -> MissionPatchGenerateRequest:
    """検証済みContractをPatch Requestへ変換する。"""

    if not generated_by.strip():
        raise CodeGenerationPatchConversionError(
            "generated_byは空にできません。"
        )

    contract_payload = contract.model_dump(
        mode="json"
    )

    contract_sha256 = _canonical_json_sha256(
        contract_payload
    )

    patch_edits = [
        _build_patch_edit(edit=edit)
        for edit in contract.edits
    ]

    note = _build_note(
        contract=contract,
        contract_sha256=contract_sha256,
    )

    try:
        return MissionPatchGenerateRequest(
            edits=patch_edits,
            generated_by=generated_by,
            note=note,
        )
    except Exception as error:
        raise CodeGenerationPatchConversionError(
            "MissionPatchGenerateRequestの"
            f"生成に失敗しました: {error}"
        ) from error


def convert_contract_to_patch_request(
    *,
    payload: dict[str, Any],
    context: dict[str, Any],
    generated_by: str = DEFAULT_GENERATED_BY,
) -> dict[str, Any]:
    """
    Raw Contractを検証し、MissionPatchGenerateRequestへ変換する。
    """

    if not isinstance(payload, dict):
        raise CodeGenerationPatchConversionError(
            "Code Generation Contractは"
            "JSON Objectである必要があります。"
        )

    if not isinstance(context, dict):
        raise CodeGenerationPatchConversionError(
            "Code ContextはJSON Objectで"
            "ある必要があります。"
        )

    validation = validate_payload_against_context(
        payload=payload,
        context=context,
    )

    if not validation.get("valid"):
        raise CodeGenerationPatchConversionError(
            "Mission Context Validationが"
            "成功していません。"
        )

    try:
        contract = CodeGenerationContract.model_validate(
            payload
        )
    except Exception as error:
        raise CodeGenerationPatchConversionError(
            "Code Generation Contractの"
            f"復元に失敗しました: {error}"
        ) from error

    request = build_patch_generate_request(
        contract=contract,
        generated_by=generated_by,
    )

    contract_payload = contract.model_dump(
        mode="json"
    )

    contract_sha256 = _canonical_json_sha256(
        contract_payload
    )

    request_payload = request.model_dump(
        mode="json"
    )

    request_sha256 = _canonical_json_sha256(
        request_payload
    )

    changed_files = sorted(
        {
            edit.path
            for edit in contract.edits
        }
    )

    return {
        "converter_version": (
            PATCH_REQUEST_CONVERTER_VERSION
        ),
        "converted": True,
        "mission_id": contract.mission_id,
        "context_sha256": (
            contract.context_sha256
        ),
        "contract_sha256": contract_sha256,
        "patch_request_sha256": request_sha256,
        "edit_count": len(contract.edits),
        "changed_file_count": len(
            changed_files
        ),
        "changed_files": changed_files,
        "generated_by": generated_by,
        "patch_request": request,
        "patch_request_payload": (
            request_payload
        ),
        "validation": validation,
        "next_stage": "PATCH_GENERATION",
    }


def convert_contract_to_patch_request_safe(
    *,
    payload: dict[str, Any],
    context: dict[str, Any],
    generated_by: str = DEFAULT_GENERATED_BY,
) -> dict[str, Any]:
    """例外を投げず変換結果を返す。"""

    try:
        return convert_contract_to_patch_request(
            payload=payload,
            context=context,
            generated_by=generated_by,
        )
    except (
        CodeGenerationContractError,
        CodeGenerationContextValidationError,
        CodeGenerationPatchConversionError,
    ) as error:
        return {
            "converter_version": (
                PATCH_REQUEST_CONVERTER_VERSION
            ),
            "converted": False,
            "error": str(error),
            "next_stage": "BLOCKED",
        }
    except Exception as error:
        return {
            "converter_version": (
                PATCH_REQUEST_CONVERTER_VERSION
            ),
            "converted": False,
            "error": (
                "予期しないPatch Request変換エラー: "
                f"{error}"
            ),
            "next_stage": "BLOCKED",
        }
