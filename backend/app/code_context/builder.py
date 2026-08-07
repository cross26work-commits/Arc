from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.analyzer.service import (
    FileAnalysisError,
    analyze_project_file,
)
from app.database import DATA_DIR, get_connection
from app.dependencies.service import (
    DependencyGraphError,
    analyze_dependency_tree,
)
from app.projects.reader import (
    ProjectReadError,
    read_project_file,
)


class CodeContextError(Exception):
    """Code Contextの生成・取得失敗。"""


CODE_CONTEXT_VERSION = "mission-code-context-v0.1"

CONTEXT_ROOT = DATA_DIR / "mission-contexts"

MAX_CONTEXT_FILES = 12
MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 1_000_000
MAX_ANALYSIS_RESULT_BYTES = 100_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _mission_context_directory(
    mission_id: int,
) -> Path:
    return CONTEXT_ROOT / f"mission-{mission_id}"


def _context_path(
    mission_id: int,
) -> Path:
    return (
        _mission_context_directory(mission_id)
        / "code-context.json"
    )


def _write_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary.replace(path)


def _load_json(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None

    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(value, dict):
        return None

    return value


def _get_mission_row(
    mission_id: int,
):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                missions.id,
                missions.project_id,
                missions.title,
                missions.objective,
                missions.status,
                missions.progress,
                missions.success_criteria,
                missions.next_action,
                projects.name AS project_name,
                projects.path AS project_path
            FROM missions
            INNER JOIN projects
                ON projects.id = missions.project_id
            WHERE missions.id = ?
            """,
            (mission_id,),
        ).fetchone()


def _get_analysis_task(
    mission_id: int,
):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                status,
                target_path,
                result
            FROM mission_tasks
            WHERE mission_id = ?
              AND task_type = 'ANALYSIS'
            ORDER BY position ASC
            LIMIT 1
            """,
            (mission_id,),
        ).fetchone()



