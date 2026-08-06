from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.repair_policy import (
    get_repair_policy,
)
from app.missions.repair_request_builder import (
    REPAIR_PLAN_ROOT,
    _load_existing_request,
    _write_json_atomic,
)
from app.missions.self_repair_planner import ARC_ROOT
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairContextError(Exception):
    """Repair Context作成失敗時の例外。"""


REPAIR_CONTEXT_VERSION = (
    "mission-repair-context-v0.1"
)

MAX_CONTEXT_FILES = 20
MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 1_000_000

ALLOWED_REPAIR_STATUSES = {
    "AWAITING_REPAIR_REQUEST",
    "REPAIR_FAILED",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_to_arc(path: Path) -> str:
    resolved = path.resolve()

    try:
        return resolved.relative_to(
            ARC_ROOT.resolve()
        ).as_posix()
    except ValueError:
        return resolved.as_posix()


def _normalize_relative_path(
    raw_path: Any,
) -> str | None:
    if not isinstance(raw_path, str):
        return None

    normalized = raw_path.strip().replace(
        "\\",
        "/",
    )

    if not normalized:
        return None

    if normalized.startswith("/"):
        return None

    path = Path(normalized)

    if ".." in path.parts:
        return None

    if path.is_absolute():
        return None

    return path.as_posix()


def _safe_source_path(
    relative_path: str,
) -> Path:
    root = ARC_ROOT.resolve()
    candidate = (
        root / relative_path
    ).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise MissionRepairContextError(
            "対象ファイルがArcルート外です。"
        ) from error

    return candidate


def _append_path(
    paths: list[str],
    value: Any,
) -> None:
    normalized = _normalize_relative_path(
        value
    )

    if normalized is None:
        return

    if normalized not in paths:
        paths.append(normalized)


def _collect_paths_from_value(
    paths: list[str],
    value: Any,
) -> None:
    if isinstance(value, str):
        _append_path(paths, value)
        return

    if isinstance(value, list):
        for item in value:
            _collect_paths_from_value(
                paths,
                item,
            )
        return

    if not isinstance(value, dict):
        return

    for key in (
        "path",
        "file",
        "file_path",
        "relative_path",
        "target_file",
        "target_path",
    ):
        _append_path(
            paths,
            value.get(key),
        )

    for key in (
        "files",
        "selected_files",
        "suspected_files",
        "changed_files",
        "target_files",
        "edits",
        "operations",
        "failed_results",
    ):
        child = value.get(key)

        if child is not None:
            _collect_paths_from_value(
                paths,
                child,
            )


def _collect_candidate_paths(
    repair_request: dict[str, Any],
) -> list[str]:
    paths: list[str] = []

    for key in (
        "selected_files",
        "suspected_files",
        "target_files",
        "changed_files",
        "edits",
        "operations",
        "verification_result",
        "apply_result",
        "patch_result",
        "patch_check_result",
    ):
        value = repair_request.get(key)

        if value is not None:
            _collect_paths_from_value(
                paths,
                value,
            )

    return paths[:MAX_CONTEXT_FILES]


def _read_source_file(
    relative_path: str,
    remaining_total_bytes: int,
) -> dict[str, Any]:
    path = _safe_source_path(
        relative_path
    )

    result: dict[str, Any] = {
        "relative_path": relative_path,
        "exists": path.exists(),
        "is_file": path.is_file(),
        "included": False,
        "truncated": False,
        "size_bytes": None,
        "sha256": None,
        "content": None,
        "error": None,
    }

    if not path.exists():
        result["error"] = "FILE_NOT_FOUND"
        return result

    if not path.is_file():
        result["error"] = "NOT_A_REGULAR_FILE"
        return result

    try:
        data = path.read_bytes()
    except OSError as error:
        result["error"] = (
            f"READ_ERROR: {error}"
        )
        return result

    result["size_bytes"] = len(data)
    result["sha256"] = _sha256_bytes(
        data
    )

    allowed_bytes = min(
        MAX_FILE_BYTES,
        max(remaining_total_bytes, 0),
    )

    if allowed_bytes <= 0:
        result["error"] = (
            "TOTAL_CONTEXT_LIMIT_REACHED"
        )
        return result

    selected = data[:allowed_bytes]

    if len(selected) < len(data):
        result["truncated"] = True

    try:
        content = selected.decode(
            "utf-8"
        )
    except UnicodeDecodeError:
        content = selected.decode(
            "utf-8",
            errors="replace",
        )
        result["error"] = (
            "UTF8_REPLACEMENT_USED"
        )

    result["content"] = content
    result["included"] = True

    return result


def _load_json_if_exists(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    if not path.is_file():
        return None

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(data, dict):
        return None

    return data


def _find_repair_plan(
    *,
    mission_id: int,
    repair_request: dict[str, Any],
) -> dict[str, Any] | None:
    mission_dir = (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
    )

    requested_plan_id = str(
        repair_request.get(
            "retry_repair_plan_id"
        )
        or repair_request.get(
            "repair_plan_id"
        )
        or ""
    ).strip()

    candidates = [
        mission_dir / "repair-plan.json",
        mission_dir / "latest.json",
    ]

    candidates.extend(
        sorted(
            mission_dir.glob(
                "repair-plan-*.json"
            ),
            key=lambda item: (
                item.stat().st_mtime
                if item.exists()
                else 0
            ),
            reverse=True,
        )
    )

    fallback: dict[str, Any] | None = None

    for path in candidates:
        plan = _load_json_if_exists(
            path
        )

        if plan is None:
            continue

        if fallback is None:
            fallback = plan

        plan_id = str(
            plan.get("repair_plan_id")
            or plan.get("plan_id")
            or ""
        ).strip()

        if (
            requested_plan_id
            and plan_id == requested_plan_id
        ):
            return plan

    return fallback


def _validate_request(
    *,
    mission_id: int,
    repair_request: dict[str, Any],
) -> None:
    if repair_request.get(
        "mission_id"
    ) != mission_id:
        raise MissionRepairContextError(
            "Repair RequestのMission IDが"
            "一致しません。"
        )

    request_status = repair_request.get(
        "status"
    )

    if request_status not in (
        ALLOWED_REPAIR_STATUSES
    ):
        raise MissionRepairContextError(
            "Repair Contextを作成できるのは"
            "AWAITING_REPAIR_REQUESTまたは"
            "REPAIR_FAILED状態のみです。"
        )

    if repair_request.get(
        "auto_apply"
    ) is not False:
        raise MissionRepairContextError(
            "auto_applyが安全状態ではありません。"
        )

    if request_status == "REPAIR_FAILED":
        if (
            repair_request.get(
                "repair_verification_passed"
            )
            is not False
        ):
            raise MissionRepairContextError(
                "Repair Verification失敗を"
                "確認できません。"
            )

        if (
            repair_request.get(
                "repair_patch_rolled_back"
            )
            is not True
        ):
            raise MissionRepairContextError(
                "Rollback完了を確認できません。"
            )


def _verification_context(
    repair_request: dict[str, Any],
) -> dict[str, Any]:
    verification = repair_request.get(
        "verification_result"
    )

    if not isinstance(
        verification,
        dict,
    ):
        verification = {}

    failed_results = verification.get(
        "failed_results"
    )

    if not isinstance(
        failed_results,
        list,
    ):
        failed_results = []

    return {
        "passed": verification.get(
            "passed"
        ),
        "failure_category": (
            verification.get(
                "failure_category"
            )
        ),
        "requested_command_count": (
            verification.get(
                "requested_command_count"
            )
        ),
        "executed_command_count": (
            verification.get(
                "executed_command_count"
            )
        ),
        "failed_results": failed_results,
    }


def _safety_policy(
    *,
    maximum_retry_count: int,
) -> dict[str, Any]:
    return {
        "auto_apply": False,
        "require_unique_match": True,
        "require_patch_check": True,
        "require_backup": True,
        "require_verification": True,
        "require_rollback_on_failure": True,
        "forbid_paths_outside_arc_root": True,
        "forbid_secret_file_edits": True,
        "forbid_binary_file_edits": True,
        "forbid_dependency_install_without_approval": True,
        "forbid_shell_execution_from_generated_text": True,
        "allowed_edit_operations": [
            "REPLACE_UNIQUE",
            "INSERT_BEFORE",
            "INSERT_AFTER",
            "CREATE_FILE",
        ],
        "maximum_files_per_attempt": 10,
        "maximum_retry_count": (
            maximum_retry_count
        ),
    }


def _resolve_context_retry_limit(
    repair_request: dict[str, Any],
) -> int:
    embedded_policy = repair_request.get(
        "repair_policy"
    )

    if isinstance(embedded_policy, dict):
        policy_limit = embedded_policy.get(
            "max_retries"
        )
    else:
        policy_limit = None

    if policy_limit is None:
        policy_limit = get_repair_policy(
            repair_request.get(
                "failure_category"
            )
        ).max_retries

    try:
        normalized_policy_limit = int(
            policy_limit
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise MissionRepairContextError(
            "Repair Policy Retry????????"
        ) from error

    requested_limit = repair_request.get(
        "max_retries",
        normalized_policy_limit,
    )

    try:
        normalized_requested_limit = int(
            requested_limit
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise MissionRepairContextError(
            "Repair Retry????????"
        ) from error

    if normalized_policy_limit < 1:
        raise MissionRepairContextError(
            "Repair Policy Retry???"
            "1????????"
        )

    if normalized_requested_limit < 1:
        raise MissionRepairContextError(
            "Repair Retry???1????????"
        )

    return min(
        normalized_requested_limit,
        normalized_policy_limit,
    )


def build_repair_context(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    repair_request = _load_existing_request(
        mission_id
    )

    if repair_request is None:
        raise MissionRepairContextError(
            "Repair Requestが存在しません。"
        )

    _validate_request(
        mission_id=mission_id,
        repair_request=repair_request,
    )

    retry_limit = _resolve_context_retry_limit(
        repair_request
    )

    repair_plan = _find_repair_plan(
        mission_id=mission_id,
        repair_request=repair_request,
    )

    candidate_paths = (
        _collect_candidate_paths(
            repair_request
        )
    )

    if isinstance(repair_plan, dict):
        _collect_paths_from_value(
            candidate_paths,
            repair_plan.get(
                "selected_files"
            ),
        )

        _collect_paths_from_value(
            candidate_paths,
            repair_plan.get(
                "suspected_files"
            ),
        )

        _collect_paths_from_value(
            candidate_paths,
            repair_plan.get(
                "recommended_files"
            ),
        )

    deduplicated_paths: list[str] = []

    for raw_path in candidate_paths:
        normalized = (
            _normalize_relative_path(
                raw_path
            )
        )

        if normalized is None:
            continue

        if normalized not in (
            deduplicated_paths
        ):
            deduplicated_paths.append(
                normalized
            )

    deduplicated_paths = (
        deduplicated_paths[
            :MAX_CONTEXT_FILES
        ]
    )

    source_files: list[
        dict[str, Any]
    ] = []

    included_bytes = 0

    for relative_path in (
        deduplicated_paths
    ):
        source = _read_source_file(
            relative_path,
            MAX_TOTAL_BYTES
            - included_bytes,
        )

        source_files.append(source)

        if source.get("included"):
            content = source.get(
                "content"
            )

            if isinstance(content, str):
                included_bytes += len(
                    content.encode(
                        "utf-8"
                    )
                )

    created_at = _now()

    context_payload: dict[str, Any] = {
        "repair_context_version": (
            REPAIR_CONTEXT_VERSION
        ),
        "created_at": created_at,
        "mission_id": mission_id,
        "mission": {
            "id": mission.get("id"),
            "title": mission.get("title"),
            "purpose": mission.get(
                "purpose"
            ),
            "status": mission.get(
                "status"
            ),
            "progress": mission.get(
                "progress"
            ),
        },
        "retry": {
            "retry_count": (
                repair_request.get(
                    "retry_count",
                    0,
                )
            ),
            "max_retries": retry_limit,
            "retry_history": (
                repair_request.get(
                    "retry_history",
                    [],
                )
            ),
            "repair_plan_id": (
                repair_request.get(
                    "retry_repair_plan_id"
                )
                or repair_request.get(
                    "repair_plan_id"
                )
            ),
        },
        "repair_request": {
            "request_id": (
                repair_request.get(
                    "request_id"
                )
            ),
            "status": (
                repair_request.get(
                    "status"
                )
            ),
            "next_stage": (
                repair_request.get(
                    "next_stage"
                )
            ),
            "previous_edits": (
                repair_request.get(
                    "edits",
                    [],
                )
            ),
            "apply_result": (
                repair_request.get(
                    "apply_result"
                )
            ),
            "patch_result": (
                repair_request.get(
                    "patch_result"
                )
            ),
            "patch_check_result": (
                repair_request.get(
                    "patch_check_result"
                )
            ),
        },
        "verification": (
            _verification_context(
                repair_request
            )
        ),
        "repair_plan": repair_plan,
        "candidate_paths": (
            deduplicated_paths
        ),
        "source_files": source_files,
        "context_limits": {
            "maximum_files": (
                MAX_CONTEXT_FILES
            ),
            "maximum_file_bytes": (
                MAX_FILE_BYTES
            ),
            "maximum_total_bytes": (
                MAX_TOTAL_BYTES
            ),
            "included_file_count": sum(
                1
                for item in source_files
                if item.get("included")
            ),
            "included_total_bytes": (
                included_bytes
            ),
        },
        "safety_policy": (
            _safety_policy(
                maximum_retry_count=(
                    retry_limit
                )
            )
        ),
        "editor_instruction": {
            "goal": (
                "Verification失敗を修正する"
                "最小差分Editを生成する"
            ),
            "requirements": [
                (
                    "失敗原因に直接関係する"
                    "ファイルだけを変更する"
                ),
                (
                    "前回と同一の失敗済みEditを"
                    "そのまま再利用しない"
                ),
                (
                    "既存コードを可能な限り維持する"
                ),
                (
                    "置換は一意に一致する"
                    "old_textを使用する"
                ),
                (
                    "推測だけで依存関係を"
                    "追加しない"
                ),
                (
                    "判断材料不足時は"
                    "修正を生成せず停止する"
                ),
            ],
            "expected_output": {
                "status": (
                    "EDIT_READYまたは"
                    "INSUFFICIENT_CONTEXT"
                ),
                "reason": "string",
                "edits": [
                    {
                        "operation": (
                            "REPLACE_UNIQUE"
                        ),
                        "path": (
                            "relative/path.py"
                        ),
                        "old_text": "string",
                        "new_text": "string",
                    }
                ],
            },
        },
    }

    canonical = json.dumps(
        context_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    context_id = (
        "repair-context-"
        + _sha256_bytes(canonical)[:16]
    )

    context_payload["context_id"] = (
        context_id
    )

    mission_dir = (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
    )

    archive_path = (
        mission_dir
        / f"{context_id}.json"
    )

    latest_path = (
        mission_dir
        / "repair-context.json"
    )

    existing = _load_json_if_exists(
        latest_path
    )

    duplicate = bool(
        isinstance(existing, dict)
        and existing.get("context_id")
        == context_id
    )

    if not duplicate:
        _write_json_atomic(
            archive_path,
            context_payload,
        )

        _write_json_atomic(
            latest_path,
            context_payload,
        )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_REPAIR_CONTEXT_BUILT"
        ),
        message=(
            "AI Repair Editor用の"
            "Repair Contextを作成しました。"
        ),
        metadata={
            "repair_context_version": (
                REPAIR_CONTEXT_VERSION
            ),
            "context_id": context_id,
            "candidate_file_count": len(
                deduplicated_paths
            ),
            "included_file_count": (
                context_payload[
                    "context_limits"
                ][
                    "included_file_count"
                ]
            ),
            "included_total_bytes": (
                included_bytes
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
        "repair_context": (
            context_payload
        ),
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


def build_repair_context_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return build_repair_context(
            mission_id
        )
    except (
        MissionRepairContextError,
        MissionError,
    ):
        raise
