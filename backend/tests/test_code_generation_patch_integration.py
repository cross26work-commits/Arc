from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app import database
from app.code_generation import (
    CODE_GENERATION_CONTRACT_VERSION,
    PATCH_INTEGRATION_VERSION,
    CodeGenerationPatchIntegrationError,
    run_code_generation_patch_integration,
    run_code_generation_patch_integration_safe,
)


CONTEXT_SHA256 = "d" * 64

TARGET_PATH = "backend/app/api/auth.py"


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


def _context_payload() -> dict[str, Any]:
    return {
        "mission_id": 1,
        "sha256": CONTEXT_SHA256,
        "files": [
            {
                "relative_path": TARGET_PATH,
                "content": (
                    "def current_user():\n"
                    "    return {'status': 'before'}\n"
                ),
            }
        ],
    }


def _contract_payload() -> dict[str, Any]:
    return {
        "contract_version": (
            CODE_GENERATION_CONTRACT_VERSION
        ),
        "mission_id": 1,
        "context_sha256": CONTEXT_SHA256,
        "summary": (
            "current_user関数へ戻り値型を追加する。"
        ),
        "reasoning": (
            "Code Context内で一意な関数定義だけを"
            "安全に置換する。"
        ),
        "edits": [
            {
                "operation": "REPLACE_UNIQUE",
                "path": TARGET_PATH,
                "old_text": (
                    "def current_user():\n"
                ),
                "new_text": (
                    "def current_user() -> dict:\n"
                ),
            }
        ],
        "generated_by": (
            "pytest-code-generation-integration"
        ),
        "assumptions": [],
        "warnings": [],
    }


