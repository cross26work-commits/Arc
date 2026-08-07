from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from app.missions.implementation_runner import (
    apply_mission_implementation_patch_safe,
    create_mission_implementation_backup_safe,
)
from app.missions.models import (
    MissionPatchApplyRequest,
    MissionPatchEdit,
    MissionPatchGenerateRequest,
    MissionTaskUpdate,
)
from app.missions.patch_generator import (
    generate_mission_patch_safe,
)
from app.missions.verification_runner import (
    run_mission_verification_safe,
)


MISSION_ID = 36
PROJECT_ID = 1

FIXTURE_ROOT = Path(
    r"C:\Users\closs\ArcRepairFixture"
)

TARGET_RELATIVE_PATH = "src/calculator.py"

BROKEN_BLOCK = (
    "def multiply(left: int, right: int) -> int:\n"
    '    """Return the product of two integers."""\n'
    "    return left + right"
)

FIXED_BLOCK = (
    "def multiply(left: int, right: int) -> int:\n"
    '    """Return the product of two integers."""\n'
    "    return left * right"
)


def _initial_implementation_result() -> dict:
    return {
        "implementation_version": (
            "mission-implementation-v0.1"
        ),
        "mode": "DRY_RUN",
        "mission_id": MISSION_ID,
        "project_id": PROJECT_ID,
        "project_name": "ArcRepairFixture",
        "project_path": str(FIXTURE_ROOT),
        "selected_file_count": 1,
        "selected_files": [
            {
                "path": TARGET_RELATIVE_PATH,
                "reason": (
                    "Repair broken multiply behavior"
                ),
            }
        ],
        "verification_commands": [
            {
                "name": "pytest",
                "command": "cd backend && venv/bin/python -m pytest",
                "category": "TEST",
            }
        ],
        "git": {
            "original_branch": "arc/repair-e2e",
            "original_head": "",
            "branch_name": "arc/repair-e2e",
            "branch_created": False,
            "current_branch": "arc/repair-e2e",
        },
        "write_enabled": False,
        "files_modified": 0,
        "step_execution": {
            "enabled": True,
            "current_step_id": "repair-step-1",
            "ordered_step_ids": [
                "repair-step-1",
            ],
            "results": {
                "repair-step-1": {
                    "step_id": "repair-step-1",
                    "status": "PATCH_READY",
                    "target_paths": [
                        TARGET_RELATIVE_PATH,
                    ],
                },
            },
        },
    }


def _state() -> dict:
    return {
        "mission": {
            "id": MISSION_ID,
            "project_id": PROJECT_ID,
            "title": "Real Repair Engine E2E",
            "status": "RUNNING",
            "progress": 80,
            "next_action": None,
        },
        "tasks": {
            361: {
                "id": 361,
                "mission_id": MISSION_ID,
                "task_type": "PLANNING",
                "position": 1,
                "status": "COMPLETED",
                "result": json.dumps(
                    {
                        "plan_version": (
                            "real-repair-plan-v0.1"
                        ),
                        "selected_files": [
                            {
                                "path": (
                                    TARGET_RELATIVE_PATH
                                ),
                                "reason": (
                                    "Repair multiply behavior"
                                ),
                            }
                        ],
                        "verification_commands": [
                            {
                                "name": "pytest",
                                "command": (
                                    "cd backend && venv/bin/python -m pytest"
                                ),
                                "category": "TEST",
                            }
                        ],
                    }
                ),
                "target_path": None,
            },
            362: {
                "id": 362,
                "mission_id": MISSION_ID,
                "task_type": "APPROVAL",
                "position": 2,
                "status": "COMPLETED",
                "result": None,
                "target_path": None,
            },
            363: {
                "id": 363,
                "mission_id": MISSION_ID,
                "task_type": "IMPLEMENTATION",
                "position": 3,
                "status": "RUNNING",
                "result": json.dumps(
                    _initial_implementation_result()
                ),
                "target_path": (
                    TARGET_RELATIVE_PATH
                ),
            },
            364: {
                "id": 364,
                "mission_id": MISSION_ID,
                "task_type": "VERIFICATION",
                "position": 4,
                "status": "PENDING",
                "result": None,
                "target_path": None,
            },
        },
    }


