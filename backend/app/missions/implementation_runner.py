from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database import get_connection
from app.missions.models import (
    MissionPatchApplyRequest,
    MissionPatchCheckRequest,
    MissionTaskUpdate,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
    update_mission_task,
)
from app.projects.reader import EXCLUDED_NAMES


class MissionImplementationError(Exception):
    """Implementation Runnerの実行に失敗した場合の例外。"""


ARC_ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTATION_BACKUP_ROOT = (
    ARC_ROOT
    / "data"
    / "implementation_backups"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_git(
    project_root: Path,
    *arguments: str,
) -> str:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                *arguments,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise MissionImplementationError(
            "Gitコマンドが見つかりません。"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MissionImplementationError(
            "Gitコマンドがタイムアウトしました。"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (
            error.stderr.strip()
            or error.stdout.strip()
            or str(error)
        )
        raise MissionImplementationError(
            f"Git操作に失敗しました: {detail}"
        ) from error

    return completed.stdout.strip()


def _get_project(project_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, path, status
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in mission["tasks"]
            if item["task_type"] == task_type
        ),
        None,
    )

    if task is None:
        raise MissionImplementationError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _load_plan(
    planning_task: dict[str, Any],
) -> dict[str, Any]:
    if not planning_task.get("result"):
        raise MissionImplementationError(
            "PLANNING結果が保存されていません。"
        )

    try:
        plan = json.loads(planning_task["result"])
    except json.JSONDecodeError as error:
        raise MissionImplementationError(
            "PLANNING結果のJSONを読み取れません。"
        ) from error

    if not isinstance(plan, dict):
        raise MissionImplementationError(
            "PLANNING結果の形式が不正です。"
        )

    selected_files = plan.get("selected_files")

    if not isinstance(selected_files, list):
        raise MissionImplementationError(
            "selected_filesが存在しません。"
        )

    if not selected_files:
        raise MissionImplementationError(
            "実装対象ファイルがありません。"
        )

    return plan


def _is_inside_project(
    project_root: Path,
    target: Path,
) -> bool:
    try:
        target.relative_to(project_root)
        return True
    except ValueError:
        return False


def _validate_selected_files(
    *,
    project_root: Path,
    selected_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for index, item in enumerate(
        selected_files,
        start=1,
    ):
        if not isinstance(item, dict):
            raise MissionImplementationError(
                f"selected_files[{index}]の形式が不正です。"
            )

        raw_path = item.get("path")

        if not isinstance(raw_path, str):
            raise MissionImplementationError(
                f"selected_files[{index}]にpathがありません。"
            )

        normalized = raw_path.strip().lstrip("/")

        if not normalized:
            raise MissionImplementationError(
                f"selected_files[{index}]のpathが空です。"
            )

        target = (
            project_root
            / normalized
        ).resolve()

        if not _is_inside_project(
            project_root,
            target,
        ):
            raise MissionImplementationError(
                "プロジェクト外のファイルが"
                f"指定されています: {raw_path}"
            )

        relative_path = target.relative_to(
            project_root
        ).as_posix()

        if any(
            part in EXCLUDED_NAMES
            for part in Path(relative_path).parts
        ):
            raise MissionImplementationError(
                "除外対象のファイルが"
                f"指定されています: {relative_path}"
            )

        if not target.exists():
            raise MissionImplementationError(
                "実装対象ファイルが存在しません: "
                f"{relative_path}"
            )

        if not target.is_file():
            raise MissionImplementationError(
                "実装対象がファイルではありません: "
                f"{relative_path}"
            )

        if relative_path in seen_paths:
            continue

        seen_paths.add(relative_path)

        validated.append(
            {
                "path": relative_path,
                "role": item.get("role"),
                "score": item.get("score"),
                "size_bytes": target.stat().st_size,
            }
        )

    return validated


def _normalize_verification_commands(
    value: Any,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    commands: list[dict[str, str]] = []

    for item in value:
        if isinstance(item, dict):
            name = str(
                item.get("name") or "Verification"
            ).strip()
            command = str(
                item.get("command") or ""
            ).strip()

            if command:
                commands.append(
                    {
                        "name": name,
                        "command": command,
                    }
                )

        elif isinstance(item, str):
            command = item.strip()

            if command:
                commands.append(
                    {
                        "name": "Verification",
                        "command": command,
                    }
                )

    return commands


def _prepare_git_branch(
    *,
    project_root: Path,
    mission_id: int,
) -> dict[str, Any]:
    inside_work_tree = _run_git(
        project_root,
        "rev-parse",
        "--is-inside-work-tree",
    )

    if inside_work_tree != "true":
        raise MissionImplementationError(
            "登録ProjectはGitリポジトリではありません。"
        )

    dirty_status = _run_git(
        project_root,
        "status",
        "--porcelain",
    )

    if dirty_status:
        raise MissionImplementationError(
            "ProjectのGit作業ツリーに"
            "未保存の変更があります。"
        )

    original_branch = _run_git(
        project_root,
        "branch",
        "--show-current",
    )

    original_head = _run_git(
        project_root,
        "rev-parse",
        "HEAD",
    )

    branch_name = f"arc/mission-{mission_id}"

    branch_exists = (
        subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch_name}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        ).returncode
        == 0
    )

    if branch_exists:
        _run_git(
            project_root,
            "switch",
            branch_name,
        )
        branch_created = False
    else:
        _run_git(
            project_root,
            "switch",
            "-c",
            branch_name,
        )
        branch_created = True

    current_branch = _run_git(
        project_root,
        "branch",
        "--show-current",
    )

    if current_branch != branch_name:
        raise MissionImplementationError(
            "Mission専用Branchへの切替を"
            "確認できませんでした。"
        )

    return {
        "original_branch": original_branch,
        "original_head": original_head,
        "branch_name": branch_name,
        "branch_created": branch_created,
        "current_branch": current_branch,
    }


def run_mission_implementation(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionImplementationError(
            "承認済みMissionだけが"
            "Implementation Runnerを実行できます。"
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

    if planning_task["status"] != "COMPLETED":
        raise MissionImplementationError(
            "PLANNING Taskが完了していません。"
        )

    if approval_task["status"] != "COMPLETED":
        raise MissionImplementationError(
            "APPROVAL Taskが完了していません。"
        )

    if implementation_task["status"] not in {
        "READY",
        "RUNNING",
    }:
        raise MissionImplementationError(
            "IMPLEMENTATION Taskは"
            "実行可能な状態ではありません。"
        )

    project = _get_project(
        mission["project_id"]
    )

    if project is None:
        raise MissionImplementationError(
            "Projectが見つかりません。"
        )

    if project["status"] != "active":
        raise MissionImplementationError(
            "非アクティブなProjectは実装できません。"
        )

    project_root = Path(
        project["path"]
    ).expanduser().resolve()

    if not project_root.exists():
        raise MissionImplementationError(
            "Projectフォルダが存在しません。"
        )

    if not project_root.is_dir():
        raise MissionImplementationError(
            "Project Pathがフォルダではありません。"
        )

    plan = _load_plan(planning_task)

    validated_files = _validate_selected_files(
        project_root=project_root,
        selected_files=plan["selected_files"],
    )

    git_result = _prepare_git_branch(
        project_root=project_root,
        mission_id=mission_id,
    )

    verification_commands = (
        _normalize_verification_commands(
            plan.get("verification_commands")
        )
    )

    dry_run = {
        "implementation_version": (
            "mission-implementation-v0.1"
        ),
        "mode": "DRY_RUN",
        "mission_id": mission_id,
        "project_id": project["id"],
        "project_name": project["name"],
        "project_path": str(project_root),
        "plan_version": plan.get("plan_version"),
        "risk": plan.get("risk"),
        "effort": plan.get("effort"),
        "selected_file_count": len(
            validated_files
        ),
        "selected_files": validated_files,
        "verification_commands": (
            verification_commands
        ),
        "git": git_result,
        "write_enabled": False,
        "files_modified": 0,
        "next_stage": (
            "Implementation Runner v0.2で"
            "Backup・Patch生成・File Writeを実装する"
        ),
    }

    result_text = json.dumps(
        dry_run,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionImplementationError(
            "Dry Run結果が保存上限を超えました。"
        )

    updated_mission = update_mission_task(
        mission_id=mission_id,
        task_id=implementation_task["id"],
        payload=MissionTaskUpdate(
            status="RUNNING",
            result=result_text,
            target_path=(
                validated_files[0]["path"]
                if validated_files
                else None
            ),
        ),
    )

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE missions
            SET
                status = 'APPROVED',
                next_action = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                (
                    "Dry Run完了。"
                    "Backup Engineを実行してください。"
                ),
                _now(),
                mission_id,
            ),
        )
        connection.commit()

    updated_mission = get_mission(mission_id)

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_IMPLEMENTATION_DRY_RUN_COMPLETED"
        ),
        message=(
            f"Mission専用Branch "
            f"{git_result['branch_name']} を準備し、"
            f"実装対象{len(validated_files)}件を"
            "検証しました。ファイル変更は"
            "まだ実行していません。"
        ),
        metadata={
            "implementation_version": (
                "mission-implementation-v0.1"
            ),
            "mode": "DRY_RUN",
            "branch_name": (
                git_result["branch_name"]
            ),
            "branch_created": (
                git_result["branch_created"]
            ),
            "selected_file_count": len(
                validated_files
            ),
            "files_modified": 0,
        },
    )

    return {
        "mission": updated_mission,
        "implementation": dry_run,
    }



def _load_implementation_result(
    implementation_task: dict[str, Any],
) -> dict[str, Any]:
    raw_result = implementation_task.get("result")

    if not raw_result:
        raise MissionImplementationError(
            "Implementation Dry Run結果がありません。"
        )

    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError as error:
        raise MissionImplementationError(
            "Implementation結果のJSONを"
            "読み取れません。"
        ) from error

    if not isinstance(result, dict):
        raise MissionImplementationError(
            "Implementation結果の形式が不正です。"
        )

    allowed_modes = {
        "DRY_RUN",
        "BACKUP_READY",
        "PATCH_CHECKED",
    }

    if result.get("mode") not in allowed_modes:
        raise MissionImplementationError(
            "Implementation結果の状態が"
            "現在の処理に対応していません: "
            f"{result.get('mode')}"
        )

    return result


def _safe_backup_target(
    *,
    run_root: Path,
    relative_path: str,
) -> Path:
    before_root = (
        run_root
        / "before"
    ).resolve()

    target = (
        before_root
        / relative_path
    ).resolve()

    if not _is_inside_project(
        before_root,
        target,
    ):
        raise MissionImplementationError(
            "Backup保存先が許可範囲外です。"
        )

    return target


def create_mission_implementation_backup(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionImplementationError(
            "承認済みMissionのみBackup可能です。"
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

    if planning_task["status"] != "COMPLETED":
        raise MissionImplementationError(
            "PLANNING Taskが完了していません。"
        )

    if approval_task["status"] != "COMPLETED":
        raise MissionImplementationError(
            "APPROVAL Taskが完了していません。"
        )

    if implementation_task["status"] != "RUNNING":
        raise MissionImplementationError(
            "Implementation Dry Runが"
            "完了していません。"
        )

    implementation_result = (
        _load_implementation_result(
            implementation_task
        )
    )

    project = _get_project(
        mission["project_id"]
    )

    if project is None:
        raise MissionImplementationError(
            "Projectが見つかりません。"
        )

    project_root = Path(
        project["path"]
    ).expanduser().resolve()

    if not project_root.exists():
        raise MissionImplementationError(
            "Projectフォルダが存在しません。"
        )

    current_branch = _run_git(
        project_root,
        "branch",
        "--show-current",
    )

    expected_branch = (
        implementation_result
        .get("git", {})
        .get("branch_name")
    )

    if current_branch != expected_branch:
        raise MissionImplementationError(
            "Mission専用Branchではありません。"
        )

    dirty_status = _run_git(
        project_root,
        "status",
        "--porcelain",
    )

    if dirty_status:
        raise MissionImplementationError(
            "Projectに未保存の変更があります。"
        )

    selected_files = (
        implementation_result
        .get("selected_files")
    )

    if not isinstance(selected_files, list):
        raise MissionImplementationError(
            "Backup対象ファイルがありません。"
        )

    validated_files = _validate_selected_files(
        project_root=project_root,
        selected_files=selected_files,
    )

    run_id = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%S")
        + "-"
        + uuid4().hex[:8]
    )

    mission_root = (
        IMPLEMENTATION_BACKUP_ROOT
        / f"mission-{mission_id}"
    )

    run_root = (
        mission_root
        / run_id
    )

    if run_root.exists():
        raise MissionImplementationError(
            "同じBackup実行IDが既に存在します。"
        )

    run_root.mkdir(
        parents=True,
        exist_ok=False,
    )

    manifest_files: list[dict[str, Any]] = []

    try:
        for item in validated_files:
            relative_path = item["path"]

            source = (
                project_root
                / relative_path
            ).resolve()

            if not _is_inside_project(
                project_root,
                source,
            ):
                raise MissionImplementationError(
                    "Project外ファイルはBackupできません。"
                )

            data = source.read_bytes()

            backup_target = _safe_backup_target(
                run_root=run_root,
                relative_path=relative_path,
            )

            backup_target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            backup_target.write_bytes(data)

            backup_data = backup_target.read_bytes()

            source_hash = _sha256_bytes(data)
            backup_hash = _sha256_bytes(
                backup_data
            )

            if source_hash != backup_hash:
                raise MissionImplementationError(
                    "BackupファイルのHash検証に"
                    f"失敗しました: {relative_path}"
                )

            manifest_files.append(
                {
                    "path": relative_path,
                    "sha256": source_hash,
                    "size_bytes": len(data),
                    "backup_path": (
                        backup_target
                        .relative_to(run_root)
                        .as_posix()
                    ),
                    "verified": True,
                }
            )

        manifest = {
            "backup_version": (
                "mission-backup-v0.2"
            ),
            "mission_id": mission_id,
            "project_id": project["id"],
            "project_name": project["name"],
            "project_path": str(project_root),
            "run_id": run_id,
            "created_at": _now(),
            "git": {
                "branch": current_branch,
                "head": _run_git(
                    project_root,
                    "rev-parse",
                    "HEAD",
                ),
                "working_tree_clean": True,
            },
            "file_count": len(
                manifest_files
            ),
            "files": manifest_files,
            "restore_ready": True,
        }

        manifest_path = (
            run_root
            / "manifest.json"
        )

        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        stored_manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )

        if (
            stored_manifest["file_count"]
            != len(manifest_files)
        ):
            raise MissionImplementationError(
                "manifest.jsonの検証に失敗しました。"
            )

    except Exception:
        shutil.rmtree(
            run_root,
            ignore_errors=True,
        )
        raise

    updated_result = {
        **implementation_result,
        "implementation_version": (
            "mission-implementation-v0.2"
        ),
        "mode": "BACKUP_READY",
        "backup": {
            "run_id": run_id,
            "root_path": str(run_root),
            "manifest_path": str(
                run_root
                / "manifest.json"
            ),
            "file_count": len(
                manifest_files
            ),
            "restore_ready": True,
        },
        "write_enabled": False,
        "files_modified": 0,
        "next_stage": (
            "Unified Diff生成と"
            "git apply --checkを実行する"
        ),
    }

    result_text = json.dumps(
        updated_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        shutil.rmtree(
            run_root,
            ignore_errors=True,
        )
        raise MissionImplementationError(
            "Backup結果が保存上限を超えました。"
        )

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE mission_tasks
            SET
                result = ?,
                updated_at = ?
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                result_text,
                _now(),
                implementation_task["id"],
                mission_id,
            ),
        )

        connection.execute(
            """
            UPDATE missions
            SET
                status = 'APPROVED',
                next_action = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                (
                    "Backup完了。"
                    "Patch生成・検証へ進んでください。"
                ),
                _now(),
                mission_id,
            ),
        )

        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_IMPLEMENTATION_BACKUP_COMPLETED"
        ),
        message=(
            f"実装対象{len(manifest_files)}件の"
            "変更前Backupを作成し、"
            "SHA-256検証を完了しました。"
        ),
        metadata={
            "backup_version": (
                "mission-backup-v0.2"
            ),
            "run_id": run_id,
            "file_count": len(
                manifest_files
            ),
            "restore_ready": True,
            "files_modified": 0,
        },
    )

    return {
        "mission": get_mission(mission_id),
        "backup": manifest,
        "implementation": updated_result,
    }


def create_mission_implementation_backup_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return create_mission_implementation_backup(
            mission_id
        )
    except MissionImplementationError:
        raise
    except MissionError as error:
        raise MissionImplementationError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionImplementationError(
            "Backup Engineで予期しない"
            f"エラーが発生しました: {error}"
        ) from error



def _load_backup_manifest(
    implementation_result: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    backup = implementation_result.get("backup")

    if not isinstance(backup, dict):
        raise MissionImplementationError(
            "Backup情報が保存されていません。"
        )

    root_path = backup.get("root_path")
    manifest_path = backup.get("manifest_path")

    if not isinstance(root_path, str):
        raise MissionImplementationError(
            "Backup Root Pathが不正です。"
        )

    if not isinstance(manifest_path, str):
        raise MissionImplementationError(
            "Manifest Pathが不正です。"
        )

    run_root = Path(
        root_path
    ).expanduser().resolve()

    manifest_file = Path(
        manifest_path
    ).expanduser().resolve()

    backup_root = (
        IMPLEMENTATION_BACKUP_ROOT
        .expanduser()
        .resolve()
    )

    if not _is_inside_project(
        backup_root,
        run_root,
    ):
        raise MissionImplementationError(
            "Backup保存先がArc管理領域外です。"
        )

    if not _is_inside_project(
        run_root,
        manifest_file,
    ):
        raise MissionImplementationError(
            "ManifestがBackup領域外です。"
        )

    if not manifest_file.exists():
        raise MissionImplementationError(
            "manifest.jsonが存在しません。"
        )

    try:
        manifest = json.loads(
            manifest_file.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise MissionImplementationError(
            "manifest.jsonを読み取れません。"
        ) from error

    if not isinstance(manifest, dict):
        raise MissionImplementationError(
            "manifest.jsonの形式が不正です。"
        )

    if manifest.get("restore_ready") is not True:
        raise MissionImplementationError(
            "Backupが復元可能状態ではありません。"
        )

    return run_root, manifest


def _verify_project_against_manifest(
    *,
    project_root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    files = manifest.get("files")

    if not isinstance(files, list) or not files:
        raise MissionImplementationError(
            "Manifestにファイル情報がありません。"
        )

    verified: list[dict[str, Any]] = []

    for item in files:
        if not isinstance(item, dict):
            raise MissionImplementationError(
                "Manifest内のファイル形式が不正です。"
            )

        relative_path = item.get("path")
        expected_hash = item.get("sha256")

        if not isinstance(relative_path, str):
            raise MissionImplementationError(
                "Manifest内のPathが不正です。"
            )

        if not isinstance(expected_hash, str):
            raise MissionImplementationError(
                "Manifest内のHashが不正です。"
            )

        target = (
            project_root
            / relative_path
        ).resolve()

        if not _is_inside_project(
            project_root,
            target,
        ):
            raise MissionImplementationError(
                "ManifestにProject外Pathがあります。"
            )

        if not target.exists() or not target.is_file():
            raise MissionImplementationError(
                "Backup後に対象ファイルが"
                f"失われています: {relative_path}"
            )

        current_hash = _sha256_bytes(
            target.read_bytes()
        )

        if current_hash != expected_hash:
            raise MissionImplementationError(
                "Backup作成後に対象ファイルが"
                f"変更されています: {relative_path}"
            )

        verified.append(
            {
                "path": relative_path,
                "sha256": current_hash,
                "matched": True,
            }
        )

    return verified


def _extract_patch_paths(
    patch_text: str,
) -> list[str]:
    paths: list[str] = []

    for line in patch_text.splitlines():
        if not line.startswith("diff --git "):
            continue

        parts = line.split()

        if len(parts) != 4:
            raise MissionImplementationError(
                "Unified Diffのdiff --git行が不正です。"
            )

        old_path = parts[2]
        new_path = parts[3]

        if not old_path.startswith("a/"):
            raise MissionImplementationError(
                "Patch旧Pathはa/で始めてください。"
            )

        if not new_path.startswith("b/"):
            raise MissionImplementationError(
                "Patch新Pathはb/で始めてください。"
            )

        old_relative = old_path[2:]
        new_relative = new_path[2:]

        if old_relative != new_relative:
            raise MissionImplementationError(
                "v0.3ではファイル名変更・移動を"
                "許可していません。"
            )

        normalized = (
            old_relative
            .strip()
            .lstrip("/")
        )

        if not normalized:
            raise MissionImplementationError(
                "Patch対象Pathが空です。"
            )

        if normalized not in paths:
            paths.append(normalized)

    if not paths:
        raise MissionImplementationError(
            "Patch内にdiff --git行がありません。"
        )

    return paths


def _validate_patch_text(
    *,
    patch_text: str,
    project_root: Path,
    allowed_paths: set[str],
) -> list[str]:
    normalized_patch = patch_text.replace(
        "\r\n",
        "\n",
    )

    if not normalized_patch.endswith("\n"):
        normalized_patch += "\n"

    forbidden_markers = {
        "GIT binary patch",
        "Binary files ",
        "new file mode ",
        "deleted file mode ",
        "rename from ",
        "rename to ",
        "similarity index ",
    }

    for marker in forbidden_markers:
        if marker in normalized_patch:
            raise MissionImplementationError(
                "v0.3では新規作成・削除・名前変更・"
                f"Binary Patchを許可していません: {marker}"
            )

    patch_paths = _extract_patch_paths(
        normalized_patch
    )

    for relative_path in patch_paths:
        target = (
            project_root
            / relative_path
        ).resolve()

        if not _is_inside_project(
            project_root,
            target,
        ):
            raise MissionImplementationError(
                "PatchにProject外Pathがあります。"
            )

        if any(
            part in EXCLUDED_NAMES
            for part in Path(relative_path).parts
        ):
            raise MissionImplementationError(
                "Patchに除外対象Pathがあります: "
                f"{relative_path}"
            )

        if relative_path not in allowed_paths:
            raise MissionImplementationError(
                "Planner・Backup対象外のファイルは"
                f"変更できません: {relative_path}"
            )

        if not target.exists() or not target.is_file():
            raise MissionImplementationError(
                "Patch対象ファイルが存在しません: "
                f"{relative_path}"
            )

    return patch_paths


def _run_git_apply_check(
    *,
    project_root: Path,
    patch_path: Path,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "apply",
                "--check",
                "--whitespace=error-all",
                str(patch_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as error:
        raise MissionImplementationError(
            "Gitコマンドが見つかりません。"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MissionImplementationError(
            "git apply --checkが"
            "タイムアウトしました。"
        ) from error

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        detail = (
            stderr
            or stdout
            or "詳細なし"
        )

        raise MissionImplementationError(
            "Patch適用可能性検証に失敗しました: "
            f"{detail}"
        )

    return {
        "command": (
            "git apply --check "
            "--whitespace=error-all proposed.patch"
        ),
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "applicable": True,
    }


def check_mission_implementation_patch(
    *,
    mission_id: int,
    payload: MissionPatchCheckRequest,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionImplementationError(
            "承認済みMissionのみPatch検証可能です。"
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
        raise MissionImplementationError(
            "APPROVAL Taskが完了していません。"
        )

    if implementation_task["status"] != "RUNNING":
        raise MissionImplementationError(
            "IMPLEMENTATION Taskが"
            "RUNNINGではありません。"
        )

    implementation_result = (
        _load_implementation_result(
            implementation_task
        )
    )

    if implementation_result.get("mode") not in {
        "BACKUP_READY",
        "PATCH_CHECKED",
    }:
        raise MissionImplementationError(
            "Backup Engine完了後に"
            "Patch検証を実行してください。"
        )

    project = _get_project(
        mission["project_id"]
    )

    if project is None:
        raise MissionImplementationError(
            "Projectが見つかりません。"
        )

    project_root = Path(
        project["path"]
    ).expanduser().resolve()

    if not project_root.exists():
        raise MissionImplementationError(
            "Projectフォルダが存在しません。"
        )

    current_branch = _run_git(
        project_root,
        "branch",
        "--show-current",
    )

    expected_branch = (
        implementation_result
        .get("git", {})
        .get("branch_name")
    )

    if current_branch != expected_branch:
        raise MissionImplementationError(
            "Mission専用Branchではありません。"
        )

    dirty_status = _run_git(
        project_root,
        "status",
        "--porcelain",
    )

    if dirty_status:
        raise MissionImplementationError(
            "Projectに未保存の変更があります。"
        )

    run_root, manifest = (
        _load_backup_manifest(
            implementation_result
        )
    )

    if manifest.get("mission_id") != mission_id:
        raise MissionImplementationError(
            "BackupのMission IDが一致しません。"
        )

    manifest_branch = (
        manifest
        .get("git", {})
        .get("branch")
    )

    if manifest_branch != current_branch:
        raise MissionImplementationError(
            "Backup作成時と現在のBranchが"
            "一致しません。"
        )

    verified_files = (
        _verify_project_against_manifest(
            project_root=project_root,
            manifest=manifest,
        )
    )

    allowed_paths = {
        item["path"]
        for item in manifest["files"]
    }

    patch_text = payload.patch_text.replace(
        "\r\n",
        "\n",
    )

    if not patch_text.endswith("\n"):
        patch_text += "\n"

    patch_paths = _validate_patch_text(
        patch_text=patch_text,
        project_root=project_root,
        allowed_paths=allowed_paths,
    )

    patch_path = (
        run_root
        / "proposed.patch"
    ).resolve()

    if not _is_inside_project(
        run_root,
        patch_path,
    ):
        raise MissionImplementationError(
            "Patch保存先がBackup領域外です。"
        )

    patch_path.write_text(
        patch_text,
        encoding="utf-8",
    )

    patch_hash = _sha256_bytes(
        patch_path.read_bytes()
    )

    apply_check = _run_git_apply_check(
        project_root=project_root,
        patch_path=patch_path,
    )

    check_result = {
        "patch_engine_version": (
            "mission-patch-v0.3"
        ),
        "mission_id": mission_id,
        "checked_at": _now(),
        "generated_by": (
            payload.generated_by.strip()
        ),
        "note": (
            payload.note.strip()
            if payload.note
            else None
        ),
        "patch_path": str(patch_path),
        "patch_sha256": patch_hash,
        "patch_size_bytes": (
            patch_path.stat().st_size
        ),
        "changed_file_count": len(
            patch_paths
        ),
        "changed_files": patch_paths,
        "backup_hash_check": {
            "verified": True,
            "file_count": len(
                verified_files
            ),
        },
        "git_apply_check": apply_check,
        "write_enabled": False,
        "applied": False,
    }

    result_path = (
        run_root
        / "patch_check.json"
    ).resolve()

    result_path.write_text(
        json.dumps(
            check_result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    updated_result = {
        **implementation_result,
        "implementation_version": (
            "mission-implementation-v0.3"
        ),
        "mode": "PATCH_CHECKED",
        "patch": {
            "path": str(patch_path),
            "result_path": str(result_path),
            "sha256": patch_hash,
            "changed_file_count": len(
                patch_paths
            ),
            "changed_files": patch_paths,
            "applicable": True,
            "applied": False,
        },
        "write_enabled": False,
        "files_modified": 0,
        "next_stage": (
            "明示承認後にPatchを実適用する"
        ),
    }

    result_text = json.dumps(
        updated_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionImplementationError(
            "Patch検証結果が保存上限を超えました。"
        )

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE mission_tasks
            SET
                result = ?,
                updated_at = ?
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                result_text,
                _now(),
                implementation_task["id"],
                mission_id,
            ),
        )

        connection.execute(
            """
            UPDATE missions
            SET
                status = 'APPROVED',
                next_action = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                (
                    "Patch検証完了。"
                    "実適用の明示承認を待っています。"
                ),
                _now(),
                mission_id,
            ),
        )

        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_IMPLEMENTATION_PATCH_CHECKED"
        ),
        message=(
            f"変更対象{len(patch_paths)}件の"
            "Unified Diffを検証し、"
            "git apply --checkに成功しました。"
            "実ファイルは変更していません。"
        ),
        metadata={
            "patch_engine_version": (
                "mission-patch-v0.3"
            ),
            "changed_file_count": len(
                patch_paths
            ),
            "changed_files": patch_paths,
            "patch_sha256": patch_hash,
            "applicable": True,
            "applied": False,
            "files_modified": 0,
        },
    )

    return {
        "mission": get_mission(mission_id),
        "patch_check": check_result,
        "implementation": updated_result,
    }