def _get_planning_task(
    mission_id: int,
):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                status,
                target_path,
                result
            FROM mission_tasks
            WHERE mission_id = ?
              AND task_type = 'PLANNING'
            ORDER BY position ASC
            LIMIT 1
            """,
            (mission_id,),
        ).fetchone()

def _normalize_relative_path(
    value: Any,
) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = (
        value.strip()
        .replace("\\", "/")
        .lstrip("/")
    )

    if not normalized:
        return None

    path = Path(normalized)

    if path.is_absolute():
        return None

    if ".." in path.parts:
        return None

    return path.as_posix()


def _parse_analysis_result(
    raw_result: Any,
) -> dict[str, Any]:
    if not isinstance(raw_result, str):
        return {}

    if not raw_result.strip():
        return {}

    encoded = raw_result.encode("utf-8")

    if len(encoded) > MAX_ANALYSIS_RESULT_BYTES:
        raw_result = encoded[
            :MAX_ANALYSIS_RESULT_BYTES
        ].decode(
            "utf-8",
            errors="ignore",
        )

    try:
        value = json.loads(raw_result)
    except json.JSONDecodeError:
        return {
            "raw_result": raw_result,
            "parse_error": True,
        }

    if not isinstance(value, dict):
        return {}

    return value


def _parse_planning_result(
    raw_result: Any,
) -> dict[str, Any]:
    if not isinstance(raw_result, str):
        return {}

    if not raw_result.strip():
        return {}

    try:
        value = json.loads(raw_result)
    except json.JSONDecodeError:
        return {}

    if not isinstance(value, dict):
        return {}

    return value


def _planning_file_operations(
    planning: dict[str, Any],
) -> dict[str, str]:
    typed_plan = planning.get("typed_plan")

    if not isinstance(typed_plan, dict):
        return {}

    selected_files = typed_plan.get(
        "selected_files"
    )

    if not isinstance(selected_files, list):
        return {}

    operations: dict[str, str] = {}

    for item in selected_files:
        if not isinstance(item, dict):
            continue

        relative_path = _normalize_relative_path(
            item.get("path")
        )

        if relative_path is None:
            continue

        operation = str(
            item.get("operation")
            or "UPDATE"
        ).strip().upper()

        if operation not in {
            "CREATE",
            "UPDATE",
        }:
            continue

        operations[relative_path] = operation

    return operations

def _candidate_paths_from_analysis(
    analysis: dict[str, Any],
) -> list[str]:
    paths: list[str] = []

    candidates = analysis.get("candidates")

    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            normalized = _normalize_relative_path(
                candidate.get("path")
            )

            if (
                normalized is not None
                and normalized not in paths
            ):
                paths.append(normalized)

    for key in (
        "api_files",
        "frontend_files",
        "backend_files",
    ):
        values = analysis.get(key)

        if not isinstance(values, list):
            continue

        for value in values:
            normalized = _normalize_relative_path(
                value
            )

            if (
                normalized is not None
                and normalized not in paths
            ):
                paths.append(normalized)

    return paths[:MAX_CONTEXT_FILES]


def _analysis_candidate_map(
    analysis: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    candidates = analysis.get("candidates")

    if not isinstance(candidates, list):
        return result

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        path = _normalize_relative_path(
            candidate.get("path")
        )

        if path is None:
            continue

        result[path] = candidate

    return result


def _read_context_source(
    *,
    project_path: str,
    relative_path: str,
    remaining_bytes: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "relative_path": relative_path,
        "exists": False,
        "included": False,
        "truncated": False,
        "size_bytes": None,
        "included_bytes": 0,
        "sha256": None,
        "language": None,
        "content": None,
        "error": None,
    }

    try:
        file_data = read_project_file(
            project_path=project_path,
            relative_path=relative_path,
        )
    except ProjectReadError as error:
        result["error"] = str(error)
        return result

    content = file_data.get("content")

    if not isinstance(content, str):
        result["error"] = "ファイル本文を取得できません。"
        return result

    raw_bytes = content.encode("utf-8")

    result["exists"] = True
    result["size_bytes"] = file_data.get(
        "size_bytes",
        len(raw_bytes),
    )
    result["language"] = file_data.get(
        "language"
    )
    result["sha256"] = _sha256_bytes(raw_bytes)

    allowed_bytes = min(
        MAX_FILE_BYTES,
        max(remaining_bytes, 0),
    )

    if allowed_bytes <= 0:
        result["error"] = (
            "TOTAL_CONTEXT_LIMIT_REACHED"
        )
        return result

    selected = raw_bytes[:allowed_bytes]

    if len(selected) < len(raw_bytes):
        result["truncated"] = True

    result["content"] = selected.decode(
        "utf-8",
        errors="replace",
    )
    result["included"] = True
    result["included_bytes"] = len(selected)

    return result


def _analyze_context_file(
    *,
    project_path: str,
    relative_path: str,
) -> dict[str, Any]:
    try:
        analysis = analyze_project_file(
            project_path=project_path,
            relative_path=relative_path,
        )
    except FileAnalysisError as error:
        return {
            "analysis_error": str(error),
        }

    return {
        "analysis_engine": analysis.get(
            "analysis_engine"
        ),
        "summary": analysis.get("summary"),
        "role": analysis.get("role"),
        "language": analysis.get("language"),
        "metrics": analysis.get("metrics"),
        "imports": analysis.get("imports", [])[:100],
        "functions": analysis.get(
            "functions",
            [],
        )[:100],
        "classes": analysis.get(
            "classes",
            [],
        )[:100],
        "routes": analysis.get("routes", [])[:50],
        "components": analysis.get(
            "components",
            [],
        )[:100],
        "api_calls": analysis.get(
            "api_calls",
            [],
        )[:100],
        "sdk_calls": analysis.get(
            "sdk_calls",
            [],
        )[:100],
        "hooks": analysis.get("hooks", [])[:100],
        "calls": analysis.get("calls", [])[:200],
        "dependencies": analysis.get(
            "dependencies",
            [],
        )[:100],
        "todos": analysis.get("todos", [])[:100],
        "warnings": analysis.get(
            "warnings",
            [],
        )[:100],
    }


def _dependency_context(
    *,
    project_path: str,
    relative_path: str,
) -> dict[str, Any]:
    try:
        dependency = analyze_dependency_tree(
            project_path=project_path,
            target_path=relative_path,
            direction="both",
            max_files=3000,
            max_depth=3,
            max_nodes=150,
        )
    except DependencyGraphError as error:
        return {
            "dependency_error": str(error),
        }

    return {
        "analysis_engine": dependency.get(
            "analysis_engine"
        ),
        "summary": dependency.get("summary"),
        "direct_dependencies": dependency.get(
            "direct_dependencies",
            [],
        )[:50],
        "direct_dependents": dependency.get(
            "direct_dependents",
            [],
        )[:50],
        "affected_files": dependency.get(
            "affected_files",
            [],
        )[:100],
        "risk": dependency.get("risk"),
        "dependency_tree": dependency.get(
            "dependency_tree"
        ),
        "dependent_tree": dependency.get(
            "dependent_tree"
        ),
    }


def _add_mission_log(
    *,
    mission_id: int,
    event_type: str,
    message: str,
    metadata: dict[str, Any],
) -> None:
    try:
        metadata_text = json.dumps(
            metadata,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO mission_logs (
                    mission_id,
                    level,
                    event_type,
                    message,
                    metadata,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mission_id,
                    "INFO",
                    event_type,
                    message,
                    metadata_text,
                    _now(),
                ),
            )
            connection.commit()
    except Exception:
        # Context生成自体をログ失敗で中断させない。
        return


def build_code_context(
    mission_id: int,
) -> dict[str, Any]:
    mission = _get_mission_row(mission_id)

    if mission is None:
        raise CodeContextError(
            "Missionが見つかりません。"
        )

    analysis_task = _get_analysis_task(
        mission_id
    )

    if analysis_task is None:
        raise CodeContextError(
            "ANALYSIS Taskが見つかりません。"
        )

    if analysis_task["status"] != "COMPLETED":
        raise CodeContextError(
            "Code Context生成にはANALYSIS Taskの"
            "完了が必要です。"
        )

    analysis = _parse_analysis_result(
        analysis_task["result"]
    )

    candidate_paths = (
        _candidate_paths_from_analysis(
            analysis
        )
    )

    planning_task = _get_planning_task(
        mission_id
    )

    planning: dict[str, Any] = {}
    planning_operations: dict[str, str] = {}

    if (
        planning_task is not None
        and planning_task["status"] == "COMPLETED"
    ):
        planning = _parse_planning_result(
            planning_task["result"]
        )
        planning_operations = (
            _planning_file_operations(
                planning
            )
        )

        for planned_path in planning_operations:
            if planned_path not in candidate_paths:
                candidate_paths.append(
                    planned_path
                )

    if not candidate_paths:
        target_path = _normalize_relative_path(
            analysis_task["target_path"]
        )

        if target_path is not None:
            candidate_paths = [target_path]

    if not candidate_paths:
        raise CodeContextError(
            "No related file candidates were found."
        )

    candidate_map = _analysis_candidate_map(
        analysis
    )

    context_files: list[dict[str, Any]] = []
    included_total_bytes = 0

    for relative_path in candidate_paths:
        operation = planning_operations.get(
            relative_path,
            "UPDATE",
        )

        if operation == "CREATE":
            source = {
                "relative_path": relative_path,
                "exists": False,
                "included": True,
                "truncated": False,
                "size_bytes": 0,
                "included_bytes": 0,
                "sha256": None,
                "language": None,
                "content": "",
                "error": None,
                "operation": "CREATE",
                "virtual": True,
            }
        else:
            source = _read_context_source(
                project_path=mission["project_path"],
                relative_path=relative_path,
                remaining_bytes=(
                    MAX_TOTAL_BYTES
                    - included_total_bytes
                ),
            )
            source["operation"] = operation
            source["virtual"] = False

        included_total_bytes += int(
            source.get("included_bytes") or 0
        )

        static_analysis = _analyze_context_file(
            project_path=mission["project_path"],
            relative_path=relative_path,
        )

        dependency = _dependency_context(
            project_path=mission["project_path"],
            relative_path=relative_path,
        )

        context_files.append(
            {
                "relative_path": relative_path,
                "candidate": candidate_map.get(
                    relative_path,
                    {},
                ),
                "source": source,
                "static_analysis": static_analysis,
                "dependency": dependency,
            }
        )

    created_at = _now()

    payload: dict[str, Any] = {
        "context_version": CODE_CONTEXT_VERSION,
        "created_at": created_at,
        "mission_id": mission_id,
        "project": {
            "id": mission["project_id"],
            "name": mission["project_name"],
            "path": mission["project_path"],
        },
        "mission": {
            "id": mission["id"],
            "title": mission["title"],
            "objective": mission["objective"],
            "status": mission["status"],
            "progress": mission["progress"],
            "success_criteria": mission[
                "success_criteria"
            ],
            "next_action": mission["next_action"],
        },
        "analysis": {
            "task_id": analysis_task["id"],
            "task_status": analysis_task["status"],
            "analysis_version": analysis.get(
                "analysis_version"
            ),
            "search_terms": analysis.get(
                "search_terms",
                [],
            ),
            "candidate_count": len(
                candidate_paths
            ),
            "high_risk_count": analysis.get(
                "high_risk_count",
                0,
            ),
            "medium_risk_count": analysis.get(
                "medium_risk_count",
                0,
            ),
        },
        "limits": {
            "maximum_context_files": (
                MAX_CONTEXT_FILES
            ),
            "maximum_file_bytes": MAX_FILE_BYTES,
            "maximum_total_bytes": MAX_TOTAL_BYTES,
        },
        "summary": {
            "candidate_file_count": len(
                candidate_paths
            ),
            "included_file_count": sum(
                1
                for item in context_files
                if item["source"].get("included")
            ),
            "included_total_bytes": (
                included_total_bytes
            ),
            "truncated_file_count": sum(
                1
                for item in context_files
                if item["source"].get("truncated")
            ),
            "analysis_error_count": sum(
                1
                for item in context_files
                if item["static_analysis"].get(
                    "analysis_error"
                )
            ),
            "dependency_error_count": sum(
                1
                for item in context_files
                if item["dependency"].get(
                    "dependency_error"
                )
            ),
        },
        "files": context_files,
        "safety": {
            "read_only": True,
            "patch_applied": False,
            "files_modified": False,
            "shell_execution": False,
            "context_root": str(CONTEXT_ROOT),
        },
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    payload["context_sha256"] = _sha256_text(
        canonical
    )

    path = _context_path(mission_id)

    _write_json_atomic(
        path,
        payload,
    )

    response = {
        **payload,
        "storage": {
            "path": str(path),
            "exists": path.exists(),
        },
    }

    _add_mission_log(
        mission_id=mission_id,
        event_type="CODE_CONTEXT_CREATED",
        message="Code Contextを生成しました。",
        metadata={
            "context_version": (
                CODE_CONTEXT_VERSION
            ),
            "context_sha256": (
                payload["context_sha256"]
            ),
            "candidate_file_count": len(
                candidate_paths
            ),
            "included_total_bytes": (
                included_total_bytes
            ),
        },
    )

    return response


def get_code_context(
    mission_id: int,
) -> dict[str, Any]:
    mission = _get_mission_row(mission_id)

    if mission is None:
        raise CodeContextError(
            "Missionが見つかりません。"
        )

    path = _context_path(mission_id)
    payload = _load_json(path)

    if payload is None:
        raise CodeContextError(
            "Code Contextがまだ生成されていません。"
        )

    return {
        **payload,
        "storage": {
            "path": str(path),
            "exists": True,
        },
    }


def build_code_context_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return build_code_context(mission_id)
    except CodeContextError:
        raise
    except Exception as error:
        raise CodeContextError(
            f"Code Context生成に失敗しました: {error}"
        ) from error


def get_code_context_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return get_code_context(mission_id)
    except CodeContextError:
        raise
    except Exception as error:
        raise CodeContextError(
            f"Code Context取得に失敗しました: {error}"
        ) from error
