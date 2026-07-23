from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.mission_orchestrator import (
    determine_mission_stage,
)
from app.missions.service import (
    MissionError,
    get_mission,
)


class MissionRecoveryError(Exception):
    """Mission Recovery Inspectorの判定失敗。"""


MISSION_RECOVERY_VERSION = (
    "mission-recovery-v0.1"
)


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _sha256_bytes(
    data: bytes,
) -> str:
    return hashlib.sha256(
        data
    ).hexdigest()


def _run_git(
    project_path: Path,
    *arguments: str,
) -> str:
    if not project_path.is_dir():
        raise MissionRecoveryError(
            "Project Pathが存在しません。"
            f" path={project_path}"
        )

    if not (
        project_path / ".git"
    ).exists():
        raise MissionRecoveryError(
            "ProjectはGit Repositoryでは"
            "ありません。"
            f" path={project_path}"
        )

    result = subprocess.run(
        [
            "git",
            "-C",
            str(project_path),
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise MissionRecoveryError(
            "Git Commandに失敗しました。"
            f" command={' '.join(arguments)}"
            f" stderr={result.stderr.strip()}"
        )

    return result.stdout.strip()


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any] | None:
    tasks = mission.get("tasks")

    if not isinstance(tasks, list):
        return None

    return next(
        (
            task
            for task in tasks
            if (
                isinstance(task, dict)
                and task.get("task_type")
                == task_type
            )
        ),
        None,
    )


def _load_task_result(
    task: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return None

    raw = task.get("result")

    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str):
        return None

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(value, dict):
        return None

    return value


def _task_status(
    mission: dict[str, Any],
    task_type: str,
) -> str | None:
    task = _task_by_type(
        mission,
        task_type,
    )

    if task is None:
        return None

    value = task.get("status")

    if value is None:
        return None

    return str(value).strip().upper()


def inspect_mission_state(
    mission: dict[str, Any],
) -> dict[str, Any]:
    decision = determine_mission_stage(
        mission
    )

    if not isinstance(decision, dict):
        raise MissionRecoveryError(
            "Mission Stage判定結果が不正です。"
        )

    task_statuses = {}

    for task_type in (
        "REQUIREMENTS",
        "ANALYSIS",
        "PLANNING",
        "APPROVAL",
        "IMPLEMENTATION",
        "VERIFICATION",
        "REPORTING",
    ):
        task_statuses[task_type] = (
            _task_status(
                mission,
                task_type,
            )
        )

    return {
        "mission_id": mission.get("id"),
        "mission_status": mission.get(
            "status"
        ),
        "mission_progress": mission.get(
            "progress"
        ),
        "next_action": mission.get(
            "next_action"
        ),
        "task_statuses": task_statuses,
        "orchestrator_stage": (
            decision.get("stage")
        ),
        "orchestrator_reason": (
            decision.get("reason")
        ),
        "recommended_action": (
            decision.get(
                "recommended_action"
            )
        ),
        "requires_master_action": (
            decision.get(
                "requires_master_action"
            )
            is True
        ),
        "executable": (
            decision.get("executable")
            is True
        ),
        "severity": decision.get(
            "severity"
        ),
    }


def inspect_backup(
    *,
    mission_id: int,
    implementation: dict[str, Any],
) -> dict[str, Any]:
    backup = implementation.get("backup")

    if not isinstance(backup, dict):
        return {
            "present": False,
            "valid": False,
            "errors": [
                "BACKUP_METADATA_MISSING"
            ],
        }

    root_path_value = backup.get(
        "root_path"
    )
    manifest_path_value = backup.get(
        "manifest_path"
    )

    errors: list[str] = []

    if not isinstance(
        root_path_value,
        str,
    ):
        errors.append(
            "BACKUP_ROOT_PATH_INVALID"
        )

    if not isinstance(
        manifest_path_value,
        str,
    ):
        errors.append(
            "MANIFEST_PATH_INVALID"
        )

    if errors:
        return {
            "present": True,
            "valid": False,
            "errors": errors,
        }

    root_path = Path(
        root_path_value
    ).resolve()
    manifest_path = Path(
        manifest_path_value
    ).resolve()

    if not root_path.is_dir():
        errors.append(
            "BACKUP_ROOT_NOT_FOUND"
        )

    if not manifest_path.is_file():
        errors.append(
            "MANIFEST_NOT_FOUND"
        )

    manifest: dict[str, Any] | None = None

    if manifest_path.is_file():
        try:
            loaded = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            errors.append(
                "MANIFEST_READ_FAILED"
            )
        else:
            if isinstance(loaded, dict):
                manifest = loaded
            else:
                errors.append(
                    "MANIFEST_FORMAT_INVALID"
                )

    if manifest is not None:
        if (
            manifest.get("mission_id")
            != mission_id
        ):
            errors.append(
                "MANIFEST_MISSION_MISMATCH"
            )

        if (
            manifest.get("restore_ready")
            is not True
        ):
            errors.append(
                "RESTORE_NOT_READY"
            )

        files = manifest.get("files")

        if not isinstance(files, list):
            errors.append(
                "MANIFEST_FILES_INVALID"
            )
        elif (
            manifest.get("file_count")
            != len(files)
        ):
            errors.append(
                "MANIFEST_FILE_COUNT_MISMATCH"
            )

    return {
        "present": True,
        "valid": not errors,
        "root_path": str(root_path),
        "manifest_path": str(
            manifest_path
        ),
        "manifest": manifest,
        "errors": errors,
    }


def inspect_git_state(
    *,
    implementation: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    project_path_value = (
        implementation.get(
            "project_path"
        )
    )

    if not isinstance(
        project_path_value,
        str,
    ):
        return {
            "valid": False,
            "errors": [
                "PROJECT_PATH_INVALID"
            ],
        }

    project_path = Path(
        project_path_value
    ).resolve()

    errors: list[str] = []

    try:
        current_branch = _run_git(
            project_path,
            "branch",
            "--show-current",
        )
        current_head = _run_git(
            project_path,
            "rev-parse",
            "HEAD",
        )
        working_tree_output = _run_git(
            project_path,
            "status",
            "--porcelain",
        )
    except MissionRecoveryError as error:
        return {
            "valid": False,
            "project_path": str(
                project_path
            ),
            "errors": [
                str(error)
            ],
        }

    expected_branch = None
    expected_head = None

    if isinstance(manifest, dict):
        manifest_git = manifest.get(
            "git"
        )

        if isinstance(
            manifest_git,
            dict,
        ):
            expected_branch = (
                manifest_git.get("branch")
            )
            expected_head = (
                manifest_git.get("head")
            )

    if expected_branch is None:
        implementation_git = (
            implementation.get("git")
        )

        if isinstance(
            implementation_git,
            dict,
        ):
            expected_branch = (
                implementation_git.get(
                    "current_branch"
                )
                or implementation_git.get(
                    "branch_name"
                )
            )

    if expected_head is None:
        implementation_git = (
            implementation.get("git")
        )

        if isinstance(
            implementation_git,
            dict,
        ):
            expected_head = (
                implementation_git.get(
                    "original_head"
                )
            )

    if (
        isinstance(expected_branch, str)
        and current_branch
        != expected_branch
    ):
        errors.append(
            "BRANCH_MISMATCH"
        )

    if (
        isinstance(expected_head, str)
        and current_head
        != expected_head
    ):
        errors.append(
            "HEAD_MISMATCH"
        )

    working_tree_clean = (
        not bool(working_tree_output)
    )

    implementation_mode = str(
        implementation.get("mode")
        or ""
    ).strip().upper()

    if (
        implementation_mode
        in {
            "BACKUP_READY",
            "PATCH_CHECKED",
        }
        and not working_tree_clean
    ):
        errors.append(
            "WORKING_TREE_DIRTY"
        )

    return {
        "valid": not errors,
        "project_path": str(
            project_path
        ),
        "expected_branch": (
            expected_branch
        ),
        "current_branch": (
            current_branch
        ),
        "expected_head": expected_head,
        "current_head": current_head,
        "working_tree_clean": (
            working_tree_clean
        ),
        "changed_paths": (
            working_tree_output.splitlines()
            if working_tree_output
            else []
        ),
        "errors": errors,
    }


def inspect_backup_files(
    *,
    implementation: dict[str, Any],
    backup_result: dict[str, Any],
) -> dict[str, Any]:
    manifest = backup_result.get(
        "manifest"
    )

    root_path_value = backup_result.get(
        "root_path"
    )

    project_path_value = (
        implementation.get(
            "project_path"
        )
    )

    if (
        not isinstance(manifest, dict)
        or not isinstance(
            root_path_value,
            str,
        )
        or not isinstance(
            project_path_value,
            str,
        )
    ):
        return {
            "valid": False,
            "file_count": 0,
            "files": [],
            "errors": [
                "FILE_INSPECTION_CONTEXT_INVALID"
            ],
        }

    root_path = Path(
        root_path_value
    ).resolve()
    project_path = Path(
        project_path_value
    ).resolve()

    files = manifest.get("files")

    if not isinstance(files, list):
        return {
            "valid": False,
            "file_count": 0,
            "files": [],
            "errors": [
                "MANIFEST_FILES_INVALID"
            ],
        }

    errors: list[str] = []
    results: list[dict[str, Any]] = []

    mode = str(
        implementation.get("mode")
        or ""
    ).strip().upper()

    require_source_unchanged = mode in {
        "BACKUP_READY",
        "PATCH_CHECKED",
    }

    for item in files:
        if not isinstance(item, dict):
            errors.append(
                "MANIFEST_FILE_ENTRY_INVALID"
            )
            continue

        relative_path = item.get("path")
        expected_sha256 = item.get(
            "sha256"
        )
        backup_path_value = item.get(
            "backup_path"
        )

        if (
            not isinstance(
                relative_path,
                str,
            )
            or not isinstance(
                expected_sha256,
                str,
            )
            or not isinstance(
                backup_path_value,
                str,
            )
        ):
            errors.append(
                "MANIFEST_FILE_METADATA_INVALID"
            )
            continue

        source_path = (
            project_path
            / relative_path
        ).resolve()

        backup_path = (
            root_path
            / backup_path_value
        ).resolve()

        source_exists = (
            source_path.is_file()
        )
        backup_exists = (
            backup_path.is_file()
        )

        source_sha256 = (
            _sha256_bytes(
                source_path.read_bytes()
            )
            if source_exists
            else None
        )

        backup_sha256 = (
            _sha256_bytes(
                backup_path.read_bytes()
            )
            if backup_exists
            else None
        )

        source_matches = (
            source_sha256
            == expected_sha256
        )
        backup_matches = (
            backup_sha256
            == expected_sha256
        )

        valid = (
            backup_exists
            and backup_matches
            and (
                source_matches
                if require_source_unchanged
                else source_exists
            )
        )

        if not valid:
            errors.append(
                f"FILE_INTEGRITY_ERROR:"
                f"{relative_path}"
            )

        results.append(
            {
                "path": relative_path,
                "source_exists": (
                    source_exists
                ),
                "backup_exists": (
                    backup_exists
                ),
                "source_sha256_match": (
                    source_matches
                ),
                "backup_sha256_match": (
                    backup_matches
                ),
                "valid": valid,
            }
        )

    return {
        "valid": not errors,
        "file_count": len(results),
        "require_source_unchanged": (
            require_source_unchanged
        ),
        "files": results,
        "errors": errors,
    }


def inspect_patch(
    *,
    mission_id: int,
    implementation: dict[str, Any],
) -> dict[str, Any]:
    patch = implementation.get("patch")

    mode = str(
        implementation.get("mode")
        or ""
    ).strip().upper()

    patch_expected = mode in {
        "PATCH_CHECKED",
        "PATCH_APPLIED",
        "COMMITTED",
    }

    if not isinstance(patch, dict):
        return {
            "present": False,
            "expected": patch_expected,
            "valid": not patch_expected,
            "errors": (
                ["PATCH_METADATA_MISSING"]
                if patch_expected
                else []
            ),
        }

    errors: list[str] = []

    patch_path_value = patch.get("path")
    result_path_value = patch.get(
        "result_path"
    )
    expected_sha256 = patch.get(
        "sha256"
    )

    if not isinstance(
        patch_path_value,
        str,
    ):
        errors.append(
            "PATCH_PATH_INVALID"
        )

    if not isinstance(
        expected_sha256,
        str,
    ):
        errors.append(
            "PATCH_SHA256_INVALID"
        )

    patch_path = (
        Path(patch_path_value).resolve()
        if isinstance(
            patch_path_value,
            str,
        )
        else None
    )

    actual_sha256 = None

    if patch_path is not None:
        if not patch_path.is_file():
            errors.append(
                "PATCH_FILE_NOT_FOUND"
            )
        else:
            actual_sha256 = (
                _sha256_bytes(
                    patch_path.read_bytes()
                )
            )

            if (
                actual_sha256
                != expected_sha256
            ):
                errors.append(
                    "PATCH_SHA256_MISMATCH"
                )

    patch_check = None

    if isinstance(
        result_path_value,
        str,
    ):
        result_path = Path(
            result_path_value
        ).resolve()

        if not result_path.is_file():
            errors.append(
                "PATCH_CHECK_NOT_FOUND"
            )
        else:
            try:
                loaded = json.loads(
                    result_path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
            ):
                errors.append(
                    "PATCH_CHECK_READ_FAILED"
                )
            else:
                if isinstance(
                    loaded,
                    dict,
                ):
                    patch_check = loaded
                else:
                    errors.append(
                        "PATCH_CHECK_FORMAT_INVALID"
                    )

    if isinstance(patch_check, dict):
        if (
            patch_check.get("mission_id")
            != mission_id
        ):
            errors.append(
                "PATCH_CHECK_MISSION_MISMATCH"
            )

        if (
            patch_check.get(
                "patch_sha256"
            )
            != expected_sha256
        ):
            errors.append(
                "PATCH_CHECK_SHA256_MISMATCH"
            )

        git_apply_check = (
            patch_check.get(
                "git_apply_check"
            )
        )

        if (
            mode == "PATCH_CHECKED"
            and (
                not isinstance(
                    git_apply_check,
                    dict,
                )
                or git_apply_check.get(
                    "applicable"
                )
                is not True
            )
        ):
            errors.append(
                "PATCH_NOT_APPLICABLE"
            )

    if (
        mode == "PATCH_CHECKED"
        and patch.get("applied") is True
    ):
        errors.append(
            "PATCH_APPLIED_FLAG_CONFLICT"
        )

    if (
        mode in {
            "PATCH_APPLIED",
            "COMMITTED",
        }
        and patch.get("applied")
        is not True
    ):
        errors.append(
            "PATCH_NOT_MARKED_APPLIED"
        )

    return {
        "present": True,
        "expected": patch_expected,
        "valid": not errors,
        "path": (
            str(patch_path)
            if patch_path is not None
            else None
        ),
        "expected_sha256": (
            expected_sha256
        ),
        "actual_sha256": actual_sha256,
        "sha256_match": (
            actual_sha256
            == expected_sha256
        ),
        "applicable": patch.get(
            "applicable"
        ),
        "applied": patch.get(
            "applied"
        ),
        "changed_files": patch.get(
            "changed_files"
        ),
        "patch_check": patch_check,
        "errors": errors,
    }


def inspect_verification(
    mission: dict[str, Any],
) -> dict[str, Any]:
    task = _task_by_type(
        mission,
        "VERIFICATION",
    )
    result = _load_task_result(
        task
    )

    status = _task_status(
        mission,
        "VERIFICATION",
    )

    passed = (
        result.get("passed")
        if isinstance(result, dict)
        else None
    )

    errors: list[str] = []

    if (
        status == "COMPLETED"
        and passed is not True
    ):
        errors.append(
            "VERIFICATION_COMPLETED_WITHOUT_PASS"
        )

    return {
        "status": status,
        "result_present": (
            result is not None
        ),
        "passed": passed,
        "valid": not errors,
        "result": result,
        "errors": errors,
    }


def inspect_commit(
    implementation: dict[str, Any],
) -> dict[str, Any]:
    mode = str(
        implementation.get("mode")
        or ""
    ).strip().upper()

    commit = implementation.get(
        "commit"
    )

    errors: list[str] = []

    if mode == "COMMITTED":
        if not isinstance(commit, dict):
            errors.append(
                "COMMIT_METADATA_MISSING"
            )
        else:
            if (
                commit.get("committed")
                is not True
            ):
                errors.append(
                    "COMMIT_FLAG_INVALID"
                )

            commit_hash = commit.get(
                "commit_hash"
            )

            if (
                not isinstance(
                    commit_hash,
                    str,
                )
                or len(commit_hash) != 40
            ):
                errors.append(
                    "COMMIT_HASH_INVALID"
                )

    return {
        "mode": mode,
        "committed": (
            commit.get("committed")
            if isinstance(commit, dict)
            else False
        ),
        "commit_hash": (
            commit.get("commit_hash")
            if isinstance(commit, dict)
            else None
        ),
        "valid": not errors,
        "commit": commit,
        "errors": errors,
    }


def inspect_reporting(
    mission: dict[str, Any],
) -> dict[str, Any]:
    task = _task_by_type(
        mission,
        "REPORTING",
    )
    result = _load_task_result(
        task
    )
    status = _task_status(
        mission,
        "REPORTING",
    )

    errors: list[str] = []

    if (
        status == "COMPLETED"
        and result is None
    ):
        errors.append(
            "REPORTING_RESULT_MISSING"
        )

    return {
        "status": status,
        "result_present": (
            result is not None
        ),
        "valid": not errors,
        "result": result,
        "errors": errors,
    }


def _resume_action(
    stage: str,
) -> str:
    mapping = {
        "RUN_ANALYSIS": "RUN_ANALYSIS",
        "RUN_PLANNING": "RUN_PLANNING",
        "WAIT_MISSION_APPROVAL": (
            "APPROVE_MISSION"
        ),
        "RUN_IMPLEMENTATION_DRY_RUN": (
            "RUN_IMPLEMENTATION_DRY_RUN"
        ),
        "WAIT_PATCH_APPLY_APPROVAL": (
            "APPLY_PATCH"
        ),
        "RUN_VERIFICATION": (
            "RUN_VERIFICATION"
        ),
        "WAIT_COMMIT_APPROVAL": (
            "COMMIT_CHANGES"
        ),
        "RUN_REPORTING": (
            "RUN_REPORTING"
        ),
        "MISSION_COMPLETED": (
            "REVIEW_FINAL_REPORT"
        ),
        "MISSION_FAILED": (
            "INSPECT_MISSION_FAILURE"
        ),
        "MISSION_CANCELLED": (
            "NO_ACTION"
        ),
        "REPAIR_REQUIRED": (
            "RUN_REPAIR_INSPECTION"
        ),
        "STATE_BLOCKED": (
            "INSPECT_STATE_BLOCK"
        ),
    }

    return mapping.get(
        stage,
        "INSPECT_MANUALLY",
    )


def inspect_mission_recovery(
    *,
    mission_id: int,
) -> dict[str, Any]:
    inspected_at = _now()

    mission = get_mission(
        mission_id
    )

    mission_state = (
        inspect_mission_state(
            mission
        )
    )

    implementation_task = (
        _task_by_type(
            mission,
            "IMPLEMENTATION",
        )
    )

    implementation = (
        _load_task_result(
            implementation_task
        )
    )

    if not isinstance(
        implementation,
        dict,
    ):
        implementation = {}

    backup = inspect_backup(
        mission_id=mission_id,
        implementation=implementation,
    )

    git_state = inspect_git_state(
        implementation=implementation,
        manifest=backup.get(
            "manifest"
        ),
    )

    backup_files = (
        inspect_backup_files(
            implementation=implementation,
            backup_result=backup,
        )
    )

    patch = inspect_patch(
        mission_id=mission_id,
        implementation=implementation,
    )

    verification = (
        inspect_verification(
            mission
        )
    )

    commit = inspect_commit(
        implementation
    )

    reporting = inspect_reporting(
        mission
    )

    all_errors: list[str] = []

    for section_name, section in (
        ("backup", backup),
        ("git", git_state),
        ("backup_files", backup_files),
        ("patch", patch),
        ("verification", verification),
        ("commit", commit),
        ("reporting", reporting),
    ):
        section_errors = section.get(
            "errors"
        )

        if isinstance(
            section_errors,
            list,
        ):
            for error in section_errors:
                all_errors.append(
                    f"{section_name}:"
                    f"{error}"
                )

    stage = str(
        mission_state.get(
            "orchestrator_stage"
        )
        or ""
    ).strip().upper()

    blocked_stage = stage in {
        "STATE_BLOCKED",
        "MISSION_FAILED",
    }

    state_consistent = (
        not all_errors
    )

    safe_to_resume = (
        state_consistent
        and not blocked_stage
    )

    required_action = (
        _resume_action(stage)
    )

    return {
        "recovery_version": (
            MISSION_RECOVERY_VERSION
        ),
        "inspected_at": inspected_at,
        "mission_id": mission_id,
        "current_stage": stage,
        "required_action": (
            required_action
        ),
        "requires_master_action": (
            mission_state.get(
                "requires_master_action"
            )
            is True
        ),
        "recoverable": safe_to_resume,
        "safe_to_resume": safe_to_resume,
        "state_consistent": (
            state_consistent
        ),
        "error_count": len(
            all_errors
        ),
        "errors": all_errors,
        "mission": mission_state,
        "implementation": {
            "status": _task_status(
                mission,
                "IMPLEMENTATION",
            ),
            "mode": implementation.get(
                "mode"
            ),
            "write_enabled": (
                implementation.get(
                    "write_enabled"
                )
            ),
            "files_modified": (
                implementation.get(
                    "files_modified"
                )
            ),
        },
        "backup": backup,
        "backup_files": backup_files,
        "git": git_state,
        "patch": patch,
        "verification": verification,
        "commit": commit,
        "reporting": reporting,
        "safety": {
            "read_only": True,
            "mission_changed": False,
            "database_changed": False,
            "project_files_changed": False,
            "git_changed": False,
            "patch_apply_executed": False,
            "commit_executed": False,
            "automatic_recovery": False,
        },
    }


def inspect_mission_recovery_safe(
    *,
    mission_id: int,
) -> dict[str, Any]:
    try:
        return inspect_mission_recovery(
            mission_id=mission_id
        )
    except (
        MissionRecoveryError,
        MissionError,
    ) as error:
        raise MissionRecoveryError(
            str(error)
        ) from error
