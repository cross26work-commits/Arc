from __future__ import annotations

import json
import subprocess
import time
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


class MissionVerificationError(Exception):
    """Verification Runnerの実行に失敗した場合の例外。"""


MAX_OUTPUT_CHARS = 50000


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
        raise MissionVerificationError(
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
        raise MissionVerificationError(
            f"{label}結果が保存されていません。"
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MissionVerificationError(
            f"{label}結果のJSONを読み取れません。"
        ) from error

    if not isinstance(result, dict):
        raise MissionVerificationError(
            f"{label}結果の形式が不正です。"
        )

    return result


def _truncate_output(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value

    return (
        value[:MAX_OUTPUT_CHARS]
        + "\n...[output truncated]..."
    )


def _classify_failure(
    *,
    command_name: str,
    stdout: str,
    stderr: str,
    timed_out: bool,
    returncode: int | None,
) -> str:
    combined = (
        f"{command_name}\n{stdout}\n{stderr}"
    ).lower()

    if timed_out:
        return "TIMEOUT"

    if "permission denied" in combined:
        return "PERMISSION"

    if (
        "no such file or directory" in combined
        or "not found" in combined
        or "command not found" in combined
    ):
        return "DEPENDENCY"

    if (
        "syntaxerror" in combined
        or "syntax error" in combined
        or "indentationerror" in combined
    ):
        return "SYNTAX"

    if (
        "modulenotfounderror" in combined
        or "importerror" in combined
        or "cannot import" in combined
    ):
        return "IMPORT"

    if (
        "eslint" in combined
        or "lint" in command_name.lower()
    ):
        return "LINT"

    if (
        "pytest" in combined
        or "test failed" in combined
        or "failed" in combined
        and "test" in combined
    ):
        return "TEST"

    if (
        "npm run build" in combined
        or "build failed" in combined
        or "failed to compile" in combined
    ):
        return "BUILD"

    if "git" in command_name.lower():
        return "GIT"

    if returncode not in {
        None,
        0,
    }:
        return "COMMAND"

    return "UNKNOWN"


def _resolve_command(
    *,
    project_root: Path,
    name: str,
    command: str,
) -> dict[str, Any]:
    normalized = " ".join(
        command.strip().split()
    )

    exact_commands: dict[str, dict[str, Any]] = {
        (
            "cd backend && "
            "venv/bin/python -m compileall -q app"
        ): {
            "argv": [
                "venv/bin/python",
                "-m",
                "compileall",
                "-q",
                "app",
            ],
            "cwd": project_root / "backend",
            "timeout_seconds": 60,
            "category": "COMPILE",
        },
        (
            "cd backend && "
            "venv/bin/python -m pytest"
        ): {
            "argv": [
                "venv/bin/python",
                "-m",
                "pytest",
            ],
            "cwd": project_root / "backend",
            "timeout_seconds": 300,
            "category": "TEST",
        },
        "npm run build": {
            "argv": [
                "npm",
                "run",
                "build",
            ],
            "cwd": project_root / "frontend",
            "timeout_seconds": 300,
            "category": "BUILD",
        },
        "npm run lint": {
            "argv": [
                "npm",
                "run",
                "lint",
            ],
            "cwd": project_root / "frontend",
            "timeout_seconds": 180,
            "category": "LINT",
        },
        "git diff --check && git status": {
            "argv_sequence": [
                [
                    "git",
                    "diff",
                    "--check",
                ],
                [
                    "git",
                    "status",
                    "--short",
                ],
            ],
            "cwd": project_root,
            "timeout_seconds": 30,
            "category": "GIT",
        },
        "git diff --check": {
            "argv": [
                "git",
                "diff",
                "--check",
            ],
            "cwd": project_root,
            "timeout_seconds": 20,
            "category": "GIT",
        },
        "git status --porcelain": {
            "argv": [
                "git",
                "status",
                "--porcelain",
            ],
            "cwd": project_root,
            "timeout_seconds": 20,
            "category": "GIT",
        },
    }

    spec = exact_commands.get(normalized)

    if spec is None:
        raise MissionVerificationError(
            "許可されていないVerification "
            f"Commandです: {command}"
        )

    cwd = Path(spec["cwd"]).resolve()

    try:
        cwd.relative_to(project_root)
    except ValueError as error:
        raise MissionVerificationError(
            "Verification作業ディレクトリが"
            "Project外です。"
        ) from error

    return {
        "name": name.strip() or "Verification",
        "original_command": command,
        "normalized_command": normalized,
        **spec,
        "cwd": cwd,
    }


def _run_single_command(
    *,
    name: str,
    argv: list[str],
    cwd: Path,
    timeout_seconds: int,
    category: str,
) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False

    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        returncode: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr

    except FileNotFoundError as error:
        returncode = 127
        stdout = ""
        stderr = str(error)

    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = None

        stdout = (
            error.stdout.decode(
                "utf-8",
                errors="replace",
            )
            if isinstance(error.stdout, bytes)
            else error.stdout or ""
        )

        stderr = (
            error.stderr.decode(
                "utf-8",
                errors="replace",
            )
            if isinstance(error.stderr, bytes)
            else error.stderr or ""
        )

    elapsed = round(
        time.monotonic() - started,
        3,
    )

    passed = (
        not timed_out
        and returncode == 0
    )

    failure_category = (
        None
        if passed
        else _classify_failure(
            command_name=name,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            returncode=returncode,
        )
    )

    return {
        "name": name,
        "category": category,
        "argv": argv,
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": elapsed,
        "returncode": returncode,
        "timed_out": timed_out,
        "passed": passed,
        "failure_category": failure_category,
        "stdout": _truncate_output(stdout),
        "stderr": _truncate_output(stderr),
    }


def execute_verification_spec(
    spec: dict[str, Any],
) -> dict[str, Any]:
    if "argv_sequence" in spec:
        sequence_results: list[dict[str, Any]] = []

        for position, argv in enumerate(
            spec["argv_sequence"],
            start=1,
        ):
            result = _run_single_command(
                name=(
                    f"{spec['name']} "
                    f"({position}/"
                    f"{len(spec['argv_sequence'])})"
                ),
                argv=argv,
                cwd=spec["cwd"],
                timeout_seconds=spec[
                    "timeout_seconds"
                ],
                category=spec["category"],
            )

            sequence_results.append(result)

            if not result["passed"]:
                break

        passed = all(
            item["passed"]
            for item in sequence_results
        )

        failure = next(
            (
                item
                for item in sequence_results
                if not item["passed"]
            ),
            None,
        )

        return {
            "name": spec["name"],
            "category": spec["category"],
            "original_command": spec[
                "original_command"
            ],
            "cwd": str(spec["cwd"]),
            "passed": passed,
            "failure_category": (
                failure["failure_category"]
                if failure
                else None
            ),
            "steps": sequence_results,
        }

    result = _run_single_command(
        name=spec["name"],
        argv=spec["argv"],
        cwd=spec["cwd"],
        timeout_seconds=spec[
            "timeout_seconds"
        ],
        category=spec["category"],
    )

    return {
        "name": spec["name"],
        "category": spec["category"],
        "original_command": spec[
            "original_command"
        ],
        "cwd": str(spec["cwd"]),
        "passed": result["passed"],
        "failure_category": result[
            "failure_category"
        ],
        "steps": [result],
    }


def run_verification_commands(
    *,
    project_root: Path,
    commands: list[dict[str, str]],
) -> dict[str, Any]:
    project_root = project_root.resolve()

    if not project_root.exists():
        raise MissionVerificationError(
            "Project Rootが存在しません。"
        )

    if not project_root.is_dir():
        raise MissionVerificationError(
            "Project Rootがフォルダではありません。"
        )

    if not commands:
        raise MissionVerificationError(
            "Verification Commandがありません。"
        )

    results: list[dict[str, Any]] = []

    for item in commands:
        if not isinstance(item, dict):
            raise MissionVerificationError(
                "Verification Commandの形式が不正です。"
            )

        name = str(
            item.get("name") or "Verification"
        )

        command = str(
            item.get("command") or ""
        ).strip()

        if not command:
            raise MissionVerificationError(
                "Verification Commandが空です。"
            )

        spec = _resolve_command(
            project_root=project_root,
            name=name,
            command=command,
        )

        result = execute_verification_spec(
            spec
        )

        results.append(result)

        if not result["passed"]:
            break

    passed = (
        len(results) == len(commands)
        and all(
            item["passed"]
            for item in results
        )
    )

    failed_result = next(
        (
            item
            for item in results
            if not item["passed"]
        ),
        None,
    )

    return {
        "verification_version": (
            "mission-verification-v0.1"
        ),
        "executed_at": _now(),
        "passed": passed,
        "requested_command_count": len(
            commands
        ),
        "executed_command_count": len(
            results
        ),
        "failure_category": (
            failed_result["failure_category"]
            if failed_result
            else None
        ),
        "results": results,
    }


def run_mission_verification(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    implementation_result = _load_json_result(
        implementation_task,
        label="IMPLEMENTATION",
    )

    if (
        implementation_result.get("mode")
        != "PATCH_APPLIED"
    ):
        raise MissionVerificationError(
            "Patch適用完了後にVerificationを"
            "実行してください。"
        )

    if (
        implementation_result.get(
            "write_enabled"
        )
        is not True
    ):
        raise MissionVerificationError(
            "書込みが有効化されていません。"
        )

    if (
        int(
            implementation_result.get(
                "files_modified",
                0,
            )
        )
        <= 0
    ):
        raise MissionVerificationError(
            "変更済みファイルがありません。"
        )

    if verification_task["status"] not in {
        "PENDING",
        "READY",
        "RUNNING",
    }:
        raise MissionVerificationError(
            "VERIFICATION Taskは"
            "実行可能な状態ではありません。"
        )

    project = _get_project(
        mission["project_id"]
    )

    if project is None:
        raise MissionVerificationError(
            "Projectが見つかりません。"
        )

    project_root = Path(
        project["path"]
    ).expanduser().resolve()

    commands = implementation_result.get(
        "verification_commands"
    )

    if not isinstance(commands, list):
        raise MissionVerificationError(
            "Verification Commandが"
            "保存されていません。"
        )

    if verification_task["status"] != "RUNNING":
        update_mission_task(
            mission_id=mission_id,
            task_id=verification_task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

    verification_result = (
        run_verification_commands(
            project_root=project_root,
            commands=commands,
        )
    )

    result_text = json.dumps(
        verification_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    final_status = (
        "COMPLETED"
        if verification_result["passed"]
        else "FAILED"
    )

    updated_mission = update_mission_task(
        mission_id=mission_id,
        task_id=verification_task["id"],
        payload=MissionTaskUpdate(
            status=final_status,
            result=result_text,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level=(
            "INFO"
            if verification_result["passed"]
            else "ERROR"
        ),
        event_type=(
            "MISSION_VERIFICATION_COMPLETED"
            if verification_result["passed"]
            else "MISSION_VERIFICATION_FAILED"
        ),
        message=(
            "Verification Runnerが"
            + (
                "全検証に成功しました。"
                if verification_result["passed"]
                else (
                    "検証に失敗しました。"
                    f"分類: "
                    f"{verification_result['failure_category']}"
                )
            )
        ),
        metadata={
            "verification_version": (
                "mission-verification-v0.1"
            ),
            "passed": verification_result[
                "passed"
            ],
            "requested_command_count": (
                verification_result[
                    "requested_command_count"
                ]
            ),
            "executed_command_count": (
                verification_result[
                    "executed_command_count"
                ]
            ),
            "failure_category": (
                verification_result[
                    "failure_category"
                ]
            ),
        },
    )

    return {
        "mission": updated_mission,
        "verification": verification_result,
    }


def run_mission_verification_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_mission_verification(
            mission_id
        )
    except MissionVerificationError:
        raise
    except MissionError as error:
        raise MissionVerificationError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionVerificationError(
            "Verification Runnerで予期しない"
            f"エラーが発生しました: {error}"
        ) from error
