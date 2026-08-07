from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from app.missions.implementation_runner import (
    create_mission_implementation_backup_safe,
)
from app.missions.models import (
    MissionPatchEdit,
    MissionPatchGenerateRequest,
)
from app.missions.patch_generator import (
    generate_mission_patch_safe,
)


MISSION_ID = 36
PROJECT_ID = 1

FIXTURE_ROOT = Path(
    r"C:\Users\closs\ArcRepairFixture"
)

TARGET_RELATIVE_PATH = "src/calculator.py"

NEW_FILE_RELATIVE_PATH = "src/new_module.py"

NEW_FILE_CONTENT = (
    "def hello() -> str:\n"
    '    return "hello"\n'
)

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
                "command": "python -m pytest -q",
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
    }


def _state() -> dict:
    return {
        "mission": {
            "id": MISSION_ID,
            "project_id": PROJECT_ID,
            "title": "Real Repair Patch Engine",
            "status": "RUNNING",
            "progress": 80,
            "next_action": None,
        },
        "tasks": {
            361: {
                "id": 361,
                "mission_id": MISSION_ID,
                "task_type": "PLANNING",
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
                                    "Repair broken multiply "
                                    "behavior"
                                ),
                            }
                        ],
                        "verification_commands": [
                            {
                                "name": "pytest",
                                "command": (
                                    "python -m pytest -q"
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
                "status": "COMPLETED",
                "result": None,
                "target_path": None,
            },
            363: {
                "id": 363,
                "mission_id": MISSION_ID,
                "task_type": "IMPLEMENTATION",
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
                "status": "PENDING",
                "result": None,
                "target_path": None,
            },
        },
    }



def _create_implementation_result() -> dict:
    result = _initial_implementation_result()

    result["selected_file_count"] = 1
    result["selected_files"] = [
        {
            "path": NEW_FILE_RELATIVE_PATH,
            "reason": "Create new module",
            "operation": "CREATE",
        }
    ]

    return result


def _create_state() -> dict:
    state = _state()

    state["tasks"][363]["result"] = json.dumps(
        _create_implementation_result()
    )

    state["tasks"][363]["target_path"] = (
        NEW_FILE_RELATIVE_PATH
    )

    return state
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

            if parameters:
                possible_mission_id = (
                    parameters[-1]
                )

                if isinstance(
                    possible_mission_id,
                    int,
                ):
                    assert (
                        possible_mission_id
                        == MISSION_ID
                    )

            return self

        raise AssertionError(
            "Unexpected SQL in fake connection: "
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


def test_real_fixture_backup_and_patch_check(
    tmp_path,
):
    assert FIXTURE_ROOT.exists()
    assert (
        _git("branch", "--show-current")
        == "arc/repair-e2e"
    )
    assert _git("status", "--short") == ""

    target = (
        FIXTURE_ROOT
        / TARGET_RELATIVE_PATH
    )

    original_bytes = target.read_bytes()

    normalized_original = (
        original_bytes
        .decode("utf-8")
        .replace("\r\n", "\n")
    )

    assert BROKEN_BLOCK in normalized_original
    assert FIXED_BLOCK not in normalized_original

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

    payload = MissionPatchGenerateRequest(
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
            "Use the real Backup, Patch "
            "Generator and Patch Check engines."
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
        ):
            backup = (
                create_mission_implementation_backup_safe(
                    MISSION_ID
                )
            )

            backup_result = backup[
                "implementation"
            ]

            assert (
                backup_result["mode"]
                == "BACKUP_READY"
            )

            assert (
                backup_result["files_modified"]
                == 0
            )

            manifest_path = Path(
                backup_result[
                    "backup"
                ]["manifest_path"]
            )

            assert manifest_path.exists()

            manifest = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )

            assert manifest["mission_id"] == (
                MISSION_ID
            )

            assert manifest["git"]["branch"] == (
                "arc/repair-e2e"
            )

            assert manifest["file_count"] == 1
            assert manifest["files"][0][
                "path"
            ] == TARGET_RELATIVE_PATH

            generated = (
                generate_mission_patch_safe(
                    mission_id=MISSION_ID,
                    payload=payload,
                )
            )

        implementation = generated[
            "implementation"
        ]

        patch_check = generated[
            "patch_check"
        ]

        generator = generated["generator"]

        assert implementation[
            "mode"
        ] == "PATCH_CHECKED"

        assert implementation[
            "files_modified"
        ] == 0

        assert implementation[
            "write_enabled"
        ] is False

        assert implementation["patch"][
            "applicable"
        ] is True

        assert implementation["patch"][
            "applied"
        ] is False

        assert implementation["patch"][
            "changed_files"
        ] == [
            TARGET_RELATIVE_PATH,
        ]

        assert patch_check[
            "changed_files"
        ] == [
            TARGET_RELATIVE_PATH,
        ]

        assert patch_check[
            "git_apply_check"
        ]

        assert patch_check[
            "applied"
        ] is False

        assert generator[
            "changed_files"
        ] == [
            TARGET_RELATIVE_PATH,
        ]

        assert (
            "-    return left + right"
            in generator["patch_text"]
        )

        assert (
            "+    return left * right"
            in generator["patch_text"]
        )

        assert Path(
            generator["result_path"]
        ).exists()

        assert Path(
            implementation[
                "patch"
            ]["path"]
        ).exists()

        # Patch Checkでは実ファイルを書き換えない。
        assert target.read_bytes() == original_bytes
        assert _git("status", "--short") == ""

    finally:
        # テスト途中で失敗してもFixtureを基準状態へ戻す。
        target.write_bytes(original_bytes)

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

    restored = (
        target.read_text(
            encoding="utf-8"
        )
        .replace("\r\n", "\n")
    )

    assert BROKEN_BLOCK in restored
    assert _git("status", "--short") == ""