def check_mission_implementation_patch_safe(
    *,
    mission_id: int,
    payload: MissionPatchCheckRequest,
) -> dict[str, Any]:
    try:
        return check_mission_implementation_patch(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionImplementationError:
        raise
    except MissionError as error:
        raise MissionImplementationError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionImplementationError(
            "Patch Engineで予期しない"
            f"エラーが発生しました: {error}"
        ) from error



def _git_changed_paths(
    project_root: Path,
) -> list[str]:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "status",
                "--porcelain=v1",
                "-z",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise MissionImplementationError(
            "Gitコマンドが見つかりません。"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MissionImplementationError(
            "Git状態確認がタイムアウトしました。"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (
            error.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            or str(error)
        )
        raise MissionImplementationError(
            f"Git状態確認に失敗しました: {detail}"
        ) from error

    entries = completed.stdout.split(b"\0")
    paths: list[str] = []
    index = 0

    while index < len(entries):
        entry = entries[index]

        if not entry:
            index += 1
            continue

        decoded = entry.decode(
            "utf-8",
            errors="replace",
        )

        if len(decoded) < 4:
            index += 1
            continue

        status_code = decoded[:2]
        raw_path = decoded[3:]

        if status_code[0] in {"R", "C"}:
            index += 1

            if index >= len(entries):
                raise MissionImplementationError(
                    "Git rename情報の形式が不正です。"
                )

            raw_path = entries[index].decode(
                "utf-8",
                errors="replace",
            )

        normalized = raw_path.strip()

        if normalized and normalized not in paths:
            paths.append(normalized)

        index += 1

    return paths


def _restore_manifest_files(
    *,
    project_root: Path,
    run_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    restored: list[str] = []

    files = manifest.get("files")

    if not isinstance(files, list):
        raise MissionImplementationError(
            "Restore用Manifestが不正です。"
        )

    for item in files:
        relative_path = item.get("path")
        backup_path = item.get("backup_path")
        expected_hash = item.get("sha256")

        if not isinstance(relative_path, str):
            raise MissionImplementationError(
                "Restore対象Pathが不正です。"
            )

        if not isinstance(backup_path, str):
            raise MissionImplementationError(
                "Backup Pathが不正です。"
            )

        source = (
            run_root
            / backup_path
        ).resolve()

        target = (
            project_root
            / relative_path
        ).resolve()

        if not _is_inside_project(
            run_root,
            source,
        ):
            raise MissionImplementationError(
                "Restore元がBackup領域外です。"
            )

        if not _is_inside_project(
            project_root,
            target,
        ):
            raise MissionImplementationError(
                "Restore先がProject領域外です。"
            )

        if not source.exists():
            raise MissionImplementationError(
                "Restore元ファイルがありません: "
                f"{relative_path}"
            )

        data = source.read_bytes()

        if (
            isinstance(expected_hash, str)
            and _sha256_bytes(data) != expected_hash
        ):
            raise MissionImplementationError(
                "Restore元BackupのHashが"
                f"一致しません: {relative_path}"
            )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_bytes(data)

        restored.append(relative_path)

    remaining_changes = _git_changed_paths(
        project_root
    )

    return {
        "restored": True,
        "restored_file_count": len(restored),
        "restored_files": restored,
        "remaining_changes": remaining_changes,
        "working_tree_clean": (
            len(remaining_changes) == 0
        ),
    }


def _apply_patch_transactional(
    *,
    project_root: Path,
    run_root: Path,
    manifest: dict[str, Any],
    patch_path: Path,
    expected_patch_sha256: str,
    expected_changed_paths: list[str],
    simulate_failure_after_apply: bool = False,
) -> dict[str, Any]:
    if not project_root.exists():
        raise MissionImplementationError(
            "Project Rootが存在しません。"
        )

    if not run_root.exists():
        raise MissionImplementationError(
            "Backup Run Rootが存在しません。"
        )

    if not patch_path.exists():
        raise MissionImplementationError(
            "適用対象Patchが存在しません。"
        )

    initial_changes = _git_changed_paths(
        project_root
    )

    if initial_changes:
        raise MissionImplementationError(
            "Patch適用前のGit作業ツリーが"
            f"Cleanではありません: {initial_changes}"
        )

    _verify_project_against_manifest(
        project_root=project_root,
        manifest=manifest,
    )

    actual_patch_sha256 = _sha256_bytes(
        patch_path.read_bytes()
    )

    if actual_patch_sha256 != expected_patch_sha256:
        raise MissionImplementationError(
            "Patch Hashが検証時と一致しません。"
        )

    normalized_expected = sorted(
        set(expected_changed_paths)
    )

    if not normalized_expected:
        raise MissionImplementationError(
            "変更予定ファイルがありません。"
        )

    manifest_paths = {
        item["path"]
        for item in manifest.get("files", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
    }

    unexpected_expected_paths = (
        set(normalized_expected)
        - manifest_paths
    )

    if unexpected_expected_paths:
        raise MissionImplementationError(
            "Backup対象外の変更予定Pathがあります: "
            f"{sorted(unexpected_expected_paths)}"
        )

    _run_git_apply_check(
        project_root=project_root,
        patch_path=patch_path,
    )

    applied = False

    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "apply",
                "--whitespace=error-all",
                str(patch_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if completed.returncode != 0:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "詳細なし"
            )

            raise MissionImplementationError(
                "Patch実適用に失敗しました: "
                f"{detail}"
            )

        applied = True

        changed_paths = sorted(
            _git_changed_paths(
                project_root
            )
        )

        unexpected_paths = (
            set(changed_paths)
            - set(normalized_expected)
        )

        missing_paths = (
            set(normalized_expected)
            - set(changed_paths)
        )

        if unexpected_paths:
            raise MissionImplementationError(
                "想定外ファイルが変更されました: "
                f"{sorted(unexpected_paths)}"
            )

        if missing_paths:
            raise MissionImplementationError(
                "予定ファイルが変更されていません: "
                f"{sorted(missing_paths)}"
            )

        if simulate_failure_after_apply:
            raise MissionImplementationError(
                "自動復元テスト用の模擬失敗です。"
            )

        after_files: list[dict[str, Any]] = []

        before_hash_by_path = {
            item["path"]: item["sha256"]
            for item in manifest["files"]
        }

        for relative_path in changed_paths:
            target = (
                project_root
                / relative_path
            ).resolve()

            if not target.exists():
                raise MissionImplementationError(
                    "適用後ファイルが存在しません: "
                    f"{relative_path}"
                )

            after_hash = _sha256_bytes(
                target.read_bytes()
            )

            before_hash = before_hash_by_path.get(
                relative_path
            )

            if before_hash == after_hash:
                raise MissionImplementationError(
                    "Patch適用後もHashが変化していません: "
                    f"{relative_path}"
                )

            after_files.append(
                {
                    "path": relative_path,
                    "before_sha256": before_hash,
                    "after_sha256": after_hash,
                    "changed": True,
                }
            )

        return {
            "applied": True,
            "rolled_back": False,
            "patch_sha256": actual_patch_sha256,
            "changed_file_count": len(
                changed_paths
            ),
            "changed_files": changed_paths,
            "after_files": after_files,
            "working_tree_clean": False,
        }

    except Exception as error:
        restore_result = _restore_manifest_files(
            project_root=project_root,
            run_root=run_root,
            manifest=manifest,
        )

        if not restore_result["working_tree_clean"]:
            raise MissionImplementationError(
                "Patch適用に失敗し、さらに"
                "自動復元後もGit差分が残っています: "
                f"{restore_result['remaining_changes']}"
            ) from error

        message = str(error)

        if applied:
            message += (
                "／Backupから自動復元しました。"
            )

        raise MissionImplementationError(
            message
        ) from error


def apply_mission_implementation_patch(
    *,
    mission_id: int,
    payload: MissionPatchApplyRequest,
) -> dict[str, Any]:
    if payload.confirmation.strip() != "APPLY_PATCH":
        raise MissionImplementationError(
            "実適用にはconfirmationへ"
            "APPLY_PATCHを指定してください。"
        )

    mission = get_mission(mission_id)

    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionImplementationError(
            "承認済みMissionのみPatch適用可能です。"
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
        raise MissionImplementationError(
            "APPROVAL Taskが完了していません。"
        )

    if implementation_task["status"] != "RUNNING":
        raise MissionImplementationError(
            "IMPLEMENTATION Taskが"
            "RUNNINGではありません。"
        )

    implementation_result = (
        _load_implementation_result(
            implementation_task
        )
    )

    if implementation_result.get("mode") != "PATCH_CHECKED":
        raise MissionImplementationError(
            "Patch Check完了後に"
            "実適用してください。"
        )

    patch_info = implementation_result.get(
        "patch"
    )

    if not isinstance(patch_info, dict):
        raise MissionImplementationError(
            "Patch検証情報がありません。"
        )

    if patch_info.get("applicable") is not True:
        raise MissionImplementationError(
            "適用可能と判定されていないPatchです。"
        )

    if patch_info.get("applied") is True:
        raise MissionImplementationError(
            "このPatchは既に適用済みです。"
        )

    stored_patch_sha256 = patch_info.get(
        "sha256"
    )

    if (
        payload.expected_patch_sha256.strip()
        != stored_patch_sha256
    ):
        raise MissionImplementationError(
            "承認されたPatch Hashが"
            "保存済みHashと一致しません。"
        )

    project = _get_project(
        mission["project_id"]
    )

    if project is None:
        raise MissionImplementationError(
            "Projectが見つかりません。"
        )

    project_root = Path(
        project["path"]
    ).expanduser().resolve()

    current_branch = _run_git(
        project_root,
        "branch",
        "--show-current",
    )

    expected_branch = (
        implementation_result
        .get("git", {})
        .get("branch_name")
    )

    if current_branch != expected_branch:
        raise MissionImplementationError(
            "Mission専用Branchではありません。"
        )

    run_root, manifest = (
        _load_backup_manifest(
            implementation_result
        )
    )

    patch_path_value = patch_info.get("path")

    if not isinstance(patch_path_value, str):
        raise MissionImplementationError(
            "Patch Pathが不正です。"
        )

    patch_path = Path(
        patch_path_value
    ).expanduser().resolve()

    if not _is_inside_project(
        run_root,
        patch_path,
    ):
        raise MissionImplementationError(
            "PatchがBackup Run領域外です。"
        )

    expected_changed_paths = (
        patch_info.get("changed_files")
    )

    if not isinstance(
        expected_changed_paths,
        list,
    ):
        raise MissionImplementationError(
            "変更予定ファイル情報が不正です。"
        )

    apply_result = _apply_patch_transactional(
        project_root=project_root,
        run_root=run_root,
        manifest=manifest,
        patch_path=patch_path,
        expected_patch_sha256=(
            payload.expected_patch_sha256.strip()
        ),
        expected_changed_paths=[
            str(path)
            for path in expected_changed_paths
        ],
    )

    applied_at = _now()

    apply_record = {
        "patch_apply_version": (
            "mission-patch-apply-v0.4"
        ),
        "mission_id": mission_id,
        "applied_at": applied_at,
        "decided_by": payload.decided_by.strip(),
        "note": (
            payload.note.strip()
            if payload.note
            else None
        ),
        **apply_result,
    }

    apply_result_path = (
        run_root
        / "patch_apply.json"
    ).resolve()

    apply_result_path.write_text(
        json.dumps(
            apply_record,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    updated_result = {
        **implementation_result,
        "implementation_version": (
            "mission-implementation-v0.4"
        ),
        "mode": "PATCH_APPLIED",
        "patch": {
            **patch_info,
            "applied": True,
            "applied_at": applied_at,
            "apply_result_path": str(
                apply_result_path
            ),
        },
        "write_enabled": True,
        "files_modified": apply_result[
            "changed_file_count"
        ],
        "modified_files": apply_result[
            "changed_files"
        ],
        "next_stage": (
            "Verification RunnerでBuild・"
            "Lint・Test・Git Diffを検証する"
        ),
    }

    result_text = json.dumps(
        updated_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        _restore_manifest_files(
            project_root=project_root,
            run_root=run_root,
            manifest=manifest,
        )

        raise MissionImplementationError(
            "Patch適用結果が保存上限を超えたため"
            "自動復元しました。"
        )

    updated_mission = update_mission_task(
        mission_id=mission_id,
        task_id=implementation_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
            target_path=(
                apply_result["changed_files"][0]
                if apply_result["changed_files"]
                else None
            ),
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_IMPLEMENTATION_PATCH_APPLIED"
        ),
        message=(
            f"Patchを実適用し、"
            f"{apply_result['changed_file_count']}件の"
            "ファイルを変更しました。"
        ),
        metadata={
            "patch_apply_version": (
                "mission-patch-apply-v0.4"
            ),
            "patch_sha256": (
                apply_result["patch_sha256"]
            ),
            "changed_file_count": (
                apply_result["changed_file_count"]
            ),
            "changed_files": (
                apply_result["changed_files"]
            ),
            "write_enabled": True,
            "applied": True,
        },
    )

    return {
        "mission": updated_mission,
        "patch_apply": apply_record,
        "implementation": updated_result,
    }


def apply_mission_implementation_patch_safe(
    *,
    mission_id: int,
    payload: MissionPatchApplyRequest,
) -> dict[str, Any]:
    try:
        return apply_mission_implementation_patch(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionImplementationError:
        raise
    except MissionError as error:
        raise MissionImplementationError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionImplementationError(
            "Patch Apply Engineで予期しない"
            f"エラーが発生しました: {error}"
        ) from error


def run_mission_implementation_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_mission_implementation(
            mission_id
        )
    except MissionImplementationError:
        raise
    except MissionError as error:
        raise MissionImplementationError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionImplementationError(
            f"Implementation Runnerで"
            f"予期しないエラーが発生しました: {error}"
        ) from error
