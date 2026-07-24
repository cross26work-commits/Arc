from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app.database as database
from app.missions.mission_recovery import (
    inspect_mission_recovery_safe,
)
from app.missions.mission_recovery_resume_preview import (
    preview_mission_recovery_resume_safe,
)


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_git(
    repository: Path,
    *arguments: str,
) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        raise AssertionError(
            "Git command failed\n"
            f"command: git {' '.join(arguments)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    return completed.stdout


def _prepare_patch_checked_state(
    environment: dict[str, Any],
) -> dict[str, Any]:
    project_root = Path(
        environment["isolated_project"]
    )

    backup_root = Path(
        environment["isolated_backup_root"]
    )

    target_relative_path = (
        "backend/app/api/auth.py"
    )

    target_path = (
        project_root
        / target_relative_path
    )

    original_data = target_path.read_bytes()
    original_hash = _sha256_bytes(
        original_data
    )

    branch = _run_git(
        project_root,
        "branch",
        "--show-current",
    ).strip()

    head = _run_git(
        project_root,
        "rev-parse",
        "HEAD",
    ).strip()

    changed_text = (
        "def current_user():\n"
        "    return {'status': 'after'}\n"
    )

    target_path.write_text(
        changed_text,
        encoding="utf-8",
    )

    patch_text = _run_git(
        project_root,
        "diff",
        "--",
        target_relative_path,
    )

    target_path.write_bytes(
        original_data
    )

    assert (
        _run_git(
            project_root,
            "status",
            "--porcelain",
        ).strip()
        == ""
    )

    assert patch_text.strip()

    run_id = "preview-integration-test"

    run_root = (
        backup_root
        / "mission-1"
        / run_id
    )

    before_path = (
        run_root
        / "before"
        / target_relative_path
    )

    before_path.parent.mkdir(
        parents=True,
        exist_ok=False,
    )

    before_path.write_bytes(
        original_data
    )

    manifest = {
        "backup_version": (
            "mission-backup-v0.2"
        ),
        "mission_id": 1,
        "project_id": 1,
        "project_name": (
            "Arc Recovery Harness"
        ),
        "project_path": str(
            project_root
        ),
        "run_id": run_id,
        "created_at": _now(),
        "git": {
            "branch": branch,
            "head": head,
            "working_tree_clean": True,
        },
        "file_count": 1,
        "files": [
            {
                "path": (
                    target_relative_path
                ),
                "sha256": original_hash,
                "size_bytes": len(
                    original_data
                ),
                "backup_path": (
                    "before/"
                    + target_relative_path
                ),
                "verified": True,
            }
        ],
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

    patch_path = (
        run_root
        / "proposed.patch"
    )

    patch_path.write_text(
        patch_text,
        encoding="utf-8",
    )

    patch_sha256 = _sha256_bytes(
        patch_path.read_bytes()
    )

    patch_check_completed = (
        subprocess.run(
            [
                "git",
                "apply",
                "--check",
                "--whitespace=error-all",
                str(patch_path),
            ],
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
        )
    )

    assert (
        patch_check_completed.returncode
        == 0
    ), (
        patch_check_completed.stdout
        + patch_check_completed.stderr
    )

    patch_check = {
        "patch_engine_version": (
            "mission-patch-v0.3"
        ),
        "mission_id": 1,
        "checked_at": _now(),
        "generated_by": (
            "pytest-isolated-harness"
        ),
        "note": (
            "Recovery Preview統合テスト"
        ),
        "patch_path": str(
            patch_path
        ),
        "patch_sha256": patch_sha256,
        "patch_size_bytes": (
            patch_path.stat().st_size
        ),
        "changed_file_count": 1,
        "changed_files": [
            target_relative_path
        ],
        "backup_hash_check": {
            "verified": True,
            "file_count": 1,
        },
        "git_apply_check": {
            "command": (
                "git apply --check "
                "--whitespace=error-all "
                "proposed.patch"
            ),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "applicable": True,
        },
        "write_enabled": False,
        "applied": False,
    }

    patch_check_path = (
        run_root
        / "patch_check.json"
    )

    patch_check_path.write_text(
        json.dumps(
            patch_check,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    implementation_result = {
        "implementation_version": (
            "mission-implementation-v0.3"
        ),
        "mode": "PATCH_CHECKED",
        "mission_id": 1,
        "project_id": 1,
        "project_name": (
            "Arc Recovery Harness"
        ),
        "project_path": str(
            project_root
        ),
        "plan_version": (
            "mission-planner-v0.1"
        ),
        "risk": {
            "level": "low",
            "label": "低",
            "score": 0,
        },
        "effort": {
            "level": "small",
            "label": "小",
            "estimated_minutes": 1,
        },
        "selected_file_count": 1,
        "selected_files": [
            {
                "path": (
                    target_relative_path
                ),
                "role": "test target",
                "score": 1,
                "size_bytes": len(
                    original_data
                ),
            }
        ],
        "verification_commands": [
            {
                "name": "Git diff check",
                "command": "git diff --check",
            }
        ],
        "git": {
            "original_branch": branch,
            "original_head": head,
            "branch_name": branch,
            "branch_created": False,
            "current_branch": branch,
        },
        "write_enabled": False,
        "files_modified": 0,
        "next_stage": (
            "明示承認後にPatchを実適用する"
        ),
        "backup": {
            "run_id": run_id,
            "root_path": str(
                run_root
            ),
            "manifest_path": str(
                manifest_path
            ),
            "file_count": 1,
            "restore_ready": True,
        },
        "patch": {
            "path": str(
                patch_path
            ),
            "result_path": str(
                patch_check_path
            ),
            "sha256": patch_sha256,
            "changed_file_count": 1,
            "changed_files": [
                target_relative_path
            ],
            "applicable": True,
            "applied": False,
        },
    }

    with database.get_connection() as connection:
        connection.execute(
            """
            UPDATE projects
            SET
                name = ?,
                path = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                "Arc Recovery Harness",
                str(project_root),
                _now(),
                1,
            ),
        )

        connection.execute(
            """
            UPDATE missions
            SET
                status = 'APPROVED',
                progress = 57,
                next_action = ?,
                error_count = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                (
                    "Patch検証完了。"
                    "実適用の明示承認を"
                    "待っています。"
                ),
                _now(),
                1,
            ),
        )

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'RUNNING',
                target_path = ?,
                result = ?,
                updated_at = ?
            WHERE mission_id = ?
              AND task_type = 'IMPLEMENTATION'
            """,
            (
                target_relative_path,
                json.dumps(
                    implementation_result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                _now(),
                1,
            ),
        )

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'PENDING',
                result = NULL,
                updated_at = ?
            WHERE mission_id = ?
              AND task_type IN (
                  'VERIFICATION',
                  'REPORTING'
              )
            """,
            (
                _now(),
                1,
            ),
        )

        connection.commit()

    return {
        "project_root": project_root,
        "target_path": target_path,
        "original_data": original_data,
        "run_root": run_root,
        "manifest_path": manifest_path,
        "patch_path": patch_path,
        "patch_check_path": (
            patch_check_path
        ),
        "patch_sha256": patch_sha256,
        "branch": branch,
        "head": head,
    }


def test_recovery_inspector_uses_only_isolated_paths(
    isolated_arc_environment: dict[str, Any],
) -> None:
    prepared = (
        _prepare_patch_checked_state(
            isolated_arc_environment
        )
    )

    recovery = (
        inspect_mission_recovery_safe(
            mission_id=1
        )
    )

    isolated_project = Path(
        isolated_arc_environment[
            "isolated_project"
        ]
    ).resolve()

    isolated_backup_root = Path(
        isolated_arc_environment[
            "isolated_backup_root"
        ]
    ).resolve()

    assert (
        recovery["current_stage"]
        == "WAIT_PATCH_APPLY_APPROVAL"
    )

    assert (
        recovery["required_action"]
        == "APPLY_PATCH"
    )

    assert recovery["recoverable"] is True
    assert recovery["safe_to_resume"] is True
    assert recovery["state_consistent"] is True
    assert recovery["error_count"] == 0
    assert recovery["errors"] == []

    assert (
        Path(
            recovery["git"][
                "project_path"
            ]
        ).resolve()
        == isolated_project
    )

    assert (
        Path(
            recovery["backup"][
                "root_path"
            ]
        ).resolve()
        .is_relative_to(
            isolated_backup_root
        )
    )

    assert (
        Path(
            recovery["patch"]["path"]
        ).resolve()
        .is_relative_to(
            isolated_backup_root
        )
    )

    assert (
        recovery["patch"][
            "actual_sha256"
        ]
        == prepared["patch_sha256"]
    )

    assert (
        recovery["patch"][
            "sha256_match"
        ]
        is True
    )

    assert (
        recovery["patch"][
            "applicable"
        ]
        is True
    )

    assert (
        recovery["patch"][
            "applied"
        ]
        is False
    )


def test_recovery_preview_is_valid_and_read_only(
    isolated_arc_environment: dict[str, Any],
) -> None:
    prepared = (
        _prepare_patch_checked_state(
            isolated_arc_environment
        )
    )

    target_path = Path(
        prepared["target_path"]
    )

    content_before = (
        target_path.read_bytes()
    )

    git_status_before = _run_git(
        prepared["project_root"],
        "status",
        "--porcelain",
    )

    with database.get_connection() as connection:
        database_changes_before = (
            connection.total_changes
        )

    preview = (
        preview_mission_recovery_resume_safe(
            mission_id=1
        )
    )

    with database.get_connection() as connection:
        database_changes_after = (
            connection.total_changes
        )

    git_status_after = _run_git(
        prepared["project_root"],
        "status",
        "--porcelain",
    )

    assert (
        preview["preview_version"]
        == (
            "mission-recovery-"
            "resume-preview-v0.1"
        )
    )

    assert preview["mission_id"] == 1

    assert (
        preview["current_stage"]
        == "WAIT_PATCH_APPLY_APPROVAL"
    )

    assert (
        preview["required_action"]
        == "APPLY_PATCH"
    )

    assert (
        preview["resume_handler"]
        == (
            "apply_mission_"
            "implementation_patch_safe"
        )
    )

    assert (
        preview["resume_endpoint"]
        == (
            "/missions/{mission_id}/"
            "recovery-resume"
        )
    )

    assert preview["http_method"] == "POST"

    assert (
        preview["next_expected_stage"]
        == "RUN_VERIFICATION"
    )

    assert (
        preview["intermediate_state"]
        == "PATCH_APPLIED"
    )

    assert (
        preview["requires_master_action"]
        is True
    )

    assert (
        preview["dangerous_action"]
        is True
    )

    assert (
        preview["execution_allowed"]
        is False
    )

    assert preview["preview_valid"] is True

    assert (
        preview[
            "expected_patch_sha256"
        ]
        == prepared["patch_sha256"]
    )

    assert len(
        preview[
            "expected_patch_sha256"
        ]
    ) == 64

    assert (
        preview["failed_preconditions"]
        == []
    )

    assert preview["blockers"] == []

    assert all(
        item["satisfied"] is True
        for item in preview[
            "preconditions"
        ]
    )

    assert (
        preview["effects_if_executed"]
        == {
            "would_change_database": True,
            "would_change_project_files": True,
            "would_change_git": True,
        }
    )

    assert preview["recovery_summary"] == {
        "recoverable": True,
        "safe_to_resume": True,
        "state_consistent": True,
        "error_count": 0,
        "errors": [],
    }

    assert preview["safety"] == {
        "preview_only": True,
        "read_only": True,
        "execution_performed": False,
        "mission_changed": False,
        "database_changed": False,
        "project_files_changed": False,
        "git_changed": False,
        "patch_apply_executed": False,
        "verification_executed": False,
        "commit_executed": False,
        "reporting_executed": False,
        "automatic_recovery": False,
        "automatic_master_approval": False,
    }

    assert (
        target_path.read_bytes()
        == content_before
    )

    assert (
        git_status_after
        == git_status_before
        == ""
    )

    assert (
        database_changes_after
        == database_changes_before
        == 0
    )
