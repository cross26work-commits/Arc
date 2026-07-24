from __future__ import annotations

import pytest

from app.code_generation.contract import (
    CODE_GENERATION_CONTRACT_VERSION,
    CodeGenerationContractError,
    validate_code_generation_contract,
    validate_code_generation_contract_safe,
)


CONTEXT_SHA256 = "a" * 64


def valid_payload() -> dict:
    return {
        "contract_version": (
            CODE_GENERATION_CONTRACT_VERSION
        ),
        "mission_id": 1,
        "context_sha256": CONTEXT_SHA256,
        "summary": "認証処理を修正する。",
        "reasoning": (
            "既存コードとの互換性を維持しながら"
            "対象処理だけを変更する。"
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
        "generated_by": "test-provider",
        "assumptions": [],
        "warnings": [],
    }


def test_valid_replace_unique_contract() -> None:
    result = validate_code_generation_contract(
        valid_payload()
    )

    assert result["valid"] is True
    assert result["mission_id"] == 1
    assert result["edit_count"] == 1
    assert result["changed_file_count"] == 1

    assert result["changed_files"] == [
        "backend/app/api/auth.py"
    ]

    assert result["operation_counts"] == {
        "REPLACE_UNIQUE": 1
    }

    assert (
        len(result["contract_sha256"])
        == 64
    )

    assert (
        result["next_stage"]
        == "MISSION_CONTEXT_VALIDATION"
    )


@pytest.mark.parametrize(
    (
        "operation",
        "fields",
    ),
    [
        (
            "APPEND",
            {
                "text": "\n# appended\n",
            },
        ),
        (
            "INSERT_BEFORE",
            {
                "anchor": "def current_user",
                "text": "# inserted\n",
            },
        ),
        (
            "INSERT_AFTER",
            {
                "anchor": "def current_user",
                "text": "\n# inserted",
            },
        ),
    ],
)
def test_supported_operations(
    operation: str,
    fields: dict,
) -> None:
    payload = valid_payload()

    payload["edits"] = [
        {
            "operation": operation,
            "path": "backend/app/api/auth.py",
            **fields,
        }
    ]

    result = validate_code_generation_contract(
        payload
    )

    assert result["valid"] is True
    assert result["operation_counts"] == {
        operation: 1
    }


def test_rejects_missing_replace_text() -> None:
    payload = valid_payload()

    payload["edits"] = [
        {
            "operation": "REPLACE_UNIQUE",
            "path": "backend/app/api/auth.py",
            "new_text": "replacement",
        }
    ]

    with pytest.raises(
        CodeGenerationContractError
    ):
        validate_code_generation_contract(
            payload
        )


def test_rejects_same_old_and_new_text() -> None:
    payload = valid_payload()

    payload["edits"] = [
        {
            "operation": "REPLACE_UNIQUE",
            "path": "backend/app/api/auth.py",
            "old_text": "same",
            "new_text": "same",
        }
    ]

    result = (
        validate_code_generation_contract_safe(
            payload
        )
    )

    assert result["valid"] is False
    assert result["next_stage"] == "BLOCKED"


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../outside.py",
        "backend/../../outside.py",
        ".",
        "   ",
    ],
)
def test_rejects_unsafe_paths(
    path: str,
) -> None:
    payload = valid_payload()
    payload["edits"][0]["path"] = path

    result = (
        validate_code_generation_contract_safe(
            payload
        )
    )

    assert result["valid"] is False
    assert result["next_stage"] == "BLOCKED"


def test_normalizes_windows_path() -> None:
    payload = valid_payload()

    payload["edits"][0]["path"] = (
        "backend\\app\\api\\auth.py"
    )

    result = validate_code_generation_contract(
        payload
    )

    assert result["changed_files"] == [
        "backend/app/api/auth.py"
    ]


def test_rejects_unknown_field() -> None:
    payload = valid_payload()
    payload["unexpected"] = True

    result = (
        validate_code_generation_contract_safe(
            payload
        )
    )

    assert result["valid"] is False


def test_rejects_unknown_edit_field() -> None:
    payload = valid_payload()

    payload["edits"][0][
        "unexpected"
    ] = True

    result = (
        validate_code_generation_contract_safe(
            payload
        )
    )

    assert result["valid"] is False


def test_rejects_duplicate_edits() -> None:
    payload = valid_payload()

    payload["edits"].append(
        dict(payload["edits"][0])
    )

    result = (
        validate_code_generation_contract_safe(
            payload
        )
    )

    assert result["valid"] is False


def test_contract_hash_is_deterministic() -> None:
    payload = valid_payload()

    first = validate_code_generation_contract(
        payload
    )

    second = validate_code_generation_contract(
        payload
    )

    assert (
        first["contract_sha256"]
        == second["contract_sha256"]
    )


def test_contract_hash_changes_with_content() -> None:
    first_payload = valid_payload()
    second_payload = valid_payload()

    second_payload["summary"] = (
        "別の変更概要"
    )

    first = validate_code_generation_contract(
        first_payload
    )

    second = validate_code_generation_contract(
        second_payload
    )

    assert (
        first["contract_sha256"]
        != second["contract_sha256"]
    )


def test_safe_validator_rejects_non_dict() -> None:
    result = (
        validate_code_generation_contract_safe(
            ["invalid"]  # type: ignore[arg-type]
        )
    )

    assert result["valid"] is False
    assert result["next_stage"] == "BLOCKED"


def test_multiple_files_summary() -> None:
    payload = valid_payload()

    payload["edits"].append(
        {
            "operation": "APPEND",
            "path": (
                "frontend/src/app/page.tsx"
            ),
            "text": "\n// generated\n",
        }
    )

    result = validate_code_generation_contract(
        payload
    )

    assert result["edit_count"] == 2
    assert result["changed_file_count"] == 2

    assert result["changed_files"] == [
        "backend/app/api/auth.py",
        "frontend/src/app/page.tsx",
    ]
