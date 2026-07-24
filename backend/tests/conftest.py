from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import app.database as database
import app.missions.implementation_runner as implementation_runner


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def run_git(
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

    return completed.stdout.strip()


@pytest.fixture
def isolated_arc_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    production_database = (
        Path.home()
        / "Arc"
        / "data"
        / "arc.db"
    ).resolve()

    production_backup_root = (
        Path.home()
        / "Arc"
        / "data"
        / "implementation_backups"
    ).resolve()

    assert production_database.is_file()

    production_database_hash_before = (
        sha256_file(production_database)
    )

    production_backup_entries_before = []

    if production_backup_root.exists():
        production_backup_entries_before = sorted(
            path.relative_to(
                production_backup_root
            ).as_posix()
            for path in production_backup_root.rglob("*")
        )

    isolated_data_dir = (
        tmp_path
        / "arc-data"
    )

    isolated_data_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    isolated_database = (
        isolated_data_dir
        / "arc-test.db"
    )

    shutil.copy2(
        production_database,
        isolated_database,
    )

    isolated_backup_root = (
        isolated_data_dir
        / "implementation_backups"
    )

    isolated_backup_root.mkdir(
        parents=True,
        exist_ok=False,
    )

    isolated_project = (
        tmp_path
        / "isolated-project"
    )

    isolated_project.mkdir(
        parents=True,
        exist_ok=False,
    )

    run_git(
        isolated_project,
        "init",
        "-b",
        "main",
    )

    run_git(
        isolated_project,
        "config",
        "user.name",
        "Arc Test",
    )

    run_git(
        isolated_project,
        "config",
        "user.email",
        "arc-test@example.invalid",
    )

    sample_file = (
        isolated_project
        / "backend"
        / "app"
        / "api"
        / "auth.py"
    )

    sample_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    sample_file.write_text(
        "def current_user():\n"
        "    return {'status': 'before'}\n",
        encoding="utf-8",
    )

    run_git(
        isolated_project,
        "add",
        ".",
    )

    run_git(
        isolated_project,
        "commit",
        "-m",
        "test: initialize isolated project",
    )

    monkeypatch.setattr(
        database,
        "DATA_DIR",
        isolated_data_dir,
    )

    monkeypatch.setattr(
        database,
        "DATABASE_PATH",
        isolated_database,
    )

    monkeypatch.setattr(
        implementation_runner,
        "IMPLEMENTATION_BACKUP_ROOT",
        isolated_backup_root,
    )

    environment = {
        "production_database": (
            production_database
        ),
        "production_database_hash_before": (
            production_database_hash_before
        ),
        "production_backup_root": (
            production_backup_root
        ),
        "production_backup_entries_before": (
            production_backup_entries_before
        ),
        "isolated_data_dir": (
            isolated_data_dir
        ),
        "isolated_database": (
            isolated_database
        ),
        "isolated_backup_root": (
            isolated_backup_root
        ),
        "isolated_project": (
            isolated_project
        ),
    }

    yield environment

    production_database_hash_after = (
        sha256_file(production_database)
    )

    assert (
        production_database_hash_after
        == production_database_hash_before
    ), "本番arc.dbが変更されました"

    production_backup_entries_after = []

    if production_backup_root.exists():
        production_backup_entries_after = sorted(
            path.relative_to(
                production_backup_root
            ).as_posix()
            for path in production_backup_root.rglob("*")
        )

    assert (
        production_backup_entries_after
        == production_backup_entries_before
    ), "本番implementation_backupsが変更されました"
