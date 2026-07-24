from __future__ import annotations

import pytest

from app.code_generation import (
    CODE_GENERATION_CONTRACT_VERSION,
    CodeGenerationContextValidationError,
    validate_contract_against_context_safe,
    validate_payload_against_context,
)


CONTEXT_SHA256 = "b" * 64


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
        "summary": "認証処理を修正する。",
        "reasoning": (
            "既存関数を一意に置換する。"
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


def test_valid_replace_against_context() -> None:
    result = validate_payload_against_context(
        payload=contract_payload(),
        context=context_payload(),
    )

    assert result["valid"] is True
    assert result["edit_count"] == 1
    assert result["check_count"] == 1
    assert result["next_stage"] == (
        "PATCH_CONVERSION"
    )

    assert (
        result["checks"][0]["occurrence_count"]
        == 1
    )


def test_rejects_mission_id_mismatch() -> None:
    payload = contract_payload()
    payload["mission_id"] = 2

    result = (
        validate_contract_against_context_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["valid"] is False
    assert result["next_stage"] == "BLOCKED"
    assert "Mission ID" in result["error"]


def test_rejects_context_hash_mismatch() -> None:
    payload = contract_payload()
    payload["context_sha256"] = "c" * 64

    result = (
        validate_contract_against_context_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["valid"] is False
    assert "SHA-256" in result["error"]


def test_rejects_path_outside_context() -> None:
    payload = contract_payload()

    payload["edits"][0]["path"] = (
        "backend/app/unknown.py"
    )

    result = (
        validate_contract_against_context_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["valid"] is False
    assert "Code Context内" in result["error"]


def test_rejects_missing_old_text() -> None:
    payload = contract_payload()

    payload["edits"][0]["old_text"] = (
        "def missing():\n"
    )

    result = (
        validate_contract_against_context_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["valid"] is False
    assert "見つかりません" in result["error"]


def test_rejects_duplicate_old_text() -> None:
    context = context_payload()

    context["files"][0]["content"] = (
        "def current_user():\n"
        "    pass\n"
        "\n"
        "def current_user():\n"
        "    pass\n"
    )

    result = (
        validate_contract_against_context_safe(
            payload=contract_payload(),
            context=context,
        )
    )

    assert result["valid"] is False
    assert "一意ではありません" in result["error"]


@pytest.mark.parametrize(
    "operation",
    [
        "INSERT_BEFORE",
        "INSERT_AFTER",
    ],
)
def test_valid_insert_anchor(
    operation: str,
) -> None:
    payload = contract_payload()

    payload["edits"] = [
        {
            "operation": operation,
            "path": "backend/app/api/auth.py",
            "anchor": "router = APIRouter()\n",
            "text": "# inserted\n",
        }
    ]

    result = validate_payload_against_context(
        payload=payload,
        context=context_payload(),
    )

    assert result["valid"] is True
    assert (
        result["checks"][0]["occurrence_count"]
        == 1
    )


def test_rejects_missing_anchor() -> None:
    payload = contract_payload()

    payload["edits"] = [
        {
            "operation": "INSERT_BEFORE",
            "path": "backend/app/api/auth.py",
            "anchor": "missing-anchor",
            "text": "# inserted\n",
        }
    ]

    result = (
        validate_contract_against_context_safe(
            payload=payload,
            context=context_payload(),
        )
    )

    assert result["valid"] is False
    assert "見つかりません" in result["error"]


def test_rejects_duplicate_anchor() -> None:
    context = context_payload()

    context["files"][0]["content"] = (
        "marker\n"
        "content\n"
        "marker\n"
    )

    payload = contract_payload()

    payload["edits"] = [
        {
            "operation": "INSERT_AFTER",
            "path": "backend/app/api/auth.py",
            "anchor": "marker",
            "text": "\ninserted",
        }
    ]

    result = (
        validate_contract_against_context_safe(
            payload=payload,
            context=context,
        )
    )

    assert result["valid"] is False
    assert "一意ではありません" in result["error"]


def test_valid_append_existing_file() -> None:
    payload = contract_payload()

    payload["edits"] = [
        {
            "operation": "APPEND",
            "path": (
                "frontend/src/app/page.tsx"
            ),
            "text": "\n// appended\n",
        }
    ]

    result = validate_payload_against_context(
        payload=payload,
        context=context_payload(),
    )

    assert result["valid"] is True
    assert (
        result["checks"][0]["match_type"]
        == "file_exists"
    )


def test_rejects_context_without_files() -> None:
    context = context_payload()
    del context["files"]

    result = (
        validate_contract_against_context_safe(
            payload=contract_payload(),
            context=context,
        )
    )

    assert result["valid"] is False


def test_rejects_duplicate_context_paths() -> None:
    context = context_payload()

    context["files"].append(
        dict(context["files"][0])
    )

    result = (
        validate_contract_against_context_safe(
            payload=contract_payload(),
            context=context,
        )
    )

    assert result["valid"] is False
    assert "重複" in result["error"]


def test_rejects_missing_source_content() -> None:
    context = context_payload()

    del context["files"][0]["content"]

    result = (
        validate_contract_against_context_safe(
            payload=contract_payload(),
            context=context,
        )
    )

    assert result["valid"] is False
    assert "ソース本文" in result["error"]


def test_multiple_edits_and_files() -> None:
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

    result = validate_payload_against_context(
        payload=payload,
        context=context_payload(),
    )

    assert result["valid"] is True
    assert result["edit_count"] == 2
    assert result["changed_file_count"] == 2
    assert result["check_count"] == 2


def test_non_dict_context_is_rejected() -> None:
    result = (
        validate_contract_against_context_safe(
            payload=contract_payload(),
            context=[],  # type: ignore[arg-type]
        )
    )

    assert result["valid"] is False
    assert result["next_stage"] == "BLOCKED"


def test_direct_validation_raises() -> None:
    payload = contract_payload()
    payload["context_sha256"] = "c" * 64

    with pytest.raises(
        CodeGenerationContextValidationError
    ):
        validate_payload_against_context(
            payload=payload,
            context=context_payload(),
        )


def test_nested_context_identity_is_supported() -> None:
    context = context_payload()

    context["mission"] = {
        "id": context.pop("mission_id")
    }

    context["metadata"] = {
        "context_sha256": context.pop("sha256")
    }

    result = validate_payload_against_context(
        payload=contract_payload(),
        context=context,
    )

    assert result["valid"] is True


def test_alternative_file_keys_are_supported() -> None:
    context = context_payload()

    first_file = context["files"][0]

    first_file["path"] = first_file.pop(
        "relative_path"
    )

    first_file["source"] = first_file.pop(
        "content"
    )

    result = validate_payload_against_context(
        payload=contract_payload(),
        context=context,
    )

    assert result["valid"] is True
