from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app import database
from app.missions.mission_recovery_resume_controller import (
    MissionRecoveryResumeControllerError,
    resume_mission_recovery_safe,
)
from app.missions.mission_recovery_resume_preview import (
    preview_mission_recovery_resume_safe,
)
from app.missions.models import (
    MissionRecoveryResumeRequest,
)
from app.missions.service import (
    get_mission,
)


TESTS_ROOT = Path(__file__).resolve().parent

PREVIEW_TEST_PATH = (
    TESTS_ROOT
    / "test_mission_recovery_preview_integration.py"
)


def _load_preview_test_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "arc_recovery_preview_test_helpers",
        PREVIEW_TEST_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Preview統合テストHelperを"
            "読み込めません。"
        )

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(module)

    return module


_PREVIEW_HELPERS = (
    _load_preview_test_module()
)

_prepare_patch_checked_state = getattr(
    _PREVIEW_HELPERS,
    "_prepare_patch_checked_state",
)

_run_git = getattr(
    _PREVIEW_HELPERS,
    "_run_git",
)


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    tasks = mission.get("tasks")

    assert isinstance(tasks, list)

    for task in tasks:
        if (
            isinstance(task, dict)
            and task.get("task_type")
            == task_type
        ):
            return task

    raise AssertionError(
        f"Taskが見つかりません: {task_type}"
    )


def _database_snapshot() -> dict[str, Any]:
    mission = get_mission(1)

    return {
        "mission_status": mission.get(
            "status"
        ),
        "mission_progress": mission.get(
            "progress"
        ),
        "mission_next_action": mission.get(
            "next_action"
        ),
        "implementation": {
            "status": _task_by_type(
                mission,
                "IMPLEMENTATION",
            ).get("status"),
            "result": _task_by_type(
                mission,
                "IMPLEMENTATION",
            ).get("result"),
        },
        "verification": {
            "status": _task_by_type(
                mission,
                "VERIFICATION",
            ).get("status"),
            "result": _task_by_type(
                mission,
                "VERIFICATION",
            ).get("result"),
        },
        "reporting": {
            "status": _task_by_type(
                mission,
                "REPORTING",
            ).get("status"),
            "result": _task_by_type(
                mission,
                "REPORTING",
            ).get("result"),
        },
    }


def test_recovery_resume_requires_explicit_approval(
    isolated_arc_environment: dict[str, Any],
) -> None:
    prepared = _prepare_patch_checked_state(
        isolated_arc_environment
    )

    target_path = Path(
        prepared["target_path"]
    )

    content_before = target_path.read_bytes()

    git_before = _run_git(
        prepared["project_root"],
        "status",
        "--porcelain",
    )

    database_before = _database_snapshot()

    with pytest.raises(
        MissionRecoveryResumeControllerError,
        match="approved=true",
    ):
        resume_mission_recovery_safe(
            mission_id=1,
            payload=MissionRecoveryResumeRequest(
                approved=False,
                action="APPLY_PATCH",
                expected_current_stage=(
                    "WAIT_PATCH_APPLY_APPROVAL"
                ),
                expected_patch_sha256=(
                    prepared["patch_sha256"]
                ),
                continue_cycle=False,
            ),
        )

    assert target_path.read_bytes() == content_before

    assert (
        _run_git(
            prepared["project_root"],
            "status",
            "--porcelain",
        )
        == git_before
        == ""
    )

    assert _database_snapshot() == database_before

    assert not (
        prepared["run_root"]
        / "patch_apply.json"
    ).exists()


def test_recovery_resume_rejects_stage_mismatch(
    isolated_arc_environment: dict[str, Any],
) -> None:
    prepared = _prepare_patch_checked_state(
        isolated_arc_environment
    )

    target_path = Path(
        prepared["target_path"]
    )

    content_before = target_path.read_bytes()
    database_before = _database_snapshot()

    with pytest.raises(
        MissionRecoveryResumeControllerError,
        match="Stage",
    ):
        resume_mission_recovery_safe(
            mission_id=1,
            payload=MissionRecoveryResumeRequest(
                approved=True,
                action="APPLY_PATCH",
                expected_current_stage=(
                    "RUN_VERIFICATION"
                ),
                expected_patch_sha256=(
                    prepared["patch_sha256"]
                ),
                continue_cycle=False,
            ),
        )

    assert target_path.read_bytes() == content_before

    assert (
        _run_git(
            prepared["project_root"],
            "status",
            "--porcelain",
        ).strip()
        == ""
    )

    assert _database_snapshot() == database_before

    assert not (
        prepared["run_root"]
        / "patch_apply.json"
    ).exists()


