from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from app.missions.repair_patch_apply import (
    apply_repair_patch,
)
from app.missions.repair_verification_runner import (
    run_repair_verification,
)


MISSION_ID = 36

FIXTURE_ROOT = Path(
    r"C:\Users\closs\ArcRepairFixture"
)

TARGET_PATH = (
    FIXTURE_ROOT
    / "src"
    / "calculator.py"
)

BROKEN_TEXT = (
    "def multiply(left: int, right: int) -> int:\n"
    '    """Return the product of two integers."""\n'
    "    return left + right"
)

FIXED_TEXT = (
    "def multiply(left: int, right: int) -> int:\n"
    '    """Return the product of two integers."""\n'
    "    return left * right"
)

PATCH_SHA256 = "a" * 64


def _apply_mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "ArcRepairFixture",
        "project_path": str(FIXTURE_ROOT),
        "title": "Real fixture repair apply",
        "status": "RUNNING",
        "progress": 80,
        "tasks": [
            {
                "task_type": "APPROVAL",
                "status": "COMPLETED",
            },
            {
                "task_type": "IMPLEMENTATION",
                "status": "RUNNING",
            },
            {
                "task_type": "VERIFICATION",
                "status": "FAILED",
            },
        ],
    }


def _verification_mission():
    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "ArcRepairFixture",
        "project_path": str(FIXTURE_ROOT),
        "title": "Real fixture repair verification",
        "status": "VERIFYING",
        "progress": 90,
        "tasks": [
            {
                "task_type": "IMPLEMENTATION",
                "status": "COMPLETED",
            },
            {
                "task_type": "VERIFICATION",
                "status": "PENDING",
            },
        ],
    }


def _checked_request():
    return {
        "mission_id": MISSION_ID,
        "request_id": "real-fixture-apply-1",
        "repair_plan_id": "real-fixture-plan-1",
        "status": "PATCH_CHECKED",
        "failure_source": "VERIFICATION",
        "failure_category": "TEST",
        "patch_generated": True,
        "patch_checked": True,
        "patch_applied": False,
        "auto_apply": False,
        "patch_result": {
            "patch_applicable": True,
            "implementation_mode": (
                "PATCH_CHECKED"
            ),
            "patch_sha256": PATCH_SHA256,
            "changed_file_count": 1,
            "changed_files": [
                "src/calculator.py",
            ],
            "operation_count": 1,
        },
    }


