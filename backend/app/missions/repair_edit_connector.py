from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.repair_context_builder import (
    REPAIR_PLAN_ROOT,
    _load_json_if_exists,
    _normalize_relative_path,
    _relative_to_arc,
)
from app.missions.repair_edit_generator import (
    REPAIR_EDIT_GENERATOR_VERSION,
    REPAIR_EDIT_SCHEMA_VERSION,
)
from app.missions.repair_request_builder import (
    _load_existing_request,
    _write_json_atomic,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairEditConnectorError(Exception):
    """Repair Edit接続失敗時の例外。"""


REPAIR_EDIT_CONNECTOR_VERSION = (
    "mission-repair-edit-connector-v0.1"
)

ALLOWED_DRAFT_STATUS = {
    "EDIT_READY",
}

ALLOWED_REQUEST_STATUSES = {
    "AWAITING_REPAIR_PATCH_CHECK",
    "AWAITING_REPAIR_REQUEST",
    "REPAIR_FAILED",
    "REQUESTED",
}

ALLOWED_OPERATIONS = {
    "REPLACE_UNIQUE",
    "INSERT_BEFORE",
    "INSERT_AFTER",
    "CREATE_FILE",
}

MAX_EDITS = 10
MAX_TEXT_BYTES = 200_000


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


def _load_edit_draft(
    mission_id: int,
) -> dict[str, Any]:
    path = (
        _mission_directory(mission_id)
        / "repair-edit-draft.json"
    )

    draft = _load_json_if_exists(path)

    if draft is None:
        raise MissionRepairEditConnectorError(
            "Repair Edit Draftが存在しません。"
        )

    return draft


def _validate_request(
    *,
    mission_id: int,
    request: dict[str, Any],
) -> None:
    if request.get("mission_id") != mission_id:
        raise MissionRepairEditConnectorError(
            "Repair RequestのMission IDが"
            "一致しません。"
        )

    status = request.get("status")

    if status not in ALLOWED_REQUEST_STATUSES:
        raise MissionRepairEditConnectorError(
            "Repair Editを接続できる"
            "Repair Request状態ではありません。"
        )

    if request.get("auto_apply") is not False:
        raise MissionRepairEditConnectorError(
            "Repair Requestのauto_applyが"
            "安全状態ではありません。"
        )


def _validate_text(
    *,
    value: Any,
    name: str,
    allow_empty: bool,
) -> str:
    if not isinstance(value, str):
        raise MissionRepairEditConnectorError(
            f"{name}が文字列ではありません。"
        )

    if (
        not allow_empty
        and not value
    ):
        raise MissionRepairEditConnectorError(
            f"{name}は空にできません。"
        )

    if (
        len(value.encode("utf-8"))
        > MAX_TEXT_BYTES
    ):
        raise MissionRepairEditConnectorError(
            f"{name}が上限サイズを超えています。"
        )

    return value


def _validate_edit(
    edit: dict[str, Any],
) -> dict[str, Any]:
    operation = edit.get("operation")

    if operation not in ALLOWED_OPERATIONS:
        raise MissionRepairEditConnectorError(
            "未対応のEdit Operationです。"
        )

    path = _normalize_relative_path(
        edit.get("path")
    )

    if path is None:
        raise MissionRepairEditConnectorError(
            "Edit対象Pathが不正です。"
        )

    normalized: dict[str, Any] = {
        "operation": operation,
        "path": path,
    }

    if operation == "CREATE_FILE":
        content = _validate_text(
            value=edit.get(
                "content",
                edit.get("new_text"),
            ),
            name="content",
            allow_empty=True,
        )

        normalized["content"] = content
    else:
        old_text = _validate_text(
            value=edit.get("old_text"),
            name="old_text",
            allow_empty=False,
        )

        new_text = _validate_text(
            value=edit.get("new_text"),
            name="new_text",
            allow_empty=True,
        )

        if (
            operation == "REPLACE_UNIQUE"
            and old_text == new_text
        ):
            raise MissionRepairEditConnectorError(
                "REPLACE_UNIQUEの変更前後が"
                "同一です。"
            )

        normalized["old_text"] = old_text
        normalized["new_text"] = new_text

    for key in (
        "reason",
        "rule_id",
        "confidence",
    ):
        if key in edit:
            normalized[key] = edit[key]

    return normalized


def _validate_draft(
    *,
    mission_id: int,
    draft: dict[str, Any],
) -> list[dict[str, Any]]:
    if draft.get("mission_id") != mission_id:
        raise MissionRepairEditConnectorError(
            "Repair Edit DraftのMission IDが"
            "一致しません。"
        )

    if (
        draft.get(
            "repair_edit_schema_version"
        )
        != REPAIR_EDIT_SCHEMA_VERSION
    ):
        raise MissionRepairEditConnectorError(
            "未対応のRepair Edit Schemaです。"
        )

    if (
        draft.get("generator_version")
        != REPAIR_EDIT_GENERATOR_VERSION
    ):
        raise MissionRepairEditConnectorError(
            "未対応のRepair Edit Generatorです。"
        )

    if (
        draft.get("status")
        not in ALLOWED_DRAFT_STATUS
    ):
        raise MissionRepairEditConnectorError(
            "EDIT_READY状態のDraftのみ"
            "接続できます。"
        )

    safety = draft.get("safety")

    if not isinstance(safety, dict):
        raise MissionRepairEditConnectorError(
            "DraftのSafety情報が存在しません。"
        )

    if safety.get("auto_apply") is not False:
        raise MissionRepairEditConnectorError(
            "Draftのauto_applyが"
            "安全状態ではありません。"
        )

    if (
        safety.get(
            "requires_patch_check"
        )
        is not True
    ):
        raise MissionRepairEditConnectorError(
            "Patch Check必須設定を"
            "確認できません。"
        )

    if (
        safety.get(
            "requires_verification"
        )
        is not True
    ):
        raise MissionRepairEditConnectorError(
            "Verification必須設定を"
            "確認できません。"
        )

    edits = draft.get("edits")

    if not isinstance(edits, list):
        raise MissionRepairEditConnectorError(
            "Draftのeditsが不正です。"
        )

    if not edits:
        raise MissionRepairEditConnectorError(
            "DraftにEditが存在しません。"
        )

    if len(edits) > MAX_EDITS:
        raise MissionRepairEditConnectorError(
            "Edit件数が上限を超えています。"
        )

    normalized_edits: list[
        dict[str, Any]
    ] = []

    signatures: set[str] = set()

    for raw_edit in edits:
        if not isinstance(raw_edit, dict):
            raise MissionRepairEditConnectorError(
                "Edit要素がObjectではありません。"
            )

        normalized = _validate_edit(
            raw_edit
        )

        signature = _sha256_json(
            normalized
        )

        if signature in signatures:
            raise MissionRepairEditConnectorError(
                "同一Editが重複しています。"
            )

        signatures.add(signature)
        normalized_edits.append(
            normalized
        )

    return normalized_edits


def _request_edit_signatures(
    request: dict[str, Any],
) -> set[str]:
    edits = request.get("edits")

    if not isinstance(edits, list):
        return set()

    signatures: set[str] = set()

    for edit in edits:
        if not isinstance(edit, dict):
            continue

        try:
            normalized = _validate_edit(
                edit
            )
        except MissionRepairEditConnectorError:
            continue

        signatures.add(
            _sha256_json(normalized)
        )

    return signatures


def connect_repair_edit(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    request = _load_existing_request(
        mission_id
    )

    if request is None:
        raise MissionRepairEditConnectorError(
            "Repair Requestが存在しません。"
        )

    draft = _load_edit_draft(
        mission_id
    )

    _validate_request(
        mission_id=mission_id,
        request=request,
    )

    normalized_edits = _validate_draft(
        mission_id=mission_id,
        draft=draft,
    )

    context_id = draft.get(
        "context_id"
    )

    draft_id = draft.get(
        "draft_id"
    )

    if not isinstance(draft_id, str):
        raise MissionRepairEditConnectorError(
            "Draft IDが不正です。"
        )

    previous_draft_id = request.get(
        "repair_edit_draft_id"
    )

    current_signatures = (
        _request_edit_signatures(
            request
        )
    )

    new_signatures = {
        _sha256_json(edit)
        for edit in normalized_edits
    }

    duplicate = bool(
        previous_draft_id == draft_id
        and current_signatures
        == new_signatures
        and request.get("status")
        == "AWAITING_REPAIR_PATCH_CHECK"
    )

    connected_at = _now()

    updated_request = dict(request)

    updated_request.update(
        {
            "status": (
                "AWAITING_REPAIR_PATCH_CHECK"
            ),
            "next_stage": (
                "REPAIR_PATCH_CHECK"
            ),
            "auto_apply": False,
            "edits": normalized_edits,
            "repair_edit_draft_id": (
                draft_id
            ),
            "repair_edit_context_id": (
                context_id
            ),
            "repair_edit_connected_at": (
                connected_at
            ),
            "repair_edit_connector_version": (
                REPAIR_EDIT_CONNECTOR_VERSION
            ),
            "repair_edit_generator_version": (
                draft.get(
                    "generator_version"
                )
            ),
            "repair_edit_generation_mode": (
                draft.get(
                    "safety",
                    {},
                ).get(
                    "generation_mode"
                )
            ),
            "repair_edit_count": len(
                normalized_edits
            ),
            "requires_patch_check": True,
            "requires_backup": True,
            "requires_verification": True,
            "requires_rollback_on_failure": (
                True
            ),
        }
    )

    connection_payload = {
        "connector_version": (
            REPAIR_EDIT_CONNECTOR_VERSION
        ),
        "connected_at": connected_at,
        "mission_id": mission_id,
        "request_id": request.get(
            "request_id"
        ),
        "draft_id": draft_id,
        "context_id": context_id,
        "edit_count": len(
            normalized_edits
        ),
        "status": (
            "AWAITING_REPAIR_PATCH_CHECK"
        ),
        "next_stage": (
            "REPAIR_PATCH_CHECK"
        ),
        "auto_apply": False,
        "edits": normalized_edits,
    }

    connection_id = (
        "repair-edit-connection-"
        + _sha256_json(
            connection_payload
        )[:16]
    )

    connection_payload[
        "connection_id"
    ] = connection_id

    updated_request[
        "repair_edit_connection_id"
    ] = connection_id

    mission_dir = _mission_directory(
        mission_id
    )

    request_path = (
        mission_dir
        / "repair-request.json"
    )

    connection_latest_path = (
        mission_dir
        / "repair-edit-connection.json"
    )

    connection_archive_path = (
        mission_dir
        / f"{connection_id}.json"
    )

    if not duplicate:
        _write_json_atomic(
            request_path,
            updated_request,
        )

        _write_json_atomic(
            connection_latest_path,
            connection_payload,
        )

        _write_json_atomic(
            connection_archive_path,
            connection_payload,
        )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_REPAIR_EDIT_CONNECTED"
        ),
        message=(
            "Repair Edit Draftを"
            "Repair Patch Check経路へ"
            "接続しました。"
        ),
        metadata={
            "connector_version": (
                REPAIR_EDIT_CONNECTOR_VERSION
            ),
            "connection_id": (
                connection_id
            ),
            "draft_id": draft_id,
            "context_id": context_id,
            "edit_count": len(
                normalized_edits
            ),
            "status": (
                "AWAITING_REPAIR_PATCH_CHECK"
            ),
            "next_stage": (
                "REPAIR_PATCH_CHECK"
            ),
            "duplicate": duplicate,
            "auto_apply": False,
            "request_path": (
                _relative_to_arc(
                    request_path
                )
            ),
        },
    )

    return {
        "mission": mission,
        "repair_request": (
            updated_request
        ),
        "connection": (
            connection_payload
        ),
        "storage": {
            "request_path": (
                _relative_to_arc(
                    request_path
                )
            ),
            "latest_path": (
                _relative_to_arc(
                    connection_latest_path
                )
            ),
            "archive_path": (
                _relative_to_arc(
                    connection_archive_path
                )
            ),
            "duplicate": duplicate,
        },
    }


def connect_repair_edit_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return connect_repair_edit(
            mission_id
        )
    except (
        MissionRepairEditConnectorError,
        MissionError,
    ):
        raise
