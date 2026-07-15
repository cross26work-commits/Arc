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
from app.missions.models import MissionTaskUpdate
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

    if result.get("mode") != "DRY_RUN":
        raise MissionImplementationError(
            "Backup EngineはDry Run完了後に"
            "実行してください。"
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