def _prepare_backup_ready_state(
    environment: dict[str, Any],
) -> dict[str, Any]:
    project_root = Path(
        environment["isolated_project"]
    ).resolve()

    backup_root = Path(
        environment["isolated_backup_root"]
    ).resolve()

    target_path = (
        project_root
        / TARGET_PATH
    ).resolve()

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

    assert (
        _run_git(
            project_root,
            "status",
            "--porcelain",
        ).strip()
        == ""
    )

    run_id = "code-generation-integration-test"

    run_root = (
        backup_root
        / "mission-1"
        / run_id
    )

    before_path = (
        run_root
        / "before"
        / TARGET_PATH
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
            "Arc Code Generation Harness"
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
                "path": TARGET_PATH,
                "sha256": original_hash,
                "size_bytes": len(
                    original_data
                ),
                "backup_path": (
                    "before/"
                    + TARGET_PATH
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

    implementation_result = {
        "implementation_version": (
            "mission-implementation-v0.2"
        ),
        "mode": "BACKUP_READY",
        "mission_id": 1,
        "project_id": 1,
        "project_name": (
            "Arc Code Generation Harness"
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
                "path": TARGET_PATH,
                "role": (
                    "code generation test target"
                ),
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
            "Unified Diff生成と"
            "git apply --checkを実行する"
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
                "Arc Code Generation Harness",
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
                    "Backup完了。"
                    "Patch生成・検証へ進む。"
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
                TARGET_PATH,
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
        "branch": branch,
        "head": head,
    }


def test_contract_to_patch_check_integration(
    isolated_arc_environment: dict[str, Any],
) -> None:
    prepared = _prepare_backup_ready_state(
        isolated_arc_environment
    )

    project_root = Path(
        prepared["project_root"]
    ).resolve()

    target_path = Path(
        prepared["target_path"]
    ).resolve()

    run_root = Path(
        prepared["run_root"]
    ).resolve()

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

    content_before = target_path.read_bytes()

    assert project_root == isolated_project

    assert run_root.is_relative_to(
        isolated_backup_root
    )

    assert (
        _run_git(
            project_root,
            "status",
            "--porcelain",
        ).strip()
        == ""
    )

    result = (
        run_code_generation_patch_integration(
            mission_id=1,
            payload=_contract_payload(),
            context=_context_payload(),
        )
    )

    assert result["integrated"] is True

    assert result["integration_version"] == (
        PATCH_INTEGRATION_VERSION
    )

    assert result["mission_id"] == 1

    assert result["edit_count"] == 1

    assert result["changed_file_count"] == 1

    assert result["changed_files"] == [
        TARGET_PATH
    ]

    assert result["patch_applicable"] is True

    assert result["patch_applied"] is False

    assert result["next_stage"] == (
        "WAIT_PATCH_APPLY_APPROVAL"
    )

    assert (
        result["implementation"]["mode"]
        == "PATCH_CHECKED"
    )

    assert (
        result["patch_check"][
            "git_apply_check"
        ]["applicable"]
        is True
    )

    assert (
        result["patch_check"][
            "git_apply_check"
        ]["returncode"]
        == 0
    )

    assert (
        result["patch_check"]["applied"]
        is False
    )

    assert (
        "def current_user() -> dict:"
        in result["patch_text"]
    )

    assert (
        "def current_user():"
        in result["patch_text"]
    )

    assert isinstance(
        result["patch_sha256"],
        str,
    )

    assert len(
        result["patch_sha256"]
    ) == 64

    assert target_path.read_bytes() == (
        content_before
    )

    assert (
        _run_git(
            project_root,
            "status",
            "--porcelain",
        ).strip()
        == ""
    )

    generator_path = (
        run_root
        / "patch_generator.json"
    )

    patch_path = (
        run_root
        / "proposed.patch"
    )

    patch_check_path = (
        run_root
        / "patch_check.json"
    )

    assert generator_path.is_file()
    assert patch_path.is_file()
    assert patch_check_path.is_file()

    assert (
        patch_path.read_text(
            encoding="utf-8"
        )
        == result["patch_text"]
    )


def test_integration_rejects_mission_id_mismatch(
    isolated_arc_environment: dict[str, Any],
) -> None:
    _prepare_backup_ready_state(
        isolated_arc_environment
    )

    with pytest.raises(
        CodeGenerationPatchIntegrationError,
        match="Mission ID",
    ):
        run_code_generation_patch_integration_safe(
            mission_id=2,
            payload=_contract_payload(),
            context=_context_payload(),
        )


def test_integration_rejects_context_hash_mismatch(
    isolated_arc_environment: dict[str, Any],
) -> None:
    _prepare_backup_ready_state(
        isolated_arc_environment
    )

    payload = _contract_payload()
    payload["context_sha256"] = "e" * 64

    with pytest.raises(
        CodeGenerationPatchIntegrationError,
        match="SHA-256",
    ):
        run_code_generation_patch_integration_safe(
            mission_id=1,
            payload=payload,
            context=_context_payload(),
        )


def test_integration_rejects_path_outside_context(
    isolated_arc_environment: dict[str, Any],
) -> None:
    _prepare_backup_ready_state(
        isolated_arc_environment
    )

    payload = _contract_payload()

    payload["edits"][0]["path"] = (
        "backend/app/api/unknown.py"
    )

    with pytest.raises(
        CodeGenerationPatchIntegrationError,
        match="Code Context内",
    ):
        run_code_generation_patch_integration_safe(
            mission_id=1,
            payload=payload,
            context=_context_payload(),
        )


def test_integration_rejects_non_unique_old_text(
    isolated_arc_environment: dict[str, Any],
) -> None:
    _prepare_backup_ready_state(
        isolated_arc_environment
    )

    context = _context_payload()

    context["files"][0]["content"] = (
        "def current_user():\n"
        "    return {'status': 'first'}\n"
        "\n"
        "def current_user():\n"
        "    return {'status': 'second'}\n"
    )

    with pytest.raises(
        CodeGenerationPatchIntegrationError,
        match="一意ではありません",
    ):
        run_code_generation_patch_integration_safe(
            mission_id=1,
            payload=_contract_payload(),
            context=context,
        )
