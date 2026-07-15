from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

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
