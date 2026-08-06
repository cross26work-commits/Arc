from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.missions.models import (
    MissionPatchEdit,
    MissionRepairRequestCreate,
)
from app.missions.repair_policy import (
    get_repair_policy,
    serialize_repair_policy,
)
from app.missions.self_repair_planner import (
    ARC_ROOT,
    REPAIR_PLAN_ROOT,
    _load_existing_plan,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairRequestError(Exception):
    """Repair Patch Requestの生成失敗時に使用する例外。"""


REPAIR_REQUEST_VERSION = (
    "mission-repair-request-builder-v0.1"
)

ALLOWED_OPERATIONS = {
    "REPLACE_UNIQUE",
    "APPEND",
    "INSERT_BEFORE",
    "INSERT_AFTER",
}


def _repair_policy_payload(
    repair_plan: dict[str, Any],
) -> dict[str, Any]:
    verification = repair_plan.get(
        "verification",
        {},
    )

    if not isinstance(verification, dict):
        verification = {}

    failure_category = verification.get(
        "failure_category"
    )

    return serialize_repair_policy(
        get_repair_policy(failure_category)
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in mission.get("tasks", [])
            if item.get("task_type") == task_type
        ),
        None,
    )

    if task is None:
        raise MissionRepairRequestError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _load_json_result(
    task: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    raw = task.get("result")

    if not raw:
        raise MissionRepairRequestError(
            f"{label}結果が保存されていません。"
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MissionRepairRequestError(
            f"{label}結果のJSONを読み取れません。"
        ) from error

    if not isinstance(result, dict):
        raise MissionRepairRequestError(
            f"{label}結果の形式が不正です。"
        )

    return result


def _normalize_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    normalized = normalized.lstrip("/")

    while normalized.startswith("./"):
        normalized = normalized[2:]

    if (
        not normalized
        or normalized == ".."
        or normalized.startswith("../")
        or "/../" in f"/{normalized}/"
    ):
        raise MissionRepairRequestError(
            f"不正な編集対象Pathです: {value}"
        )

    return normalized


def _planner_paths(
    planning: dict[str, Any],
) -> set[str]:
    selected_files = planning.get("selected_files")

    if not isinstance(selected_files, list):
        raise MissionRepairRequestError(
            "Planner selected_filesが存在しません。"
        )

    result: set[str] = set()

    for item in selected_files:
        if not isinstance(item, dict):
            continue

        path = item.get("path")

        if isinstance(path, str) and path.strip():
            result.add(_normalize_path(path))

    if not result:
        raise MissionRepairRequestError(
            "Planner対象ファイルがありません。"
        )

    return result


def _repair_suspected_paths(
    repair_plan: dict[str, Any],
) -> set[str]:
    values = repair_plan.get("suspected_files")

    if not isinstance(values, list):
        return set()

    result: set[str] = set()

    for value in values:
        if isinstance(value, str) and value.strip():
            result.add(_normalize_path(value))

    return result


def _allowed_repair_paths(
    *,
    planning: dict[str, Any],
    repair_plan: dict[str, Any],
) -> set[str]:
    planner_paths = _planner_paths(planning)
    suspected_paths = _repair_suspected_paths(
        repair_plan
    )

    if not suspected_paths:
        raise MissionRepairRequestError(
            "Repair Planにsuspected_filesがありません。"
            "対象ファイルを確定してから編集要求を生成してください。"
        )

    allowed = planner_paths & suspected_paths

    if not allowed:
        raise MissionRepairRequestError(
            "Repair Planの対象ファイルが"
            "Planner対象に含まれていません。"
        )

    return allowed


def _validate_edit_fields(
    edit: MissionPatchEdit,
) -> None:
    if edit.operation not in ALLOWED_OPERATIONS:
        raise MissionRepairRequestError(
            f"未対応の編集操作です: {edit.operation}"
        )

    if edit.operation == "REPLACE_UNIQUE":
        if edit.old_text is None or edit.old_text == "":
            raise MissionRepairRequestError(
                "REPLACE_UNIQUEにはold_textが必要です。"
            )

        if edit.new_text is None:
            raise MissionRepairRequestError(
                "REPLACE_UNIQUEにはnew_textが必要です。"
            )

        if edit.old_text == edit.new_text:
            raise MissionRepairRequestError(
                "old_textとnew_textが同一です。"
            )

        return

    if edit.operation == "APPEND":
        if edit.text is None or edit.text == "":
            raise MissionRepairRequestError(
                "APPENDにはtextが必要です。"
            )

        return

    if edit.operation in {
        "INSERT_BEFORE",
        "INSERT_AFTER",
    }:
        if edit.anchor is None or edit.anchor == "":
            raise MissionRepairRequestError(
                f"{edit.operation}にはanchorが必要です。"
            )

        if edit.text is None or edit.text == "":
            raise MissionRepairRequestError(
                f"{edit.operation}にはtextが必要です。"
            )

        return


def _serialize_edit(
    edit: MissionPatchEdit,
) -> dict[str, Any]:
    value = edit.model_dump(
        exclude_none=True
    )
    value["path"] = _normalize_path(
        edit.path
    )
    return value


def _request_signature(
    *,
    mission_id: int,
    repair_plan_id: str,
    edits: list[dict[str, Any]],
) -> str:
    payload = {
        "mission_id": mission_id,
        "repair_plan_id": repair_plan_id,
        "edits": edits,
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def _request_directory(
    mission_id: int,
) -> Path:
    return (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
    )


def _latest_request_path(
    mission_id: int,
) -> Path:
    return (
        _request_directory(mission_id)
        / "patch-request.json"
    )


def _archive_request_path(
    *,
    mission_id: int,
    request_id: str,
) -> Path:
    return (
        _request_directory(mission_id)
        / f"patch-request-{request_id}.json"
    )


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        f".{path.name}.{uuid4().hex}.tmp"
    )

    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        path,
    )


def _load_existing_request(
    mission_id: int,
) -> dict[str, Any] | None:
    path = _latest_request_path(mission_id)

    if not path.exists():
        return None

    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(value, dict):
        return None

    return value


def create_repair_patch_request(
    *,
    mission_id: int,
    payload: MissionRepairRequestCreate,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionRepairRequestError(
            "承認済みMissionのみRepair Requestを"
            "生成できます。"
        )

    planning_task = _task_by_type(
        mission,
        "PLANNING",
    )
    approval_task = _task_by_type(
        mission,
        "APPROVAL",
    )
    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    if planning_task["status"] != "COMPLETED":
        raise MissionRepairRequestError(
            "PLANNING Taskが完了していません。"
        )

    if approval_task["status"] != "COMPLETED":
        raise MissionRepairRequestError(
            "APPROVAL Taskが完了していません。"
        )

    if implementation_task["status"] not in {
        "READY",
        "RUNNING",
    }:
        raise MissionRepairRequestError(
            "IMPLEMENTATION Taskが"
            "修復可能状態ではありません。"
        )

    if verification_task["status"] not in {
        "PENDING",
        "FAILED",
    }:
        raise MissionRepairRequestError(
            "Verification失敗後に"
            "Repair Requestを生成してください。"
        )

    verification = _load_json_result(
        verification_task,
        label="VERIFICATION",
    )

    if verification.get("passed") is not False:
        raise MissionRepairRequestError(
            "Verification失敗結果を確認できません。"
        )

    planning = _load_json_result(
        planning_task,
        label="PLANNING",
    )

    repair_plan = _load_existing_plan(
        mission_id
    )

    if repair_plan is None:
        raise MissionRepairRequestError(
            "Repair Planが存在しません。"
            "先にSelf Repair Plannerを実行してください。"
        )

    if repair_plan.get("status") != "PLANNED":
        raise MissionRepairRequestError(
            "Repair PlanがPLANNED状態ではありません。"
        )

    if repair_plan.get("auto_apply") is not False:
        raise MissionRepairRequestError(
            "Repair Planの安全状態が不正です。"
        )

    allowed_paths = _allowed_repair_paths(
        planning=planning,
        repair_plan=repair_plan,
    )

    serialized_edits: list[dict[str, Any]] = []
    edit_paths: set[str] = set()

    for index, edit in enumerate(
        payload.edits,
        start=1,
    ):
        _validate_edit_fields(edit)

        path = _normalize_path(edit.path)

        if path not in allowed_paths:
            raise MissionRepairRequestError(
                f"edits[{index}]はRepair対象外です: "
                f"{path}"
            )

        serialized = _serialize_edit(edit)
        serialized_edits.append(serialized)
        edit_paths.add(path)

    if not serialized_edits:
        raise MissionRepairRequestError(
            "編集要求がありません。"
        )

    repair_plan_id = str(
        repair_plan.get("repair_plan_id")
        or ""
    ).strip()

    if not repair_plan_id:
        raise MissionRepairRequestError(
            "Repair Plan IDがありません。"
        )

    repair_policy = _repair_policy_payload(
        repair_plan
    )

    signature = _request_signature(
        mission_id=mission_id,
        repair_plan_id=repair_plan_id,
        edits=serialized_edits,
    )

    existing = _load_existing_request(
        mission_id
    )

    if (
        existing is not None
        and existing.get("request_signature")
        == signature
    ):
        return {
            "mission": mission,
            "repair_request": existing,
            "storage": {
                "latest_path": (
                    _latest_request_path(
                        mission_id
                    )
                    .relative_to(ARC_ROOT)
                    .as_posix()
                ),
                "duplicate": True,
            },
        }

    request_id = uuid4().hex

    repair_request = {
        "request_version": (
            REPAIR_REQUEST_VERSION
        ),
        "request_id": request_id,
        "request_signature": signature,
        "mission_id": mission_id,
        "project_id": mission["project_id"],
        "project_name": mission["project_name"],
        "repair_plan_id": repair_plan_id,
        "verification_failure_signature": (
            repair_plan.get(
                "verification_failure_signature"
            )
        ),
        "failure_category": (
            repair_policy["failure_category"]
        ),
        "repair_policy": repair_policy,
        "repair_action": (
            repair_policy["repair_action"]
        ),
        "resume_stage": (
            repair_policy["resume_stage"]
        ),
        "max_retries": (
            repair_policy["max_retries"]
        ),
        "requires_approval": (
            repair_policy["requires_approval"]
        ),
        "allowed_paths": sorted(
            allowed_paths
        ),
        "edit_paths": sorted(
            edit_paths
        ),
        "operation_count": len(
            serialized_edits
        ),
        "edits": serialized_edits,
        "generated_by": (
            payload.generated_by.strip()
        ),
        "note": (
            payload.note.strip()
            if payload.note
            else None
        ),
        "status": "REQUESTED",
        "patch_generated": False,
        "patch_checked": False,
        "patch_applied": False,
        "auto_apply": False,
        "created_at": _now(),
    }

    latest_path = _latest_request_path(
        mission_id
    )
    archive_path = _archive_request_path(
        mission_id=mission_id,
        request_id=request_id,
    )

    _write_json_atomic(
        archive_path,
        repair_request,
    )
    _write_json_atomic(
        latest_path,
        repair_request,
    )

    add_mission_log(
        mission_id=mission_id,
        level="WARNING",
        event_type=(
            "MISSION_REPAIR_PATCH_REQUEST_CREATED"
        ),
        message=(
            "Repair PlanとPlanner対象を照合し、"
            "自動適用を伴わないPatch Requestを"
            "生成しました。"
        ),
        metadata={
            "request_version": (
                REPAIR_REQUEST_VERSION
            ),
            "request_id": request_id,
            "repair_plan_id": repair_plan_id,
            "operation_count": len(
                serialized_edits
            ),
            "edit_paths": sorted(
                edit_paths
            ),
            "status": "REQUESTED",
            "patch_generated": False,
            "patch_applied": False,
            "auto_apply": False,
            "latest_path": (
                latest_path
                .relative_to(ARC_ROOT)
                .as_posix()
            ),
        },
    )

    return {
        "mission": get_mission(mission_id),
        "repair_request": repair_request,
        "storage": {
            "latest_path": (
                latest_path
                .relative_to(ARC_ROOT)
                .as_posix()
            ),
            "archive_path": (
                archive_path
                .relative_to(ARC_ROOT)
                .as_posix()
            ),
            "duplicate": False,
        },
    }


def create_repair_patch_request_safe(
    *,
    mission_id: int,
    payload: MissionRepairRequestCreate,
) -> dict[str, Any]:
    try:
        return create_repair_patch_request(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairRequestError,
        MissionError,
    ):
        raise