def test_recovery_resume_rejects_patch_hash_mismatch(
    isolated_arc_environment: dict[str, Any],
) -> None:
    prepared = _prepare_patch_checked_state(
        isolated_arc_environment
    )

    target_path = Path(
        prepared["target_path"]
    )

    content_before = target_path.read_bytes()
    database_before = _database_snapshot()

    wrong_hash = "0" * 64

    assert (
        wrong_hash
        != prepared["patch_sha256"]
    )

    with pytest.raises(
        MissionRecoveryResumeControllerError,
        match="Patch Hash",
    ):
        resume_mission_recovery_safe(
            mission_id=1,
            payload=MissionRecoveryResumeRequest(
                approved=True,
                action="APPLY_PATCH",
                expected_current_stage=(
                    "WAIT_PATCH_APPLY_APPROVAL"
                ),
                expected_patch_sha256=wrong_hash,
                continue_cycle=False,
            ),
        )

    assert target_path.read_bytes() == content_before

    assert (
        _run_git(
            prepared["project_root"],
            "status",
            "--porcelain",
        ).strip()
        == ""
    )

    assert _database_snapshot() == database_before

    assert not (
        prepared["run_root"]
        / "patch_apply.json"
    ).exists()


def test_recovery_resume_applies_patch_only_to_isolated_project(
    isolated_arc_environment: dict[str, Any],
) -> None:
    prepared = _prepare_patch_checked_state(
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

    assert project_root == isolated_project
    assert run_root.is_relative_to(
        isolated_backup_root
    )

    original_data = target_path.read_bytes()

    preview = (
        preview_mission_recovery_resume_safe(
            mission_id=1
        )
    )

    assert preview["preview_valid"] is True

    assert (
        preview["current_stage"]
        == "WAIT_PATCH_APPLY_APPROVAL"
    )

    assert (
        preview["required_action"]
        == "APPLY_PATCH"
    )

    assert (
        preview["expected_patch_sha256"]
        == prepared["patch_sha256"]
    )

    result = resume_mission_recovery_safe(
        mission_id=1,
        payload=MissionRecoveryResumeRequest(
            approved=True,
            action="APPLY_PATCH",
            expected_current_stage=(
                preview["current_stage"]
            ),
            expected_patch_sha256=(
                preview[
                    "expected_patch_sha256"
                ]
            ),
            reason=(
                "Recovery Resume隔離統合テスト"
            ),
            decided_by=(
                "pytest-isolated-harness"
            ),
            note=(
                "Phase28-5B-5-2"
            ),
            continue_cycle=False,
            max_steps=1,
        ),
    )

    assert (
        result["controller_version"]
        == (
            "mission-recovery-"
            "resume-controller-v0.1"
        )
    )

    assert result["mission_id"] == 1
    assert result["approved"] is True

    assert result["action"] == "APPLY_PATCH"

    assert (
        result["confirmed_stage"]
        == "WAIT_PATCH_APPLY_APPROVAL"
    )

    assert (
        result["expected_patch_sha256"]
        == prepared["patch_sha256"]
    )

    assert (
        result["delegated_to"]
        == "approve_and_resume_mission_safe"
    )

    assert result["safety"] == {
        "explicit_approval_required": True,
        "recovery_preview_rechecked": True,
        "stage_rechecked": True,
        "action_rechecked": True,
        "patch_hash_rechecked": True,
        "approval_preview_rechecked": True,
        "controller_direct_patch_apply": False,
        "controller_direct_commit": False,
        "controller_direct_database_write": False,
        "existing_runner_delegation_only": True,
    }

    execution_result = result[
        "execution_result"
    ]

    assert isinstance(
        execution_result,
        dict,
    )

    resume = execution_result["resume"]

    assert resume["action"] == "APPLY_PATCH"

    assert (
        resume["approved_or_confirmed_by"]
        == "pytest-isolated-harness"
    )

    assert resume["cycle_started"] is False
    assert resume["cycle"] is None

    explicit_action = resume[
        "explicit_action"
    ]

    assert (
        explicit_action["action"]
        == "APPLY_PATCH"
    )

    assert explicit_action["executed"] is True

    action_result = explicit_action["result"]

    assert action_result["applied"] is True

    assert (
        action_result["changed_file_count"]
        == 1
    )

    assert action_result["changed_files"] == [
        "backend/app/api/auth.py"
    ]

    assert target_path.read_bytes() != original_data

    assert (
        target_path.read_text(
            encoding="utf-8"
        )
        == (
            "def current_user():\n"
            "    return {'status': 'after'}\n"
        )
    )

    git_status = _run_git(
        project_root,
        "status",
        "--porcelain",
    )

    assert (
        "backend/app/api/auth.py"
        in git_status
    )

    assert (
        _run_git(
            project_root,
            "diff",
            "--name-only",
        ).strip()
        == "backend/app/api/auth.py"
    )

    apply_result_path = (
        run_root
        / "patch_apply.json"
    )

    assert apply_result_path.exists()

    assert apply_result_path.resolve().is_relative_to(
        isolated_backup_root
    )

    apply_record = json.loads(
        apply_result_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        apply_record[
            "patch_apply_version"
        ]
        == "mission-patch-apply-v0.4"
    )

    assert apply_record["mission_id"] == 1
    assert apply_record["applied"] is True
    assert apply_record["rolled_back"] is False

    assert (
        apply_record["patch_sha256"]
        == prepared["patch_sha256"]
    )

    assert (
        apply_record["changed_file_count"]
        == 1
    )

    assert apply_record["changed_files"] == [
        "backend/app/api/auth.py"
    ]

    assert (
        apply_record["working_tree_clean"]
        is False
    )

    mission = get_mission(1)

    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )

    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    reporting_task = _task_by_type(
        mission,
        "REPORTING",
    )

    assert (
        implementation_task["status"]
        == "COMPLETED"
    )

    implementation_result = json.loads(
        implementation_task["result"]
    )

    assert (
        implementation_result["mode"]
        == "PATCH_APPLIED"
    )

    assert (
        implementation_result[
            "write_enabled"
        ]
        is True
    )

    assert (
        implementation_result[
            "files_modified"
        ]
        == 1
    )

    assert (
        implementation_result[
            "modified_files"
        ]
        == [
            "backend/app/api/auth.py"
        ]
    )

    assert (
        implementation_result["patch"][
            "applied"
        ]
        is True
    )

    assert (
        Path(
            implementation_result[
                "patch"
            ][
                "apply_result_path"
            ]
        ).resolve()
        == apply_result_path.resolve()
    )

    # continue_cycle=Falseのため、
    # Verification Runner自体は実行しない。
    #
    # IMPLEMENTATION完了により、
    # 次のVERIFICATION TaskはREADYへ遷移する。
    # REPORTINGはまだ開始条件を満たさないため
    # PENDINGのままとする。
    assert (
        verification_task["status"]
        == "READY"
    )

    assert (
        verification_task["result"]
        is None
    )

    assert (
        reporting_task["status"]
        == "PENDING"
    )

    assert (
        reporting_task["result"]
        is None
    )

    with database.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT event_type
            FROM mission_logs
            WHERE mission_id = ?
              AND event_type IN (
                  'MISSION_IMPLEMENTATION_PATCH_APPLIED',
                  'MISSION_APPROVAL_RESUMED'
              )
            ORDER BY id ASC
            """,
            (1,),
        ).fetchall()

    event_types = [
        row["event_type"]
        for row in rows
    ]

    assert (
        "MISSION_IMPLEMENTATION_PATCH_APPLIED"
        in event_types
    )

    assert (
        "MISSION_APPROVAL_RESUMED"
        in event_types
    )
