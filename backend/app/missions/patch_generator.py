from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from app.missions.implementation_runner import (
    MissionImplementationError,
    _get_project,
    _is_inside_project,
    _load_backup_manifest,
    _load_implementation_result,
    _sha256_bytes,
    _task_by_type,
    _verified_completed_step_paths,
    _verify_project_against_manifest,
    check_mission_implementation_patch_safe,
)
from app.missions.models import (
    MissionPatchCheckRequest,
    MissionPatchEdit,
    MissionPatchGenerateRequest,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)
from app.projects.reader import EXCLUDED_NAMES


class MissionPatchGeneratorError(Exception):
    """Patch Generatorの処理に失敗した場合の例外。"""


def _normalize_relative_path(
    *,
    project_root: Path,
    raw_path: str,
) -> str:
    normalized = raw_path.strip().lstrip("/")

    if not normalized:
        raise MissionPatchGeneratorError(
            "編集対象Pathが空です。"
        )

    target = (
        project_root
        / normalized
    ).resolve()

    if not _is_inside_project(
        project_root,
        target,
    ):
        raise MissionPatchGeneratorError(
            "Project外のPathは編集できません。"
        )

    relative_path = target.relative_to(
        project_root
    ).as_posix()

    if any(
        part in EXCLUDED_NAMES
        for part in Path(relative_path).parts
    ):
        raise MissionPatchGeneratorError(
            "除外対象Pathは編集できません: "
            f"{relative_path}"
        )

    if not target.exists():
        raise MissionPatchGeneratorError(
            "編集対象ファイルが存在しません: "
            f"{relative_path}"
        )

    if not target.is_file():
        raise MissionPatchGeneratorError(
            "編集対象はファイルではありません: "
            f"{relative_path}"
        )

    return relative_path


def _require_text(
    value: str | None,
    *,
    field_name: str,
) -> str:
    if value is None:
        raise MissionPatchGeneratorError(
            f"{field_name}を指定してください。"
        )

    if value == "":
        raise MissionPatchGeneratorError(
            f"{field_name}は空にできません。"
        )

    return value


def _detect_newline(content: str) -> str:
    """対象ファイルで主に使用されている改行コードを返す。"""
    if "\r\n" in content:
        return "\r\n"

    return "\n"


