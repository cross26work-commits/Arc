from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.missions.implementation_step_state import (
    ImplementationStepStateError,
    complete_current_step,
    load_step_execution,
    update_current_step_status,
)
from app.missions.implementation_runner import (
    _load_backup_manifest,
    _restore_manifest_files,
    _verified_completed_step_paths,
)
from app.missions.models import MissionTaskUpdate
from app.missions.failure_classifier import (
    classify_command_failure,
)
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
    classification = classify_command_failure(
        command_name=command_name,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        returncode=returncode,
    )

    return classification.category.value


def _resolve_python_executable(
    project_root: Path,
) -> str:
    """Projectで利用可能なPythonを安全に解決する。"""

    project_root = project_root.resolve()

    candidates = [
        # Windows virtual environments
        project_root / "venv" / "Scripts" / "python.exe",
        (
            project_root
            / "backend"
            / "venv"
            / "Scripts"
            / "python.exe"
        ),
        project_root / ".venv" / "Scripts" / "python.exe",
        (
            project_root
            / "backend"
            / ".venv"
            / "Scripts"
            / "python.exe"
        ),

        # macOS / Linux virtual environments
        project_root / "venv" / "bin" / "python",
        project_root / "venv" / "bin" / "python3",
        (
            project_root
            / "backend"
            / "venv"
            / "bin"
            / "python"
        ),
        (
            project_root
            / "backend"
            / "venv"
            / "bin"
            / "python3"
        ),
        project_root / ".venv" / "bin" / "python",
        project_root / ".venv" / "bin" / "python3",
        (
            project_root
            / "backend"
            / ".venv"
            / "bin"
            / "python"
        ),
        (
            project_root
            / "backend"
            / ".venv"
            / "bin"
            / "python3"
        ),
    ]

    for candidate in candidates:
        if (
            candidate.is_file()
            and os.access(candidate, os.X_OK)
        ):
            return str(candidate)

    for command_name in ("python3", "python"):
        system_python = shutil.which(command_name)

        if not system_python:
            continue

        system_path = Path(system_python).resolve()

        if "WindowsApps" in system_path.parts:
            continue

        return str(system_path)

    raise MissionVerificationError(
        "Verificationに利用可能なPythonが"
        "見つかりません。"
    )