def _run_fixture_pytest() -> subprocess.CompletedProcess[str]:
    python_executable = Path(
        r"C:\Users\closs\Arc"
        r"\backend\venv\Scripts\python.exe"
    )

    return subprocess.run(
        [
            str(python_executable),
            "-m",
            "pytest",
            "-q",
        ],
        cwd=FIXTURE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_fixture_patch_apply_then_verification_passes(
    tmp_path,
):
    assert TARGET_PATH.exists()

    original_bytes = TARGET_PATH.read_bytes()

    original_content = original_bytes.decode(
        "utf-8"
    )

    normalized_original_content = (
        original_content.replace(
            "\r\n",
            "\n",
        )
    )

    assert (
        BROKEN_TEXT
        in normalized_original_content
    )

    assert (
        FIXED_TEXT
        not in normalized_original_content
    )

    state = {
        "request": _checked_request(),
    }

    mission_dir = (
        tmp_path
        / f"mission-{MISSION_ID}"
    )
    mission_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    def load_request(_mission_id):
        return dict(state["request"])

    def write_request(path, payload):
        path = Path(path)

        if path.name == "repair-request.json":
            state["request"] = dict(payload)

    def apply_real_fixture_patch(
        *,
        mission_id,
        payload,
    ):
        assert mission_id == MISSION_ID
        assert payload.confirmation == "APPLY_PATCH"
        assert (
            payload.expected_patch_sha256
            == PATCH_SHA256
        )

        current = TARGET_PATH.read_text(
            encoding="utf-8"
        )

        normalized = current.replace(
            "\r\n",
            "\n",
        )

        assert normalized.count(
            BROKEN_TEXT
        ) == 1

        fixed = normalized.replace(
            BROKEN_TEXT,
            FIXED_TEXT,
            1,
        )

        TARGET_PATH.write_text(
            fixed,
            encoding="utf-8",
            newline="\n",
        )

        return {
            "mission": _apply_mission(),
            "patch_apply": {
                "patch_apply_version": (
                    "real-fixture-apply-v0.1"
                ),
                "applied": True,
                "rolled_back": False,
                "patch_sha256": PATCH_SHA256,
                "changed_file_count": 1,
                "changed_files": [
                    "src/calculator.py",
                ],
                "working_tree_clean": False,
                "applied_at": (
                    "2026-08-07T00:00:00+00:00"
                ),
            },
            "implementation": {
                "mode": "PATCH_APPLIED",
            },
        }

    def run_real_fixture_verification(
        mission_id,
    ):
        assert mission_id == MISSION_ID

        completed = _run_fixture_pytest()

        passed = (
            completed.returncode == 0
        )

        return {
            "mission": _verification_mission(),
            "verification": {
                "verification_version": (
                    "real-fixture-verification-v0.1"
                ),
                "passed": passed,
                "failure_category": (
                    None
                    if passed
                    else "TEST"
                ),
                "requested_command_count": 1,
                "executed_command_count": 1,
                "results": [
                    {
                        "name": "pytest",
                        "category": "TEST",
                        "failure_category": (
                            None
                            if passed
                            else "TEST"
                        ),
                        "command": (
                            "python -m pytest -q"
                        ),
                        "passed": passed,
                        "returncode": (
                            completed.returncode
                        ),
                        "timed_out": False,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    }
                ],
            },
            "rollback": None,
            "implementation": {
                "mode": "PATCH_APPLIED",
            },
        }

    def save_verified_request(
        *,
        mission_id,
        request_id,
        suffix,
        repair_request,
    ):
        assert mission_id == MISSION_ID
        assert request_id == (
            "real-fixture-apply-1"
        )
        assert suffix == "verified"

        state["request"] = dict(
            repair_request
        )

        latest_path = (
            mission_dir
            / "repair-request.json"
        )

        archive_path = (
            mission_dir
            / "patch-request-"
            "real-fixture-apply-1-verified.json"
        )

        return {
            "latest_path": str(latest_path),
            "archive_path": str(
                archive_path
            ),
        }

    try:
        with (
            patch(
                "app.missions.repair_patch_apply."
                "get_mission",
                return_value=_apply_mission(),
            ),
            patch(
                "app.missions.repair_patch_apply."
                "_load_existing_request",
                side_effect=load_request,
            ),
            patch(
                "app.missions.repair_patch_apply."
                "apply_mission_implementation_patch_safe",
                side_effect=apply_real_fixture_patch,
            ) as apply_mock,
            patch(
                "app.missions.repair_patch_apply."
                "_latest_request_path",
                return_value=(
                    mission_dir
                    / "repair-request.json"
                ),
            ),
            patch(
                "app.missions.repair_patch_apply."
                "REPAIR_PLAN_ROOT",
                tmp_path,
            ),
            patch(
                "app.missions.repair_patch_apply."
                "_write_json_atomic",
                side_effect=write_request,
            ),
            patch(
                "app.missions.repair_patch_apply."
                "add_mission_log",
            ) as apply_log_mock,
        ):
            applied = apply_repair_patch(
                mission_id=MISSION_ID,
                decided_by="arc-real-fixture-test",
                note=(
                    "Apply deterministic "
                    "multiply repair."
                ),
            )

        applied_request = applied[
            "repair_request"
        ]

        assert applied_request[
            "status"
        ] == "PATCH_APPLIED"

        assert applied_request[
            "patch_applied"
        ] is True

        assert applied_request[
            "auto_apply"
        ] is False

        assert applied_request[
            "apply_result"
        ]["rolled_back"] is False

        assert applied_request[
            "apply_result"
        ]["implementation_mode"] == (
            "PATCH_APPLIED"
        )

        fixed_content = (
            TARGET_PATH.read_text(
                encoding="utf-8"
            )
        )

        assert FIXED_TEXT in fixed_content
        assert BROKEN_TEXT not in fixed_content

        apply_mock.assert_called_once()

        apply_event_types = [
            call.kwargs.get(
                "event_type"
            )
            for call in (
                apply_log_mock
                .call_args_list
            )
        ]

        assert (
            "MISSION_REPAIR_PATCH_APPLIED"
            in apply_event_types
        )

        with (
            patch(
                "app.missions.repair_verification_runner."
                "get_mission",
                return_value=(
                    _verification_mission()
                ),
            ),
            patch(
                "app.missions.repair_verification_runner."
                "_load_existing_request",
                side_effect=load_request,
            ),
            patch(
                "app.missions.repair_verification_runner."
                "run_mission_verification_safe",
                side_effect=(
                    run_real_fixture_verification
                ),
            ) as verification_mock,
            patch(
                "app.missions.repair_verification_runner."
                "_save_updated_request",
                side_effect=(
                    save_verified_request
                ),
            ),
            patch(
                "app.missions.repair_verification_runner."
                "add_mission_log",
            ) as verification_log_mock,
        ):
            verified = (
                run_repair_verification(
                    mission_id=MISSION_ID
                )
            )

        verified_request = verified[
            "repair_request"
        ]

        assert verified_request[
            "status"
        ] == "REPAIR_VERIFIED"

        assert verified_request[
            "repair_verification_passed"
        ] is True

        assert verified_request[
            "patch_applied"
        ] is True

        assert verified_request[
            "auto_apply"
        ] is False

        assert verified_request[
            "verification_result"
        ]["passed"] is True

        assert verified_request[
            "verification_result"
        ]["executed_command_count"] == 1

        assert verified_request[
            "verification_result"
        ]["failed_results"] == []

        verification_mock.assert_called_once()

        verification_event_types = [
            call.kwargs.get(
                "event_type"
            )
            for call in (
                verification_log_mock
                .call_args_list
            )
        ]

        assert any(
            event in verification_event_types
            for event in (
                "MISSION_REPAIR_VERIFICATION_COMPLETED",
                "MISSION_REPAIR_VERIFICATION_PASSED",
                "MISSION_REPAIR_VERIFIED",
            )
        )

        completed = _run_fixture_pytest()

        assert completed.returncode == 0, (
            completed.stdout
            + "\n"
            + completed.stderr
        )

        assert (
            "3 passed"
            in completed.stdout
        )

    finally:
        # 他テストのために故障状態へ戻す。
        TARGET_PATH.write_bytes(
            original_bytes
        )

    restored_content = (
        TARGET_PATH.read_text(
            encoding="utf-8"
        )
    )

    assert BROKEN_TEXT in restored_content