def _normalize_edit_newlines(
    value: str,
    *,
    newline: str,
) -> str:
    """編集文字列を対象ファイルの改行コードへ合わせる。"""
    normalized = (
        value
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    if newline == "\r\n":
        return normalized.replace("\n", "\r\n")

    return normalized


def _detect_newline(content: str) -> str:
    """?????????????????????????"""
    if "\r\n" in content:
        return "\r\n"

    return "\n"


def _normalize_edit_newlines(
    value: str,
    *,
    newline: str,
) -> str:
    """????????????????????????"""
    normalized = (
        value
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    if newline == "\r\n":
        return normalized.replace("\n", "\r\n")

    return normalized


def _apply_single_edit(
    *,
    content: str,
    edit: MissionPatchEdit,
) -> str:
    operation = edit.operation
    newline = _detect_newline(content)

    if operation == "REPLACE_UNIQUE":
        old_text = _require_text(
            edit.old_text,
            field_name="old_text",
        )

        new_text = _require_text(
            edit.new_text,
            field_name="new_text",
        )

        old_text = _normalize_edit_newlines(
            old_text,
            newline=newline,
        )
        new_text = _normalize_edit_newlines(
            new_text,
            newline=newline,
        )

        count = content.count(old_text)

        if count == 0:
            raise MissionPatchGeneratorError(
                "REPLACE_UNIQUE old_text was not found. "
                f"path={edit.path!r} "
                f"old_text_preview={old_text[:200]!r}"
            )

        if count != 1:
            raise MissionPatchGeneratorError(
                "REPLACE_UNIQUE????"
                f"1???????????: {count}?"
            )

        return content.replace(
            old_text,
            new_text,
            1,
        )

    if operation == "APPEND":
        append_text = _require_text(
            edit.text,
            field_name="text",
        )

        append_text = _normalize_edit_newlines(
            append_text,
            newline=newline,
        )

        base = content

        if base and not base.endswith(
            ("\n", "\r")
        ):
            base += newline

        return base + append_text

    if operation in {
        "INSERT_BEFORE",
        "INSERT_AFTER",
    }:
        anchor = _require_text(
            edit.anchor,
            field_name="anchor",
        )

        insertion = _require_text(
            edit.text,
            field_name="text",
        )

        anchor = _normalize_edit_newlines(
            anchor,
            newline=newline,
        )
        insertion = _normalize_edit_newlines(
            insertion,
            newline=newline,
        )

        count = content.count(anchor)

        if count == 0:
            raise MissionPatchGeneratorError(
                "??Anchor?????????"
            )

        if count != 1:
            raise MissionPatchGeneratorError(
                "??Anchor?1???????????: "
                f"{count}?"
            )

        if operation == "INSERT_BEFORE":
            replacement = insertion + anchor
        else:
            replacement = anchor + insertion

        return content.replace(
            anchor,
            replacement,
            1,
        )

    raise MissionPatchGeneratorError(
        f"??????????: {operation}"
    )


def generate_unified_patch(
    *,
    project_root: Path,
    allowed_paths: set[str],
    edits: list[MissionPatchEdit],
) -> dict[str, Any]:
    project_root = project_root.resolve()

    if not edits:
        raise MissionPatchGeneratorError(
            "編集指示がありません。"
        )

    grouped: dict[str, list[MissionPatchEdit]] = {}

    for edit in edits:
        relative_path = _normalize_relative_path(
            project_root=project_root,
            raw_path=edit.path,
        )

        if relative_path not in allowed_paths:
            raise MissionPatchGeneratorError(
                "Planner・Backup対象外のファイルは"
                f"編集できません: {relative_path}"
            )

        grouped.setdefault(
            relative_path,
            [],
        ).append(edit)

    patch_parts: list[str] = []
    file_results: list[dict[str, Any]] = []

    for relative_path, file_edits in grouped.items():
        target = (
            project_root
            / relative_path
        ).resolve()

        original_bytes = target.read_bytes()
        original = original_bytes.decode(
            "utf-8",
            errors="strict",
        )

        modified = original

        for edit in file_edits:
            modified = _apply_single_edit(
                content=modified,
                edit=edit,
            )

        if modified == original:
            raise MissionPatchGeneratorError(
                "編集後の内容が変更前と同一です: "
                f"{relative_path}"
            )

        diff_body = "".join(
            difflib.unified_diff(
                original.splitlines(
                    keepends=True
                ),
                modified.splitlines(
                    keepends=True
                ),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )

        if not diff_body:
            raise MissionPatchGeneratorError(
                "Unified Diffを生成できませんでした: "
                f"{relative_path}"
            )

        patch_parts.append(
            (
                f"diff --git a/{relative_path} "
                f"b/{relative_path}\n"
                + diff_body
            )
        )

        file_results.append(
            {
                "path": relative_path,
                "edit_count": len(file_edits),
                "before_sha256": _sha256_bytes(
                    original_bytes
                ),
                "after_sha256": _sha256_bytes(
                    modified.encode("utf-8")
                ),
                "before_size_bytes": len(
                    original_bytes
                ),
                "after_size_bytes": len(
                    modified.encode("utf-8")
                ),
            }
        )

    patch_text = "".join(patch_parts)

    # Unified Diff??????????????
    # LF?????????????
    patch_text = (
        patch_text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    if not patch_text.endswith("\n"):
        patch_text += "\n"

    return {
        "generator_version": (
            "mission-patch-generator-v0.1"
        ),
        "patch_text": patch_text,
        "changed_file_count": len(
            file_results
        ),
        "changed_files": [
            item["path"]
            for item in file_results
        ],
        "files": file_results,
        "operation_count": len(edits),
    }


def generate_mission_patch(
    *,
    mission_id: int,
    payload: MissionPatchGenerateRequest,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionPatchGeneratorError(
            "承認済みMissionのみPatch生成可能です。"
        )

    approval_task = _task_by_type(
        mission,
        "APPROVAL",
    )
    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )

    if approval_task["status"] != "COMPLETED":
        raise MissionPatchGeneratorError(
            "APPROVAL Taskが完了していません。"
        )

    if implementation_task["status"] not in {
        "READY",
        "RUNNING",
    }:
        raise MissionPatchGeneratorError(
            "IMPLEMENTATION Taskが"
            "Patch生成可能な状態ではありません。"
        )

    implementation_result = (
        _load_implementation_result(
            implementation_task
        )
    )

    allowed_modes = {
        "BACKUP_READY",
        "PATCH_CHECKED",
        "ROLLED_BACK",
    }

    if (
        implementation_result.get("mode")
        not in allowed_modes
    ):
        raise MissionPatchGeneratorError(
            "Backup完了後、またはRollback後に"
            "Patchを生成してください。"
        )

    project = _get_project(
        mission["project_id"]
    )

    if project is None:
        raise MissionPatchGeneratorError(
            "Projectが見つかりません。"
        )

    project_root = Path(
        project["path"]
    ).expanduser().resolve()

    run_root, manifest = (
        _load_backup_manifest(
            implementation_result
        )
    )

    completed_step_paths = (
        _verified_completed_step_paths(
            implementation_result
        )
    )

    _verify_project_against_manifest(
        project_root=project_root,
        manifest=manifest,
        allowed_changed_paths=(
            completed_step_paths
        ),
    )

    allowed_paths = {
        item["path"]
        for item in manifest.get("files", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
    }

    generated = generate_unified_patch(
        project_root=project_root,
        allowed_paths=allowed_paths,
        edits=payload.edits,
    )

    generator_result = {
        **generated,
        "mission_id": mission_id,
        "project_id": project["id"],
        "project_name": project["name"],
        "generated_by": (
            payload.generated_by.strip()
        ),
        "note": (
            payload.note.strip()
            if payload.note
            else None
        ),
    }

    generator_path = (
        run_root
        / "patch_generator.json"
    ).resolve()

    if not _is_inside_project(
        run_root,
        generator_path,
    ):
        raise MissionPatchGeneratorError(
            "Generator結果保存先が不正です。"
        )

    generator_path.write_text(
        json.dumps(
            {
                key: value
                for key, value
                in generator_result.items()
                if key != "patch_text"
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    checked = (
        check_mission_implementation_patch_safe(
            mission_id=mission_id,
            payload=MissionPatchCheckRequest(
                patch_text=generated["patch_text"],
                generated_by=(
                    payload.generated_by.strip()
                ),
                note=(
                    payload.note.strip()
                    if payload.note
                    else (
                        "Patch Generator v0.1により"
                        "生成されたPatch"
                    )
                ),
            ),
        )
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_PATCH_GENERATED"
        ),
        message=(
            f"安全編集操作{len(payload.edits)}件から"
            f"{generated['changed_file_count']}件の"
            "Unified Diffを生成し、"
            "Patch Checkに成功しました。"
        ),
        metadata={
            "generator_version": (
                "mission-patch-generator-v0.1"
            ),
            "operation_count": len(
                payload.edits
            ),
            "changed_file_count": (
                generated["changed_file_count"]
            ),
            "changed_files": (
                generated["changed_files"]
            ),
            "generator_result_path": str(
                generator_path
            ),
            "patch_applicable": True,
            "patch_applied": False,
        },
    )

    return {
        "mission": checked["mission"],
        "generator": {
            **generator_result,
            "result_path": str(
                generator_path
            ),
        },
        "patch_check": checked[
            "patch_check"
        ],
        "implementation": checked[
            "implementation"
        ],
    }


def generate_mission_patch_safe(
    *,
    mission_id: int,
    payload: MissionPatchGenerateRequest,
) -> dict[str, Any]:
    try:
        return generate_mission_patch(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionPatchGeneratorError:
        raise
    except MissionImplementationError as error:
        raise MissionPatchGeneratorError(
            str(error)
        ) from error
    except MissionError as error:
        raise MissionPatchGeneratorError(
            str(error)
        ) from error
    except UnicodeDecodeError as error:
        raise MissionPatchGeneratorError(
            "対象ファイルはUTF-8として"
            "読み取れません。"
        ) from error
    except Exception as error:
        raise MissionPatchGeneratorError(
            "Patch Generatorで予期しない"
            f"エラーが発生しました: {error}"
        ) from error
