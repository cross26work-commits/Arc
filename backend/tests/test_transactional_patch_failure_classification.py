from pathlib import Path
from unittest.mock import patch

import pytest

from app.missions.implementation_runner import (
    MissionImplementationError,
    _apply_patch_transactional,
)


def _manifest():
    return {
        "files": [
            {
                "path": "sample.py",
                "sha256": "before-hash",
            },
        ],
    }


def test_transactional_apply_preserves_patch_classification(
    tmp_path,
):
    project_root = tmp_path / "project"
    run_root = tmp_path / "backup"
    patch_path = run_root / "proposed.patch"

    project_root.mkdir()
    run_root.mkdir()

    target = project_root / "sample.py"
    target.write_text(
        "before\n",
        encoding="utf-8",
    )

    patch_path.write_text(
        "dummy patch\n",
        encoding="utf-8",
    )

    with (
        patch(
            "app.missions.implementation_runner."
            "_git_changed_paths",
            return_value=[],
        ),
        patch(
            "app.missions.implementation_runner."
            "_verify_project_against_manifest",
            return_value=[],
        ),
        patch(
            "app.missions.implementation_runner."
            "_sha256_bytes",
            return_value="patch-hash",
        ),
        patch(
            "app.missions.implementation_runner."
            "_run_git_apply_check",
        ),
        patch(
            "app.missions.implementation_runner."
            "subprocess.run",
            return_value=type(
                "Result",
                (),
                {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": (
                        "error: patch does not apply"
                    ),
                },
            )(),
        ),
        patch(
            "app.missions.implementation_runner."
            "_restore_manifest_files",
            return_value={
                "working_tree_clean": True,
                "remaining_changes": [],
            },
        ),
    ):
        with pytest.raises(
            MissionImplementationError
        ) as caught:
            _apply_patch_transactional(
                project_root=project_root,
                run_root=run_root,
                manifest=_manifest(),
                patch_path=patch_path,
                expected_patch_sha256=(
                    "patch-hash"
                ),
                expected_changed_paths=[
                    "sample.py",
                ],
            )

    assert caught.value.failure_category == (
        "PATCH"
    )

    assert caught.value.failure_classification[
        "classification_source"
    ] == "IMPLEMENTATION_PATCH_APPLY"


def test_transactional_apply_marks_incomplete_rollback_as_git(
    tmp_path,
):
    project_root = tmp_path / "project"
    run_root = tmp_path / "backup"
    patch_path = run_root / "proposed.patch"

    project_root.mkdir()
    run_root.mkdir()

    target = project_root / "sample.py"
    target.write_text(
        "before\n",
        encoding="utf-8",
    )

    patch_path.write_text(
        "dummy patch\n",
        encoding="utf-8",
    )

    with (
        patch(
            "app.missions.implementation_runner."
            "_git_changed_paths",
            return_value=[],
        ),
        patch(
            "app.missions.implementation_runner."
            "_verify_project_against_manifest",
            return_value=[],
        ),
        patch(
            "app.missions.implementation_runner."
            "_sha256_bytes",
            return_value="patch-hash",
        ),
        patch(
            "app.missions.implementation_runner."
            "_run_git_apply_check",
        ),
        patch(
            "app.missions.implementation_runner."
            "subprocess.run",
            return_value=type(
                "Result",
                (),
                {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": (
                        "error: patch does not apply"
                    ),
                },
            )(),
        ),
        patch(
            "app.missions.implementation_runner."
            "_restore_manifest_files",
            return_value={
                "working_tree_clean": False,
                "remaining_changes": [
                    "sample.py",
                ],
            },
        ),
    ):
        with pytest.raises(
            MissionImplementationError
        ) as caught:
            _apply_patch_transactional(
                project_root=project_root,
                run_root=run_root,
                manifest=_manifest(),
                patch_path=patch_path,
                expected_patch_sha256=(
                    "patch-hash"
                ),
                expected_changed_paths=[
                    "sample.py",
                ],
            )

    assert caught.value.failure_category == "GIT"

    assert caught.value.failure_classification[
        "reason_code"
    ] == "PATCH_ROLLBACK_INCOMPLETE"

    assert caught.value.failure_classification[
        "classification_source"
    ] == "IMPLEMENTATION_PATCH_ROLLBACK"