def _mission_snapshot(state: dict) -> dict:
    mission = dict(state["mission"])
    mission["tasks"] = [
        dict(task)
        for task in state["tasks"].values()
    ]
    return mission


class _FakeConnection:
    def __init__(self, state: dict):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def execute(
        self,
        sql: str,
        parameters=(),
    ):
        normalized = " ".join(
            sql.split()
        ).upper()

        if (
            "UPDATE MISSION_TASKS"
            in normalized
            and "SET RESULT = ?" in normalized
        ):
            result_text = parameters[0]
            task_id = int(parameters[-2])
            mission_id = int(parameters[-1])

            assert mission_id == MISSION_ID

            self.state["tasks"][
                task_id
            ]["result"] = result_text

            return self

        if "UPDATE MISSIONS" in normalized:
            if "STATUS = 'APPROVED'" in normalized:
                self.state[
                    "mission"
                ]["status"] = "APPROVED"

            return self

        raise AssertionError(
            "Unexpected SQL: "
            + normalized
        )

    def commit(self):
        return None


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(FIXTURE_ROOT),
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    return completed.stdout.strip()


def test_real_patch_apply_and_verification(
    tmp_path,
):
    assert (
        _git("branch", "--show-current")
        == "arc/repair-e2e"
    )
    assert _git("status", "--short") == ""

    target = (
        FIXTURE_ROOT
        / TARGET_RELATIVE_PATH
    )

    baseline_bytes = target.read_bytes()

    baseline_text = (
        baseline_bytes
        .decode("utf-8")
        .replace("\r\n", "\n")
    )

    assert BROKEN_BLOCK in baseline_text
    assert FIXED_BLOCK not in baseline_text

    state = _state()

    project = {
        "id": PROJECT_ID,
        "name": "ArcRepairFixture",
        "path": str(FIXTURE_ROOT),
    }

    backup_root = (
        tmp_path
        / "implementation_backups"
    )

    def get_mission(_mission_id):
        assert _mission_id == MISSION_ID
        return _mission_snapshot(state)

    def get_project(_project_id):
        assert _project_id == PROJECT_ID
        return dict(project)

    def get_connection():
        return _FakeConnection(state)

    def update_task(
        *,
        mission_id,
        task_id,
        payload,
    ):
        assert mission_id == MISSION_ID
        assert isinstance(
            payload,
            MissionTaskUpdate,
        )

        task = state["tasks"][task_id]

        if payload.status is not None:
            task["status"] = payload.status

        if payload.result is not None:
            task["result"] = payload.result

        if payload.target_path is not None:
            task[
                "target_path"
            ] = payload.target_path

        return _mission_snapshot(state)

    patch_payload = MissionPatchGenerateRequest(
        edits=[
            MissionPatchEdit(
                operation="REPLACE_UNIQUE",
                path=TARGET_RELATIVE_PATH,
                old_text=BROKEN_BLOCK,
                new_text=FIXED_BLOCK,
            )
        ],
        generated_by="real-repair-e2e",
        note=(
            "Real Backup, Patch Check, "
            "Apply and Verification."
        ),
    )

    try:
        with (
            patch(
                "app.missions."
                "implementation_runner."
                "IMPLEMENTATION_BACKUP_ROOT",
                backup_root,
            ),
            patch(
                "app.missions."
                "implementation_runner."
                "get_mission",
                side_effect=get_mission,
            ),
            patch(
                "app.missions."
                "implementation_runner."
                "_get_project",
                side_effect=get_project,
            ),
            patch(
                "app.missions."
                "implementation_runner."
                "get_connection",
                side_effect=get_connection,
            ),
            patch(
                "app.missions."
                "implementation_runner."
                "update_mission_task",
                side_effect=update_task,
            ),
            patch(
                "app.missions."
                "implementation_runner."
                "add_mission_log",
            ),
            patch(
                "app.missions."
                "patch_generator."
                "get_mission",
                side_effect=get_mission,
            ),
            patch(
                "app.missions."
                "patch_generator."
                "_get_project",
                side_effect=get_project,
            ),
            patch(
                "app.missions."
                "patch_generator."
                "add_mission_log",
            ),
            patch(
                "app.missions."
                "verification_runner."
                "get_mission",
                side_effect=get_mission,
            ),
            patch(
                "app.missions."
                "verification_runner."
                "_get_project",
                side_effect=get_project,
            ),
            patch(
                "app.missions."
                "verification_runner."
                "update_mission_task",
                side_effect=update_task,
            ),
            patch(
                "app.missions."
                "verification_runner."
                "add_mission_log",
            ),
        ):
            backup = (
                create_mission_implementation_backup_safe(
                    MISSION_ID
                )
            )

            assert backup[
                "implementation"
            ]["mode"] == "BACKUP_READY"

            generated = (
                generate_mission_patch_safe(
                    mission_id=MISSION_ID,
                    payload=patch_payload,
                )
            )

            checked = generated[
                "implementation"
            ]

            assert checked[
                "mode"
            ] == "PATCH_CHECKED"

            patch_sha256 = checked[
                "patch"
            ]["sha256"]

            applied = (
                apply_mission_implementation_patch_safe(
                    mission_id=MISSION_ID,
                    payload=(
                        MissionPatchApplyRequest(
                            confirmation=(
                                "APPLY_PATCH"
                            ),
                            expected_patch_sha256=(
                                patch_sha256
                            ),
                            decided_by=(
                                "arc-real-repair-e2e"
                            ),
                            note=(
                                "Apply verified repair "
                                "patch to fixture."
                            ),
                        )
                    ),
                )
            )

            applied_result = applied[
                "implementation"
            ]

            assert applied_result[
                "mode"
            ] == "PATCH_APPLIED"

            assert applied_result[
                "write_enabled"
            ] is True

            assert applied_result[
                "files_modified"
            ] == 1

            repaired_text = (
                target.read_text(
                    encoding="utf-8"
                )
                .replace("\r\n", "\n")
            )

            assert FIXED_BLOCK in repaired_text
            assert BROKEN_BLOCK not in repaired_text

            assert (
                state["tasks"][363]["status"]
                == "COMPLETED"
            )

            verified = (
                run_mission_verification_safe(
                    MISSION_ID
                )
            )

        verification = verified[
            "verification"
        ]

        print(
            "\n===== VERIFICATION RESULT ====="
        )
        print(
            json.dumps(
                verification,
                indent=2,
                ensure_ascii=False,
            )
        )
        print(
            "===== END VERIFICATION RESULT =====\n"
        )

        assert verification[
            "passed"
        ] is True

        assert verification[
            "requested_command_count"
        ] == 1

        assert verification[
            "executed_command_count"
        ] == 1

        assert (
            state["tasks"][364]["status"]
            == "COMPLETED"
        )

        assert (
            "3 passed"
            in (
                verification["results"][0]
                ["steps"][0]
                .get("stdout", "")
            )
        )

        final_text = (
            target.read_text(
                encoding="utf-8"
            )
            .replace("\r\n", "\n")
        )

        assert FIXED_BLOCK in final_text
        assert _git("status", "--short") == (
            "M src/calculator.py"
        )

    finally:
        target.write_bytes(
            baseline_bytes
        )

        subprocess.run(
            [
                "git",
                "-C",
                str(FIXTURE_ROOT),
                "restore",
                "--worktree",
                "--",
                TARGET_RELATIVE_PATH,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        shutil.rmtree(
            backup_root,
            ignore_errors=True,
        )

    restored_text = (
        target.read_text(
            encoding="utf-8"
        )
        .replace("\r\n", "\n")
    )

    assert BROKEN_BLOCK in restored_text
    assert FIXED_BLOCK not in restored_text
    assert _git("status", "--short") == ""
