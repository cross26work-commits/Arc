from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.repair_context_builder import (
    ARC_ROOT,
    REPAIR_CONTEXT_VERSION,
    REPAIR_PLAN_ROOT,
    _load_json_if_exists,
    _normalize_relative_path,
    _relative_to_arc,
    _safe_source_path,
)
from app.missions.repair_request_builder import (
    _write_json_atomic,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairEditGeneratorError(Exception):
    """Repair Edit生成失敗時の例外。"""


REPAIR_EDIT_GENERATOR_VERSION = (
    "mission-repair-edit-generator-v0.1"
)

REPAIR_EDIT_SCHEMA_VERSION = (
    "repair-edit-draft-v0.1"
)

ALLOWED_CONTEXT_STATUSES = {
    "AWAITING_REPAIR_REQUEST",
    "REPAIR_FAILED",
}

MAX_GENERATED_EDITS = 3
MAX_TEXT_BYTES = 100_000

SUPPORTED_OPERATIONS = {
    "REPLACE_UNIQUE",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_json(
    value: dict[str, Any],
) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def _mission_directory(
    mission_id: int,
) -> Path:
    return (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
    )


def _load_repair_context(
    mission_id: int,
) -> dict[str, Any]:
    path = (
        _mission_directory(mission_id)
        / "repair-context.json"
    )

    context = _load_json_if_exists(path)

    if context is None:
        raise MissionRepairEditGeneratorError(
            "Repair Contextが存在しません。"
        )

    return context


def _validate_context(
    *,
    mission_id: int,
    context: dict[str, Any],
) -> None:
    if context.get("mission_id") != mission_id:
        raise MissionRepairEditGeneratorError(
            "Repair ContextのMission IDが"
            "一致しません。"
        )

    if (
        context.get(
            "repair_context_version"
        )
        != REPAIR_CONTEXT_VERSION
    ):
        raise MissionRepairEditGeneratorError(
            "未対応のRepair Context Versionです。"
        )

    repair_request = context.get(
        "repair_request"
    )

    if not isinstance(
        repair_request,
        dict,
    ):
        raise MissionRepairEditGeneratorError(
            "Repair Request情報が不正です。"
        )

    request_status = repair_request.get(
        "status"
    )

    if request_status not in (
        ALLOWED_CONTEXT_STATUSES
    ):
        raise MissionRepairEditGeneratorError(
            "Repair Editを生成できる状態では"
            "ありません。"
        )

    safety_policy = context.get(
        "safety_policy"
    )

    if not isinstance(
        safety_policy,
        dict,
    ):
        raise MissionRepairEditGeneratorError(
            "Safety Policyが存在しません。"
        )

    if safety_policy.get(
        "auto_apply"
    ) is not False:
        raise MissionRepairEditGeneratorError(
            "auto_applyが安全状態ではありません。"
        )

    if (
        safety_policy.get(
            "require_patch_check"
        )
        is not True
    ):
        raise MissionRepairEditGeneratorError(
            "Patch Check必須設定を確認できません。"
        )

    if (
        safety_policy.get(
            "require_verification"
        )
        is not True
    ):
        raise MissionRepairEditGeneratorError(
            "Verification必須設定を"
            "確認できません。"
        )


def _source_map(
    context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[
        str,
        dict[str, Any],
    ] = {}

    source_files = context.get(
        "source_files"
    )

    if not isinstance(
        source_files,
        list,
    ):
        return result

    for source in source_files:
        if not isinstance(source, dict):
            continue

        raw_path = source.get(
            "relative_path"
        )

        normalized = (
            _normalize_relative_path(
                raw_path
            )
        )

        if normalized is None:
            continue

        if source.get("included") is not True:
            continue

        content = source.get("content")

        if not isinstance(content, str):
            continue

        if (
            len(content.encode("utf-8"))
            > MAX_TEXT_BYTES
        ):
            continue

        result[normalized] = source

    return result


def _failed_results(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    verification = context.get(
        "verification"
    )

    if not isinstance(
        verification,
        dict,
    ):
        return []

    values = verification.get(
        "failed_results"
    )

    if not isinstance(values, list):
        return []

    return [
        item
        for item in values
        if isinstance(item, dict)
    ]


def _failure_text(
    failure: dict[str, Any],
) -> str:
    parts: list[str] = []

    for key in (
        "stderr",
        "stdout",
        "message",
        "error",
        "detail",
        "reason",
        "output",
    ):
        value = failure.get(key)

        if isinstance(value, str):
            parts.append(value)

    return "\n".join(parts)


def _extract_path(
    failure: dict[str, Any],
    text: str,
) -> str | None:
    for key in (
        "path",
        "file",
        "file_path",
        "relative_path",
        "target_path",
    ):
        normalized = (
            _normalize_relative_path(
                failure.get(key)
            )
        )

        if normalized is not None:
            return normalized

    patterns = (
        r'File "([^"]+\.py)"',
        r"([A-Za-z0-9_./-]+\.py):\d+",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )

        if not match:
            continue

        raw_path = match.group(1)

        try:
            resolved = Path(
                raw_path
            ).resolve()

            relative = resolved.relative_to(
                ARC_ROOT.resolve()
            ).as_posix()

            normalized = (
                _normalize_relative_path(
                    relative
                )
            )

            if normalized is not None:
                return normalized
        except ValueError:
            normalized = (
                _normalize_relative_path(
                    raw_path
                )
            )

            if normalized is not None:
                return normalized

    return None


def _extract_line_number(
    failure: dict[str, Any],
    text: str,
) -> int | None:
    for key in (
        "line",
        "line_number",
        "lineno",
    ):
        value = failure.get(key)

        if isinstance(value, int):
            if value > 0:
                return value

        if isinstance(value, str):
            if value.isdigit():
                parsed = int(value)

                if parsed > 0:
                    return parsed

    patterns = (
        r"line\s+(\d+)",
        r"\.py:(\d+)",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            value = int(match.group(1))

            if value > 0:
                return value

    return None


def _previous_edit_signatures(
    context: dict[str, Any],
) -> set[str]:
    signatures: set[str] = set()

    repair_request = context.get(
        "repair_request"
    )

    if not isinstance(
        repair_request,
        dict,
    ):
        return signatures

    previous_edits = repair_request.get(
        "previous_edits"
    )

    if not isinstance(
        previous_edits,
        list,
    ):
        return signatures

    for edit in previous_edits:
        if not isinstance(edit, dict):
            continue

        signatures.add(
            _edit_signature(edit)
        )

    return signatures


def _edit_signature(
    edit: dict[str, Any],
) -> str:
    payload = {
        "operation": edit.get(
            "operation"
        ),
        "path": edit.get("path"),
        "old_text": edit.get(
            "old_text"
        ),
        "new_text": edit.get(
            "new_text"
        ),
    }

    return _sha256_json(payload)


def _validate_generated_edit(
    edit: dict[str, Any],
    source_content: str,
) -> None:
    operation = edit.get("operation")

    if operation not in (
        SUPPORTED_OPERATIONS
    ):
        raise MissionRepairEditGeneratorError(
            "未対応のEdit Operationです。"
        )

    path = _normalize_relative_path(
        edit.get("path")
    )

    if path is None:
        raise MissionRepairEditGeneratorError(
            "Edit対象Pathが不正です。"
        )

    _safe_source_path(path)

    old_text = edit.get("old_text")
    new_text = edit.get("new_text")

    if not isinstance(old_text, str):
        raise MissionRepairEditGeneratorError(
            "old_textが不正です。"
        )

    if not isinstance(new_text, str):
        raise MissionRepairEditGeneratorError(
            "new_textが不正です。"
        )

    if not old_text:
        raise MissionRepairEditGeneratorError(
            "old_textは空にできません。"
        )

    if old_text == new_text:
        raise MissionRepairEditGeneratorError(
            "変更前後の内容が同一です。"
        )

    match_count = source_content.count(
        old_text
    )

    if match_count != 1:
        raise MissionRepairEditGeneratorError(
            "old_textが対象ファイル内で"
            "一意ではありません。"
        )


def _generate_missing_colon_edit(
    *,
    path: str,
    content: str,
    line_number: int,
    failure_text: str,
) -> dict[str, Any] | None:
    normalized_failure = (
        failure_text.lower()
    )

    expected_colon = any(
        phrase in normalized_failure
        for phrase in (
            "expected ':'",
            "expected \":\"",
            "':' expected",
        )
    )

    if not expected_colon:
        return None

    lines = content.splitlines(
        keepends=True
    )

    if (
        line_number < 1
        or line_number > len(lines)
    ):
        return None

    line = lines[line_number - 1]

    newline = ""

    if line.endswith("\r\n"):
        body = line[:-2]
        newline = "\r\n"
    elif line.endswith("\n"):
        body = line[:-1]
        newline = "\n"
    else:
        body = line

    stripped = body.rstrip()

    if not stripped:
        return None

    if stripped.endswith(":"):
        return None

    code_without_comment = stripped

    if "#" in stripped:
        before_comment, comment = (
            stripped.split("#", 1)
        )

        before_comment = (
            before_comment.rstrip()
        )

        if not before_comment:
            return None

        if before_comment.endswith(":"):
            return None

        new_body = (
            before_comment
            + ":  #"
            + comment
        )
    else:
        new_body = stripped + ":"

    leading_and_code_padding = (
        body[: len(body) - len(body.lstrip())]
    )

    if body.startswith(
        leading_and_code_padding
    ):
        indentation = (
            leading_and_code_padding
        )
    else:
        indentation = ""

    if new_body.startswith(indentation):
        replacement_body = new_body
    else:
        replacement_body = (
            indentation
            + new_body.lstrip()
        )

    old_text = line
    new_text = (
        replacement_body + newline
    )

    if content.count(old_text) != 1:
        return None

    return {
        "operation": "REPLACE_UNIQUE",
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "reason": (
            f"SyntaxError expected ':'を"
            f"{path}:{line_number}で検出したため、"
            "対象行末へコロンを追加します。"
        ),
        "confidence": 0.95,
        "rule_id": (
            "python-syntax-expected-colon-v0.1"
        ),
    }


def _generate_tab_error_edit(
    *,
    path: str,
    content: str,
    line_number: int,
    failure_text: str,
) -> dict[str, Any] | None:
    lowered = failure_text.lower()

    if not any(
        phrase in lowered
        for phrase in (
            "taberror",
            "inconsistent use of tabs and spaces",
        )
    ):
        return None

    lines = content.splitlines(
        keepends=True
    )

    if (
        line_number < 1
        or line_number > len(lines)
    ):
        return None

    line = lines[line_number - 1]

    prefix_match = re.match(
        r"^[\t ]+",
        line,
    )

    if not prefix_match:
        return None

    old_prefix = prefix_match.group(0)

    if "\t" not in old_prefix:
        return None

    new_prefix = old_prefix.replace(
        "\t",
        "    ",
    )

    old_text = line
    new_text = (
        new_prefix
        + line[len(old_prefix):]
    )

    if content.count(old_text) != 1:
        return None

    return {
        "operation": "REPLACE_UNIQUE",
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "reason": (
            f"TabErrorを{path}:{line_number}"
            "で検出したため、対象行のタブを"
            "4スペースへ変換します。"
        ),
        "confidence": 0.90,
        "rule_id": (
            "python-taberror-line-normalize-v0.1"
        ),
    }


def _generate_trailing_whitespace_edit(
    *,
    path: str,
    content: str,
    line_number: int,
    failure_text: str,
) -> dict[str, Any] | None:
    lowered = failure_text.lower()

    if not any(
        phrase in lowered
        for phrase in (
            "trailing whitespace",
            "w291",
            "w293",
        )
    ):
        return None

    lines = content.splitlines(
        keepends=True
    )

    if (
        line_number < 1
        or line_number > len(lines)
    ):
        return None

    line = lines[line_number - 1]

    newline = ""

    if line.endswith("\r\n"):
        body = line[:-2]
        newline = "\r\n"
    elif line.endswith("\n"):
        body = line[:-1]
        newline = "\n"
    else:
        body = line

    cleaned = body.rstrip(" \t")

    if cleaned == body:
        return None

    old_text = line
    new_text = cleaned + newline

    if content.count(old_text) != 1:
        return None

    return {
        "operation": "REPLACE_UNIQUE",
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "reason": (
            f"Trailing whitespaceを"
            f"{path}:{line_number}で検出したため、"
            "行末空白を除去します。"
        ),
        "confidence": 0.99,
        "rule_id": (
            "lint-trailing-whitespace-v0.1"
        ),
    }


def _generate_edit_for_failure(
    *,
    failure: dict[str, Any],
    sources: dict[
        str,
        dict[str, Any],
    ],
) -> dict[str, Any] | None:
    text = _failure_text(failure)

    path = _extract_path(
        failure,
        text,
    )

    if path is None:
        return None

    source = sources.get(path)

    if source is None:
        return None

    content = source.get("content")

    if not isinstance(content, str):
        return None

    line_number = _extract_line_number(
        failure,
        text,
    )

    if line_number is None:
        return None

    rules = (
        _generate_missing_colon_edit,
        _generate_tab_error_edit,
        _generate_trailing_whitespace_edit,
    )

    for rule in rules:
        edit = rule(
            path=path,
            content=content,
            line_number=line_number,
            failure_text=text,
        )

        if edit is None:
            continue

        _validate_generated_edit(
            edit,
            content,
        )

        return edit

    return None


def generate_repair_edit(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)
    context = _load_repair_context(
        mission_id
    )

    _validate_context(
        mission_id=mission_id,
        context=context,
    )

    sources = _source_map(context)
    failures = _failed_results(context)

    previous_signatures = (
        _previous_edit_signatures(
            context
        )
    )

    edits: list[dict[str, Any]] = []
    skipped_reasons: list[str] = []

    for index, failure in enumerate(
        failures,
        start=1,
    ):
        try:
            edit = (
                _generate_edit_for_failure(
                    failure=failure,
                    sources=sources,
                )
            )
        except (
            MissionRepairEditGeneratorError,
            ValueError,
        ) as error:
            skipped_reasons.append(
                f"failure[{index}]: {error}"
            )
            continue

        if edit is None:
            skipped_reasons.append(
                f"failure[{index}]: "
                "対応可能な安全ルールなし"
            )
            continue

        signature = _edit_signature(edit)

        if signature in previous_signatures:
            skipped_reasons.append(
                f"failure[{index}]: "
                "前回失敗Editと同一"
            )
            continue

        if any(
            _edit_signature(existing)
            == signature
            for existing in edits
        ):
            continue

        edits.append(edit)

        if len(edits) >= MAX_GENERATED_EDITS:
            break

    if edits:
        status = "EDIT_READY"
        reason = (
            "安全な決定的ルールにより"
            f"{len(edits)}件の修正Editを"
            "生成しました。"
        )
    else:
        status = "INSUFFICIENT_CONTEXT"
        reason = (
            "現在のルールでは安全かつ一意な"
            "修正Editを生成できませんでした。"
        )

    created_at = _now()

    draft: dict[str, Any] = {
        "repair_edit_schema_version": (
            REPAIR_EDIT_SCHEMA_VERSION
        ),
        "generator_version": (
            REPAIR_EDIT_GENERATOR_VERSION
        ),
        "created_at": created_at,
        "mission_id": mission_id,
        "context_id": context.get(
            "context_id"
        ),
        "status": status,
        "reason": reason,
        "edits": edits,
        "generation_summary": {
            "failure_count": len(failures),
            "source_file_count": len(
                sources
            ),
            "generated_edit_count": len(
                edits
            ),
            "skipped_reasons": (
                skipped_reasons
            ),
            "previous_edit_signature_count": (
                len(previous_signatures)
            ),
        },
        "safety": {
            "auto_apply": False,
            "requires_patch_check": True,
            "requires_backup": True,
            "requires_verification": True,
            "requires_rollback_on_failure": True,
            "generated_by_ai_model": False,
            "generation_mode": (
                "DETERMINISTIC_RULE_BASED"
            ),
            "supported_operations": sorted(
                SUPPORTED_OPERATIONS
            ),
        },
        "next_stage": (
            "REPAIR_PATCH_CHECK"
            if status == "EDIT_READY"
            else "HUMAN_OR_AI_REVIEW_REQUIRED"
        ),
    }

    draft_id = (
        "repair-edit-"
        + _sha256_json(draft)[:16]
    )

    draft["draft_id"] = draft_id

    mission_dir = _mission_directory(
        mission_id
    )

    latest_path = (
        mission_dir
        / "repair-edit-draft.json"
    )

    archive_path = (
        mission_dir
        / f"{draft_id}.json"
    )

    existing = _load_json_if_exists(
        latest_path
    )

    duplicate = bool(
        isinstance(existing, dict)
        and existing.get("draft_id")
        == draft_id
    )

    if not duplicate:
        _write_json_atomic(
            archive_path,
            draft,
        )

        _write_json_atomic(
            latest_path,
            draft,
        )

    add_mission_log(
        mission_id=mission_id,
        level=(
            "INFO"
            if status == "EDIT_READY"
            else "WARNING"
        ),
        event_type=(
            "MISSION_REPAIR_EDIT_GENERATED"
        ),
        message=(
            "Repair Edit Draftを生成しました。"
        ),
        metadata={
            "generator_version": (
                REPAIR_EDIT_GENERATOR_VERSION
            ),
            "draft_id": draft_id,
            "context_id": context.get(
                "context_id"
            ),
            "status": status,
            "generated_edit_count": len(
                edits
            ),
            "duplicate": duplicate,
            "auto_apply": False,
            "latest_path": (
                _relative_to_arc(
                    latest_path
                )
            ),
        },
    )

    return {
        "mission": mission,
        "repair_edit_draft": draft,
        "storage": {
            "latest_path": (
                _relative_to_arc(
                    latest_path
                )
            ),
            "archive_path": (
                _relative_to_arc(
                    archive_path
                )
            ),
            "duplicate": duplicate,
        },
    }


def generate_repair_edit_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return generate_repair_edit(
            mission_id
        )
    except (
        MissionRepairEditGeneratorError,
        MissionError,
    ):
        raise
