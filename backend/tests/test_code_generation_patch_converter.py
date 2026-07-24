from __future__ import annotations

from copy import deepcopy

import pytest

from app.code_generation import (
    CODE_GENERATION_CONTRACT_VERSION,
    DEFAULT_GENERATED_BY,
    PATCH_REQUEST_CONVERTER_VERSION,
    CodeGenerationContract,
    CodeGenerationPatchConversionError,
    build_patch_generate_request,
    convert_contract_to_patch_request,
    convert_contract_to_patch_request_safe,
)
from app.missions.models import (
    MissionPatchGenerateRequest,
)


CONTEXT_SHA256 = "a" * 64


def context_payload() -> dict:
    return {
        "mission_id": 1,
        "sha256": CONTEXT_SHA256,
        "files": [
            {
                "relative_path": (
                    "backend/app/api/auth.py"
                ),
                "content": (
                    "from fastapi import APIRouter\n"
                    "\n"
                    "router = APIRouter()\n"
                    "\n"
                    "def current_user():\n"
                    "    return {'id': 1}\n"
                ),
            },
            {
                "relative_path": (
                    "frontend/src/app/page.tsx"
                ),
                "content": (
                    "export default function Page() {\n"
                    "  return <main>Hello</main>;\n"
                    "}\n"
                ),
            },
        ],
    }


def contract_payload() -> dict:
    return {
        "contract_version": (
            CODE_GENERATION_CONTRACT_VERSION
        ),
        "mission_id": 1,
        "context_sha256": CONTEXT_SHA256,
        "summary": "認証関数を修正する。",
        "reasoning": (
            "型情報を追加して安全性を高める。"
        ),
        "edits": [
            {
                "operation": "REPLACE_UNIQUE",
                "path": "backend/app/api/auth.py",
                "old_text": (
                    "def current_user():\n"
                ),
                "new_text": (
                    "def current_user() -> dict:\n"
                ),
            }
        ],
    }


def test_build_patch_generate_request() -> None:
    contract = CodeGenerationContract.model_validate(
        contract_payload()
    )

    request = build_patch_generate_request(
        contract=contract
    )

    assert isinstance(
        request,
        MissionPatchGenerateRequest,
    )
    assert request.generated_by == (
        DEFAULT_GENERATED_BY
    )
    assert len(request.edits) == 1
    assert request.edits[0].operation == (
        "REPLACE_UNIQUE"
    )
    assert request.edits[0].old_text == (
        "def current_user():\n"
    )
    assert request.edits[0].new_text == (
        "def current_user() -> dict:\n"
    )
    assert "context_sha256" in (
        request.note or ""
    )
    assert "contract_sha256" in (
        request.note or ""
    )


def test_convert_valid_contract() -> None:
    result = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
    )

    assert result["converted"] is True
    assert result["mission_id"] == 1
    assert result["edit_count"] == 1
    assert result["changed_file_count"] == 1
    assert result["changed_files"] == [
        "backend/app/api/auth.py"
    ]
    assert len(result["contract_sha256"]) == 64
    assert (
        len(result["patch_request_sha256"])
        == 64
    )
    assert result["next_stage"] == (
        "PATCH_GENERATION"
    )

    request = result["patch_request"]

    assert isinstance(
        request,
        MissionPatchGenerateRequest,
    )


def test_patch_request_payload_is_serializable() -> None:
    result = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
    )

    payload = result["patch_request_payload"]

    assert isinstance(payload, dict)
    assert payload["generated_by"] == (
        DEFAULT_GENERATED_BY
    )
    assert payload["edits"][0]["operation"] == (
        "REPLACE_UNIQUE"
    )


@pytest.mark.parametrize(
    "operation,fields",
    [
        (
            "REPLACE_UNIQUE",
            {
                "old_text": (
                    "def current_user():\n"
                ),
                "new_text": (
                    "def current_user() -> dict:\n"
                ),
            },
        ),
        (
            "APPEND",
            {
                "text": "\n# appended\n",
            },
        ),
        (
            "INSERT_BEFORE",
            {
                "anchor": (
                    "router = APIRouter()\n"
                ),
                "text": "# inserted\n",
            },
        ),
        (
            "INSERT_AFTER",
            {
                "anchor": (
                    "router = APIRouter()\n"
                ),
                "text": "\n# inserted",
            },
        ),
    ],
)
def test_all_operations_are_converted(
    operation: str,
    fields: dict,
) -> None:
    payload = contract_payload()

    payload["edits"] = [
        {
            "operation": operation,
            "path": "backend/app/api/auth.py",
            **fields,
        }
    ]

    result = convert_contract_to_patch_request(
        payload=payload,
        context=context_payload(),
    )

    converted_edit = (
        result["patch_request"].edits[0]
    )

    assert converted_edit.operation == operation
    assert converted_edit.path == (
        "backend/app/api/auth.py"
    )

    for key, value in fields.items():
        assert getattr(
            converted_edit,
            key,
        ) == value


