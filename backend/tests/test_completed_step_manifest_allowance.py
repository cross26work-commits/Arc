from pathlib import Path

import pytest

from app.missions.implementation_runner import (
    MissionImplementationError,
    _verified_completed_step_paths,
    _verify_project_against_manifest,
)


def test_verified_completed_step_paths_collects_only_verified() -> None:
    implementation = {
        "step_execution": {
            "completed_step_ids": [
                "step-1",
                "step-2",
                "step-3",
            ],
            "results": {
                "step-1": {
                    "status": "COMPLETED",
                    "verification_passed": True,
                    "changed_files": [
                        "src/calculator.py",
                    ],
                },
                "step-2": {
                    "status": "COMPLETED",
                    "verification_passed": False,
                    "changed_files": [
                        "tests/test_calculator.py",
                    ],
                },
                "step-3": {
                    "status": "FAILED",
                    "verification_passed": True,
                    "changed_files": [
                        "README.md",
                    ],
                },
            },
        },
    }

    assert _verified_completed_step_paths(
        implementation
    ) == {
        "src/calculator.py",
    }


def test_manifest_allows_verified_completed_step_change(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src" / "calculator.py"
    target.parent.mkdir(parents=True)

    target.write_text(
        "def multiply(left, right):\n"
        "    return left * right\n",
        encoding="utf-8",
    )

    manifest = {
        "files": [
            {
                "path": "src/calculator.py",
                "sha256": "0" * 64,
            },
        ],
    }

    result = _verify_project_against_manifest(
        project_root=tmp_path,
        manifest=manifest,
        allowed_changed_paths={
            "src/calculator.py",
        },
    )

    assert result == [
        {
            "path": "src/calculator.py",
            "sha256": result[0]["sha256"],
            "matched": False,
            "completed_step_change": True,
        }
    ]


def test_manifest_rejects_unapproved_change(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src" / "calculator.py"
    target.parent.mkdir(parents=True)

    target.write_text(
        "changed\n",
        encoding="utf-8",
    )

    manifest = {
        "files": [
            {
                "path": "src/calculator.py",
                "sha256": "0" * 64,
            },
        ],
    }

    with pytest.raises(
        MissionImplementationError,
        match="Backup作成後に対象ファイルが変更されています",
    ):
        _verify_project_against_manifest(
            project_root=tmp_path,
            manifest=manifest,
        )