def test_real_fixture_create_patch_generation(
    tmp_path,
):
    target = (
        FIXTURE_ROOT
        / NEW_FILE_RELATIVE_PATH
    )

    if target.exists():
        target.unlink()

    state = _create_state()

    project = {
        "id": PROJECT_ID,
        "name": "ArcRepairFixture",
        "path": str(FIXTURE_ROOT),
    }

    backup_root = (
        tmp_path
        / "implementation_backups"
    )

    payload = MissionPatchGenerateRequest(
        edits=[
            MissionPatchEdit(
                operation="APPEND",
                path=NEW_FILE_RELATIVE_PATH,
                text=NEW_FILE_CONTENT,
            )
        ],
        generated_by="create-repair-e2e",
        note="Test CREATE patch generation.",
    )

    def get_mission(_mission_id):
        assert _mission_id == MISSION_ID
        return _mission_snapshot(state)

    def get_project(_project_id):
        assert _project_id == PROJECT_ID
        return dict(project)

    def get_connection():
        return _FakeConnection(state)

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
        ):
            backup = (
                create_mission_implementation_backup_safe(
                    MISSION_ID
                )
            )

            backup_result = backup[
                "implementation"
            ]

            manifest_path = Path(
                backup_result["backup"]["manifest_path"]
            )

            manifest = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )

            assert manifest["files"][0]["operation"] == (
                "CREATE"
            )

            generated = (
                generate_mission_patch_safe(
                    mission_id=MISSION_ID,
                    payload=payload,
                )
            )

        generator = generated["generator"]
        patch_check = generated["patch_check"]

        assert generator["changed_files"] == [
            NEW_FILE_RELATIVE_PATH,
        ]

        assert "--- /dev/null" in (
            generator["patch_text"]
        )

        assert "+def hello() -> str:" in (
            generator["patch_text"]
        )
        assert '+    return "hello"' in (
            generator["patch_text"]
        )

        assert patch_check[
            "git_apply_check"
        ]

        assert patch_check[
            "applied"
        ] is False

        assert not target.exists()

    finally:
        if target.exists():
            target.unlink()

        shutil.rmtree(
            backup_root,
            ignore_errors=True,
        )