def test_multiple_files_are_preserved() -> None:
    payload = contract_payload()

    payload["edits"].append(
        {
            "operation": "APPEND",
            "path": (
                "frontend/src/app/page.tsx"
            ),
            "text": "\n// appended\n",
        }
    )

    result = convert_contract_to_patch_request(
        payload=payload,
        context=context_payload(),
    )

    assert result["edit_count"] == 2
    assert result["changed_file_count"] == 2
    assert result["changed_files"] == [
        "backend/app/api/auth.py",
        "frontend/src/app/page.tsx",
    ]


def test_custom_generated_by() -> None:
    result = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
        generated_by="arc-code-generator-v0.1",
    )

    assert result["generated_by"] == (
        "arc-code-generator-v0.1"
    )

    assert (
        result["patch_request"].generated_by
        == "arc-code-generator-v0.1"
    )


def test_contract_hash_is_deterministic() -> None:
    first = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
    )

    second = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
    )

    assert first["contract_sha256"] == (
        second["contract_sha256"]
    )

    assert first["patch_request_sha256"] == (
        second["patch_request_sha256"]
    )


def test_contract_change_changes_hash() -> None:
    first = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
    )

    changed = contract_payload()
    changed["summary"] = "変更後の要約"

    second = convert_contract_to_patch_request(
        payload=changed,
        context=context_payload(),
    )

    assert first["contract_sha256"] != (
        second["contract_sha256"]
    )


def test_context_validation_runs_first() -> None:
    payload = contract_payload()
    payload["context_sha256"] = "b" * 64

    result = (
        convert_contract_to_patch_request_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["converted"] is False
    assert result["next_stage"] == "BLOCKED"
    assert "SHA-256" in result["error"]


def test_path_outside_context_is_blocked() -> None:
    payload = contract_payload()

    payload["edits"][0]["path"] = (
        "backend/app/missing.py"
    )

    result = (
        convert_contract_to_patch_request_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["converted"] is False
    assert result["next_stage"] == "BLOCKED"
    assert "Code Context内" in result["error"]


def test_missing_old_text_is_blocked() -> None:
    payload = contract_payload()

    payload["edits"][0]["old_text"] = (
        "def missing():\n"
    )

    result = (
        convert_contract_to_patch_request_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["converted"] is False
    assert result["next_stage"] == "BLOCKED"
    assert "見つかりません" in result["error"]


def test_invalid_contract_is_blocked() -> None:
    payload = contract_payload()
    del payload["edits"]

    result = (
        convert_contract_to_patch_request_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["converted"] is False
    assert result["next_stage"] == "BLOCKED"


def test_non_dict_payload_is_blocked() -> None:
    result = (
        convert_contract_to_patch_request_safe(
            payload=[],  # type: ignore[arg-type]
            context=context_payload(),
        )
    )

    assert result["converted"] is False
    assert result["next_stage"] == "BLOCKED"


def test_non_dict_context_is_blocked() -> None:
    result = (
        convert_contract_to_patch_request_safe(
            payload=contract_payload(),
            context=[],  # type: ignore[arg-type]
        )
    )

    assert result["converted"] is False
    assert result["next_stage"] == "BLOCKED"


def test_blank_generated_by_is_rejected() -> None:
    contract = CodeGenerationContract.model_validate(
        contract_payload()
    )

    with pytest.raises(
        CodeGenerationPatchConversionError
    ):
        build_patch_generate_request(
            contract=contract,
            generated_by="   ",
        )


def test_converter_version() -> None:
    result = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
    )

    assert result["converter_version"] == (
        PATCH_REQUEST_CONVERTER_VERSION
    )


def test_input_payload_is_not_modified() -> None:
    payload = contract_payload()
    original = deepcopy(payload)

    convert_contract_to_patch_request(
        payload=payload,
        context=context_payload(),
    )

    assert payload == original


def test_result_validation_is_preserved() -> None:
    result = convert_contract_to_patch_request(
        payload=contract_payload(),
        context=context_payload(),
    )

    assert result["validation"]["valid"] is True
    assert result["validation"]["next_stage"] == (
        "PATCH_CONVERSION"
    )
