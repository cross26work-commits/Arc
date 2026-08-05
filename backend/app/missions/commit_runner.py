from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.missions.models import MissionCommitRequest
from app.missions.implementation_runner import (
    _verified_completed_step_paths,
)

from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionCommitError(Exception):
    """Mission Commit処理に失敗した場合の例外。"""


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


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
        raise MissionCommitError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _load_result(
    task: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    raw = task.get("result")

    if not raw:
        raise MissionCommitError(
            f"{label}結果が保存されていません。"
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MissionCommitError(
            f"{label}結果のJSONを読み取れません。"
        ) from error

    if not isinstance(result, dict):
        raise MissionCommitError(
            f"{label}結果の形式が不正です。"
        )

    return result


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
            timeout=60,
        )
    except FileNotFoundError as error:
        raise MissionCommitError(
            "Gitコマンドが見つかりません。"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MissionCommitError(
            "Git操作がタイムアウトしました。"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (
            error.stderr.strip()
            or error.stdout.strip()
            or str(error)
        )

        raise MissionCommitError(
            f"Git操作に失敗しました: {detail}"
        ) from error

    return completed.stdout.strip()


def _changed_paths(
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
    except subprocess.CalledProcessError as error:
        raise MissionCommitError(
            "Git変更ファイルを取得できません。"
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
                raise MissionCommitError(
                    "Git rename情報が不正です。"
                )

            raw_path = entries[index].decode(
                "utf-8",
                errors="replace",
            )

        if raw_path and raw_path not in paths:
            paths.append(raw_path)

        index += 1

    return paths


def commit_verified_changes(
    *,
    project_root: Path,
    branch_name: str,
    allowed_paths: list[str],
    message: str,
) -> dict[str, Any]:
    project_root = project_root.resolve()

    current_branch = _run_git(
        project_root,
        "branch",
        "--show-current",
    )

    if current_branch != branch_name:
        raise MissionCommitError(
            "Mission専用Branchではありません。"
        )

    changed_paths = sorted(
        _changed_paths(project_root)
    )

    if not changed_paths:
        raise MissionCommitError(
            "Commit対象の変更がありません。"
        )

    allowed_set = set(allowed_paths)
    unexpected = (
        set(changed_paths)
        - allowed_set
    )

    if unexpected:
        raise MissionCommitError(
            "想定外ファイルが変更されています: "
            f"{sorted(unexpected)}"
        )

    _run_git(
        project_root,
        "diff",
        "--check",
    )

    for relative_path in changed_paths:
        _run_git(
            project_root,
            "add",
            "--",
            relative_path,
        )

    staged_paths = [
        path
        for path in _run_git(
            project_root,
            "diff",
            "--cached",
            "--name-only",
        ).splitlines()
        if path
    ]

    if sorted(staged_paths) != changed_paths:
        _run_git(
            project_root,
            "reset",
        )

        raise MissionCommitError(
            "Stage対象と変更対象が一致しません。"
        )

    try:
        _run_git(
            project_root,
            "commit",
            "-m",
            message,
        )
    except Exception:
        try:
            _run_git(
                project_root,
                "reset",
            )
        except Exception:
            pass

        raise

    commit_hash = _run_git(
        project_root,
        "rev-parse",
        "HEAD",
    )

    commit_subject = _run_git(
        project_root,
        "log",
        "-1",
        "--pretty=%s",
    )

    remaining_changes = _changed_paths(
        project_root
    )

    if remaining_changes:
        raise MissionCommitError(
            "Commit後もGit差分が残っています: "
            f"{remaining_changes}"
        )

    return {
        "commit_runner_version": (
            "mission-commit-v0.1"
        ),
        "committed": True,
        "branch": branch_name,
        "commit_hash": commit_hash,
        "commit_subject": commit_subject,
        "changed_file_count": len(
            changed_paths
        ),
        "changed_files": changed_paths,
        "working_tree_clean": True,
    }


def commit_mission_changes(
    *,
    mission_id: int,
    payload: MissionCommitRequest,
) -> dict[str, Any]:
    if payload.confirmation.strip() != "COMMIT_CHANGES":
        raise MissionCommitError(
            "Commitにはconfirmationへ"
            "COMMIT_CHANGESを指定してください。"
        )

    mission = get_mission(mission_id)

    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    if implementation_task["status"] != "COMPLETED":
        raise MissionCommitError(
            "IMPLEMENTATION Taskが"
            "完了していません。"
        )

    if verification_task["status"] != "COMPLETED":
        raise MissionCommitError(
            "VERIFICATION Taskが"
            "完了していません。"
        )

    implementation = _load_result(
        implementation_task,
        label="IMPLEMENTATION",
    )

    verification = _load_result(
        verification_task,
        label="VERIFICATION",
    )

    if implementation.get("mode") != "PATCH_APPLIED":
        raise MissionCommitError(
            "Patch適用済み状態ではありません。"
        )

    if verification.get("passed") is not True:
        raise MissionCommitError(
            "Verificationが成功していません。"
        )

    project = _get_project(
        mission["project_id"]
    )

    if project is None:
        raise MissionCommitError(
            "Projectが見つかりません。"
        )

    project_root = Path(
        project["path"]
    ).expanduser().resolve()

    git_info = implementation.get("git")

    if not isinstance(git_info, dict):
        raise MissionCommitError(
            "Git情報が保存されていません。"
        )

    branch_name = git_info.get("branch_name")

    if not isinstance(branch_name, str):
        raise MissionCommitError(
            "Mission Branch情報が不正です。"
        )

    modified_files = implementation.get(
        "modified_files"
    )

    if not isinstance(modified_files, list):
        raise MissionCommitError(
            "変更済みファイル情報が不正です。"
        )

    completed_step_paths = (
        _verified_completed_step_paths(
            implementation
        )
    )

    allowed_commit_paths = {
        str(value).strip()
        .replace("\\", "/")
        .lstrip("/")
        for value in modified_files
        if str(value).strip()
    }

    allowed_commit_paths.update(
        completed_step_paths
    )

    if not allowed_commit_paths:
        raise MissionCommitError(
            "Commit許可対象ファイルがありません。"
        )

    message = payload.message.strip()

    if "\n" in message:
        raise MissionCommitError(
            "v0.1ではCommit Messageは"
            "1行だけ指定してください。"
        )

    commit_result = commit_verified_changes(
        project_root=project_root,
        branch_name=branch_name,
        allowed_paths=sorted(
            allowed_commit_paths
        ),
        message=message,
    )

    committed_at = _now()

    commit_record = {
        **commit_result,
        "mission_id": mission_id,
        "project_id": project["id"],
        "project_name": project["name"],
        "committed_by": (
            payload.committed_by.strip()
        ),
        "committed_at": committed_at,
    }

    updated_implementation = {
        **implementation,
        "implementation_version": (
            "mission-implementation-v0.5"
        ),
        "mode": "COMMITTED",
        "commit": commit_record,
        "next_stage": (
            "Reporting Runnerで変更内容と"
            "検証結果を報告する"
        ),
    }

    implementation_text = json.dumps(
        updated_implementation,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(implementation_text) > 95000:
        raise MissionCommitError(
            "Commit結果が保存上限を超えました。"
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
                implementation_text,
                committed_at,
                implementation_task["id"],
                mission_id,
            ),
        )

        connection.execute(
            """
            UPDATE missions
            SET
                next_action = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                (
                    "Commit完了。"
                    "Reporting Runnerを実行してください。"
                ),
                committed_at,
                mission_id,
            ),
        )

        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="MISSION_CHANGES_COMMITTED",
        message=(
            f"{commit_result['changed_file_count']}件の"
            "検証済み変更をMission Branchへ"
            "Commitしました。"
        ),
        metadata=commit_record,
    )

    return {
        "mission": get_mission(mission_id),
        "commit": commit_record,
        "implementation": updated_implementation,
    }


def commit_mission_changes_safe(
    *,
    mission_id: int,
    payload: MissionCommitRequest,
) -> dict[str, Any]:
    try:
        return commit_mission_changes(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionCommitError:
        raise
    except MissionError as error:
        raise MissionCommitError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionCommitError(
            "Commit Runnerで予期しない"
            f"エラーが発生しました: {error}"
        ) from error
