from pathlib import Path
import subprocess

from app.missions.implementation_runner import (
    _restore_manifest_files,
    _sha256_bytes,
)


def _git(
    root: Path,
    *args: str,
) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def test_restore_only_current_step_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    backup = tmp_path / "backup"

    project.mkdir()
    backup.mkdir()

    _git(project, "init")
    _git(
        project,
        "config",
        "user.email",
        "test@example.com",
    )
    _git(
        project,
        "config",
        "user.name",
        "Arc Test",
    )

    source = project / "src.py"
    tests = project / "test_src.py"

    source.write_text(
        "def add():\n    return 1\n",
        encoding="utf-8",
    )
    tests.write_text(
        "def test_add():\n    assert True\n",
        encoding="utf-8",
    )

    _git(project, "add", ".")
    _git(project, "commit", "-m", "initial")

    backup_source = backup / "files" / "src.py"
    backup_tests = backup / "files" / "test_src.py"
    backup_source.parent.mkdir(parents=True)

    backup_source.write_bytes(source.read_bytes())
    backup_tests.write_bytes(tests.read_bytes())

    manifest = {
        "files": [
            {
                "path": "src.py",
                "backup_path": "files/src.py",
                "sha256": _sha256_bytes(
                    backup_source.read_bytes()
                ),
            },
            {
                "path": "test_src.py",
                "backup_path": "files/test_src.py",
                "sha256": _sha256_bytes(
                    backup_tests.read_bytes()
                ),
            },
        ],
    }

    source.write_text(
        "def multiply():\n    return 2\n",
        encoding="utf-8",
    )
    tests.write_text(
        "def test_multiply():\n"
        "    assert missing_name\n",
        encoding="utf-8",
    )

    result = _restore_manifest_files(
        project_root=project,
        run_root=backup,
        manifest=manifest,
        restore_paths={
            "test_src.py",
        },
        allowed_remaining_paths={
            "src.py",
        },
    )

    assert "multiply" in source.read_text(
        encoding="utf-8"
    )
    assert "test_add" in tests.read_text(
        encoding="utf-8"
    )
    assert result["restored_files"] == [
        "test_src.py"
    ]
    assert result[
        "allowed_remaining_changes"
    ] == [
        "src.py"
    ]
    assert result[
        "unexpected_remaining_changes"
    ] == []
    assert result["working_tree_clean"] is True