def _resolve_python_verification_layout(
    project_root: Path,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    backend_root = (
        project_root / "backend"
    ).resolve()

    working_root = (
        backend_root
        if backend_root.is_dir()
        else project_root
    )

    compile_targets = [
        candidate
        for candidate in (
            "app",
            "src",
            "tests",
        )
        if (
            working_root / candidate
        ).exists()
    ]

    if not compile_targets:
        compile_targets = ["."]

    return {
        "working_root": working_root,
        "compile_targets": compile_targets,
        "backend_exists": (
            backend_root.is_dir()
        ),
    }


def _resolve_command(
    *,
    project_root: Path,
    name: str,
    command: str,
) -> dict[str, Any]:
    normalized = " ".join(
        command.strip().split()
    )

    normalized = normalized.replace(
        r"venv\Scripts\python.exe",
        "venv/bin/python",
    )

    python_commands = {
        (
            "cd backend && "
            "venv/bin/python -m compileall -q app"
        ),
        (
            "cd backend && "
            "venv/bin/python -m pytest"
        ),
    }

    python_executable: str | None = None
    python_layout: dict[str, Any] | None = None

    if normalized in python_commands:
        python_executable = (
            _resolve_python_executable(
                project_root
            )
        )
        python_layout = (
            _resolve_python_verification_layout(
                project_root
            )
        )

    exact_commands: dict[str, dict[str, Any]] = {
        (
            "cd backend && "
            "venv/bin/python -m compileall -q app"
        ): {
            "argv": [
                python_executable,
                "-m",
                "compileall",
                "-q",
                *(
                    python_layout[
                        "compile_targets"
                    ]
                    if python_layout
                    else ["."]
                ),
            ],
            "cwd": (
                python_layout["working_root"]
                if python_layout
                else project_root
            ),
            "timeout_seconds": 60,
            "category": "COMPILE",
        },
        (
            "cd backend && "
            "venv/bin/python -m pytest"
        ): {
            "argv": [
                python_executable,
                "-m",
                "pytest",
            ],
            "cwd": (
                python_layout["working_root"]
                if python_layout
                else project_root
            ),
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

    if not cwd.exists():
        raise MissionVerificationError(
            "Verification作業ディレクトリが"
            "存在しません: "
            f"{cwd}"
        )

    if not cwd.is_dir():
        raise MissionVerificationError(
            "Verification作業ディレクトリが"
            "フォルダではありません: "
            f"{cwd}"
        )

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
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            close_fds=True,
        )

        returncode: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr

    except FileNotFoundError as error:
        returncode = 127
        stdout = ""
        stderr = str(error)

    except OSError as error:
        returncode = 126
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



def _calculate_progress_in_connection(
    connection,
    mission_id: int,
) -> int:
    rows = connection.execute(
        """
        SELECT status
        FROM mission_tasks
        WHERE mission_id = ?
        ORDER BY position ASC
        """,
        (mission_id,),
    ).fetchall()

    if not rows:
        return 0

    completed = sum(
        1
        for row in rows
        if row["status"] in {
            "COMPLETED",
            "SKIPPED",
        }
    )

    return round(
        completed
        / len(rows)
        * 100
    )


def _load_step_execution_from_implementation(
    implementation_result: dict[str, Any],
):
    payload = implementation_result.get(
        "step_execution"
    )

    if payload is None:
        return None

    if not isinstance(payload, dict):
        raise MissionVerificationError(
            "Step Execution Stateの形式が不正です。"
        )

    try:
        return load_step_execution(payload)
    except ImplementationStepStateError as error:
        raise MissionVerificationError(
            str(error)
        ) from error


def _store_step_execution(
    *,
    implementation_result: dict[str, Any],
    execution,
) -> dict[str, Any]:
    return {
        **implementation_result,
        "step_execution": execution.model_dump(
            mode="json"
        ),
    }


def _start_step_verification(
    implementation_result: dict[str, Any],
) -> dict[str, Any]:
    execution = (
        _load_step_execution_from_implementation(
            implementation_result
        )
    )

    if execution is None:
        return implementation_result

    step_id = execution.current_step_id

    if step_id is None:
        raise MissionVerificationError(
            "Verification対象のCurrent Stepがありません。"
        )

    step_result = execution.results.get(step_id)

    if step_result is None:
        raise MissionVerificationError(
            f"Step Resultがありません: {step_id}"
        )

    if step_result.status != "PATCH_APPLIED":
        raise MissionVerificationError(
            "Verification開始前のStep状態が"
            "PATCH_APPLIEDではありません: "
            f"{step_result.status}"
        )

    try:
        execution = update_current_step_status(
            execution,
            status="VERIFYING",
            metadata={
                "verification_started_at": _now(),
            },
        )
    except ImplementationStepStateError as error:
        raise MissionVerificationError(
            str(error)
        ) from error

    return _store_step_execution(
        implementation_result=implementation_result,
        execution=execution,
    )


def _complete_step_verification(
    *,
    implementation_result: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    execution = (
        _load_step_execution_from_implementation(
            implementation_result
        )
    )

    if execution is None:
        return implementation_result

    step_id = execution.current_step_id

    if step_id is None:
        raise MissionVerificationError(
            "完了対象のCurrent Stepがありません。"
        )

    step_result = execution.results.get(step_id)

    if step_result is None:
        raise MissionVerificationError(
            f"Step Resultがありません: {step_id}"
        )

    if step_result.status != "VERIFYING":
        raise MissionVerificationError(
            "Verification完了前のStep状態が"
            "VERIFYINGではありません: "
            f"{step_result.status}"
        )

    changed_files = list(
        step_result.changed_files
    )

    try:
        execution = complete_current_step(
            execution,
            verification_passed=True,
            changed_files=changed_files,
            metadata={
                "verification_completed_at": _now(),
                "verification_version": (
                    verification_result.get(
                        "verification_version"
                    )
                ),
                "executed_command_count": (
                    verification_result.get(
                        "executed_command_count"
                    )
                ),
                "verification_passed": True,
            },
        )
    except ImplementationStepStateError as error:
        raise MissionVerificationError(
            str(error)
        ) from error

    return _store_step_execution(
        implementation_result=implementation_result,
        execution=execution,
    )


def _fail_step_verification(
    *,
    implementation_result: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    execution = (
        _load_step_execution_from_implementation(
            implementation_result
        )
    )

    if execution is None:
        return implementation_result

    error_message = str(
        verification_result.get(
            "failure_category"
        )
        or "Verification failed."
    )

    try:
        execution = update_current_step_status(
            execution,
            status="FAILED",
            error=error_message,
            metadata={
                "verification_completed_at": _now(),
                "verification_passed": False,
                "failure_category": (
                    verification_result.get(
                        "failure_category"
                    )
                ),
                "executed_command_count": (
                    verification_result.get(
                        "executed_command_count"
                    )
                ),
            },
        )
    except ImplementationStepStateError as error:
        raise MissionVerificationError(
            str(error)
        ) from error

    step_id = execution.current_step_id

    if step_id is not None:
        execution.results[
            step_id
        ].verification_passed = False

    return _store_step_execution(
        implementation_result=implementation_result,
        execution=execution,
    )


def _step_execution_payload(
    implementation_result: dict[str, Any],
) -> dict[str, Any] | None:
    payload = implementation_result.get(
        "step_execution"
    )

    if payload is None:
        return None

    if not isinstance(payload, dict):
        raise MissionVerificationError(
            "Step Execution Stateの形式が不正です。"
        )

    return payload


def _has_remaining_steps(
    implementation_result: dict[str, Any],
) -> bool:
    payload = _step_execution_payload(
        implementation_result
    )

    if payload is None:
        return False

    execution_completed = payload.get(
        "execution_completed"
    )

    remaining = payload.get(
        "remaining_step_ids"
    )

    return (
        execution_completed is False
        and isinstance(remaining, list)
        and len(remaining) > 0
    )


def _append_step_verification_history(
    *,
    implementation_result: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    payload = _step_execution_payload(
        implementation_result
    )

    if payload is None:
        return implementation_result

    completed_steps = payload.get(
        "completed_step_ids"
    )

    completed_step_id = (
        completed_steps[-1]
        if isinstance(completed_steps, list)
        and completed_steps
        else None
    )

    history = implementation_result.get(
        "step_verification_history"
    )

    if not isinstance(history, list):
        history = []

    history = [
        *history,
        {
            "step_id": completed_step_id,
            "passed": verification_result.get(
                "passed"
            ),
            "verification_version": (
                verification_result.get(
                    "verification_version"
                )
            ),
            "executed_command_count": (
                verification_result.get(
                    "executed_command_count"
                )
            ),
            "completed_at": _now(),
            "result": verification_result,
        },
    ]

    return {
        **implementation_result,
        "step_verification_history": history,
    }


def _rearm_next_step_cycle(
    *,
    mission_id: int,
    implementation_task: dict[str, Any],
    verification_task: dict[str, Any],
    implementation_result: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    if not _has_remaining_steps(
        implementation_result
    ):
        raise MissionVerificationError(
            "再武装対象の残Stepがありません。"
        )

    implementation_result = (
        _append_step_verification_history(
            implementation_result=(
                implementation_result
            ),
            verification_result=(
                verification_result
            ),
        )
    )

    step_execution = _step_execution_payload(
        implementation_result
    )

    current_step_id = (
        step_execution.get(
            "current_step_id"
        )
        if step_execution is not None
        else None
    )

    rearmed_result = {
        **implementation_result,
        "mode": "BACKUP_READY",
        "step_cycle_rearmed": True,
        "next_stage": "RUN_CODE_GENERATION",
        "last_completed_verification": {
            "passed": verification_result.get(
                "passed"
            ),
            "verification_version": (
                verification_result.get(
                    "verification_version"
                )
            ),
            "executed_command_count": (
                verification_result.get(
                    "executed_command_count"
                )
            ),
            "completed_at": _now(),
        },
    }

    result_text = json.dumps(
        rearmed_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionVerificationError(
            "次Step再武装後のIMPLEMENTATION結果が"
            "保存上限を超えました。"
        )

    update_mission_task(
        mission_id=mission_id,
        task_id=implementation_task["id"],
        payload=MissionTaskUpdate(
            status="RUNNING",
            result=result_text,
            target_path=(
                implementation_task.get(
                    "target_path"
                )
            ),
        ),
    )

    updated_mission = update_mission_task(
        mission_id=mission_id,
        task_id=verification_task["id"],
        payload=MissionTaskUpdate(
            status="READY",
            result=None,
            target_path=(
                verification_task.get(
                    "target_path"
                )
            ),
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "IMPLEMENTATION_STEP_CYCLE_REARMED"
        ),
        message=(
            "Step Verificationが成功したため、"
            "次のImplementation Stepを"
            "Code Generation可能な状態へ戻しました。"
        ),
        metadata={
            "current_step_id": current_step_id,
            "completed_step_ids": (
                step_execution.get(
                    "completed_step_ids",
                    [],
                )
                if step_execution is not None
                else []
            ),
            "remaining_step_ids": (
                step_execution.get(
                    "remaining_step_ids",
                    [],
                )
                if step_execution is not None
                else []
            ),
            "implementation_status":
                "RUNNING",
            "implementation_mode":
                "BACKUP_READY",
            "verification_status":
                "READY",
            "next_stage":
                "RUN_CODE_GENERATION",
        },
    )

    return {
        "mission": updated_mission,
        "verification": verification_result,
        "step_cycle_rearmed": True,
        "current_step_id": current_step_id,
        "next_stage": "RUN_CODE_GENERATION",
    }


def _rollback_failed_verification(
    *,
    mission_id: int,
    project_root: Path,
    implementation_task: dict[str, Any],
    verification_task: dict[str, Any],
    implementation_result: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    run_root, manifest = (
        _load_backup_manifest(
            implementation_result
        )
    )

    step_execution = implementation_result.get(
        "step_execution"
    )

    if not isinstance(step_execution, dict):
        raise MissionVerificationError(
            "Step Execution Stateがありません。"
        )

    current_step_id = step_execution.get(
        "current_step_id"
    )
    step_results = step_execution.get(
        "results"
    )

    if (
        not isinstance(current_step_id, str)
        or not isinstance(step_results, dict)
    ):
        raise MissionVerificationError(
            "Current Step情報が不正です。"
        )

    current_step_result = step_results.get(
        current_step_id
    )

    if not isinstance(
        current_step_result,
        dict,
    ):
        raise MissionVerificationError(
            "Current Step Resultがありません。"
        )

    changed_files = current_step_result.get(
        "changed_files"
    )

    if not isinstance(changed_files, list):
        raise MissionVerificationError(
            "Current Stepの変更ファイル情報が"
            "不正です。"
        )

    restore_paths = {
        str(value).strip()
        .replace("\\", "/")
        .lstrip("/")
        for value in changed_files
        if str(value).strip()
    }

    if not restore_paths:
        raise MissionVerificationError(
            "Current Stepの復元対象がありません。"
        )

    completed_step_paths = (
        _verified_completed_step_paths(
            implementation_result
        )
    )

    restore_result = _restore_manifest_files(
        project_root=project_root,
        run_root=run_root,
        manifest=manifest,
        restore_paths=restore_paths,
        allowed_remaining_paths=(
            completed_step_paths
        ),
    )

    if not restore_result["working_tree_clean"]:
        raise MissionVerificationError(
            "Verification失敗後の自動復元に"
            "失敗しました。残存差分: "
            f"{restore_result['remaining_changes']}"
        )

    rollback_at = _now()

    rolled_back_implementation = {
        **implementation_result,
        "implementation_version": (
            "mission-implementation-v0.4"
        ),
        "mode": "BACKUP_READY",
        "write_enabled": bool(
            completed_step_paths
        ),
        "files_modified": len(
            completed_step_paths
        ),
        "modified_files": sorted(
            completed_step_paths
        ),
        "rollback": {
            "rolled_back": True,
            "rolled_back_at": rollback_at,
            "reason": "VERIFICATION_FAILED",
            "failure_category": (
                verification_result[
                    "failure_category"
                ]
            ),
            "restored_file_count": (
                restore_result[
                    "restored_file_count"
                ]
            ),
            "restored_files": (
                restore_result[
                    "restored_files"
                ]
            ),
            "working_tree_clean": True,
        },
        "last_verification_failure": {
            "verification_version": (
                verification_result[
                    "verification_version"
                ]
            ),
            "failure_category": (
                verification_result[
                    "failure_category"
                ]
            ),
            "executed_command_count": (
                verification_result[
                    "executed_command_count"
                ]
            ),
            "failed_at": rollback_at,
        },
        "next_stage": (
            "失敗原因を解析し、Patchを再生成する"
        ),
    }

    implementation_text = json.dumps(
        rolled_back_implementation,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    verification_text = json.dumps(
        verification_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(implementation_text) > 95000:
        raise MissionVerificationError(
            "Rollback後のImplementation結果が"
            "保存上限を超えました。"
        )

    if len(verification_text) > 95000:
        raise MissionVerificationError(
            "Verification失敗結果が"
            "保存上限を超えました。"
        )

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'RUNNING',
                result = ?,
                updated_at = ?
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                implementation_text,
                rollback_at,
                implementation_task["id"],
                mission_id,
            ),
        )

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'PENDING',
                result = ?,
                updated_at = ?
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                verification_text,
                rollback_at,
                verification_task["id"],
                mission_id,
            ),
        )

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'PENDING',
                updated_at = ?
            WHERE mission_id = ?
              AND position > ?
            """,
            (
                rollback_at,
                mission_id,
                verification_task["position"],
            ),
        )

        progress = _calculate_progress_in_connection(
            connection,
            mission_id,
        )

        connection.execute(
            """
            UPDATE missions
            SET
                status = 'APPROVED',
                progress = ?,
                next_action = ?,
                error_count = error_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (
                progress,
                (
                    "Verification失敗。"
                    "復元済みです。"
                    "失敗原因を解析して"
                    "Patchを再生成してください。"
                ),
                rollback_at,
                mission_id,
            ),
        )

        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="ERROR",
        event_type=(
            "MISSION_VERIFICATION_FAILED_ROLLED_BACK"
        ),
        message=(
            "Verificationに失敗したため、"
            "変更前Backupから自動復元し、"
            "IMPLEMENTATION Taskを"
            "再試行可能状態へ戻しました。"
        ),
        metadata={
            "verification_version": (
                verification_result[
                    "verification_version"
                ]
            ),
            "failure_category": (
                verification_result[
                    "failure_category"
                ]
            ),
            "executed_command_count": (
                verification_result[
                    "executed_command_count"
                ]
            ),
            "restored_file_count": (
                restore_result[
                    "restored_file_count"
                ]
            ),
            "working_tree_clean": True,
            "implementation_status": "RUNNING",
            "verification_status": "PENDING",
            "resume_mode": "BACKUP_READY",
            "next_stage": "RUN_CODE_GENERATION",
        },
    )

    return {
        "mission": get_mission(mission_id),
        "verification": verification_result,
        "rollback": restore_result,
        "implementation": (
            rolled_back_implementation
        ),
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

    implementation_result = (
        _start_step_verification(
            implementation_result
        )
    )

    implementation_result_text = json.dumps(
        implementation_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(implementation_result_text) > 95000:
        raise MissionVerificationError(
            "Verification開始後の"
            "IMPLEMENTATION結果が保存上限を超えました。"
        )

    update_mission_task(
        mission_id=mission_id,
        task_id=implementation_task["id"],
        payload=MissionTaskUpdate(
            status=implementation_task["status"],
            result=implementation_result_text,
            target_path=(
                implementation_task.get(
                    "target_path"
                )
            ),
        ),
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

    if not verification_result["passed"]:
        implementation_result = (
            _fail_step_verification(
                implementation_result=(
                    implementation_result
                ),
                verification_result=(
                    verification_result
                ),
            )
        )

        return _rollback_failed_verification(
            mission_id=mission_id,
            project_root=project_root,
            implementation_task=implementation_task,
            verification_task=verification_task,
            implementation_result=implementation_result,
            verification_result=verification_result,
        )

    implementation_result = (
        _complete_step_verification(
            implementation_result=(
                implementation_result
            ),
            verification_result=(
                verification_result
            ),
        )
    )

    if _has_remaining_steps(
        implementation_result
    ):
        return _rearm_next_step_cycle(
            mission_id=mission_id,
            implementation_task=(
                implementation_task
            ),
            verification_task=(
                verification_task
            ),
            implementation_result=(
                implementation_result
            ),
            verification_result=(
                verification_result
            ),
        )

    implementation_result = (
        _append_step_verification_history(
            implementation_result=(
                implementation_result
            ),
            verification_result=(
                verification_result
            ),
        )
    )

    implementation_result_text = json.dumps(
        implementation_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(implementation_result_text) > 95000:
        raise MissionVerificationError(
            "Verification完了後の"
            "IMPLEMENTATION結果が保存上限を超えました。"
        )

    update_mission_task(
        mission_id=mission_id,
        task_id=implementation_task["id"],
        payload=MissionTaskUpdate(
            status=implementation_task["status"],
            result=implementation_result_text,
            target_path=(
                implementation_task.get(
                    "target_path"
                )
            ),
        ),
    )

    result_text = json.dumps(
        verification_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    updated_mission = update_mission_task(
        mission_id=mission_id,
        task_id=verification_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_VERIFICATION_COMPLETED"
        ),
        message=(
            "Verification Runnerが"
            "全検証に成功しました。"
        ),
        metadata={
            "verification_version": (
                "mission-verification-v0.2"
            ),
            "passed": True,
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
            "failure_category": None,
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
