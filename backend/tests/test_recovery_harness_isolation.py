from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import app.database as database
import app.missions.implementation_runner as implementation_runner
import app.missions.verification_runner as verification_runner


def test_database_and_project_are_isolated(
    isolated_arc_environment: dict[str, Any],
) -> None:
    isolated_database = Path(
        isolated_arc_environment[
            "isolated_database"
        ]
    )

    isolated_project = Path(
        isolated_arc_environment[
            "isolated_project"
        ]
    )

    production_database = Path(
        isolated_arc_environment[
            "production_database"
        ]
    )

    assert database.DATABASE_PATH == isolated_database

    assert (
        database.DATABASE_PATH
        != production_database
    )

    with database.get_connection() as connection:
        connection.execute(
            """
            UPDATE projects
            SET path = ?,
                name = ?
            WHERE id = 1
            """,
            (
                str(isolated_project),
                "Arc Recovery Harness",
            ),
        )

        connection.commit()

    direct_connection = sqlite3.connect(
        isolated_database
    )

    direct_connection.row_factory = sqlite3.Row

    try:
        project = direct_connection.execute(
            """
            SELECT id, name, path
            FROM projects
            WHERE id = 1
            """
        ).fetchone()
    finally:
        direct_connection.close()

    assert project is not None
    assert project["id"] == 1

    assert (
        project["name"]
        == "Arc Recovery Harness"
    )

    assert (
        Path(project["path"]).resolve()
        == isolated_project.resolve()
    )

    implementation_project = (
        implementation_runner._get_project(1)
    )

    verification_project = (
        verification_runner._get_project(1)
    )

    assert implementation_project is not None
    assert verification_project is not None

    assert (
        Path(
            implementation_project["path"]
        ).resolve()
        == isolated_project.resolve()
    )

    assert (
        Path(
            verification_project["path"]
        ).resolve()
        == isolated_project.resolve()
    )


def test_backup_root_is_isolated(
    isolated_arc_environment: dict[str, Any],
) -> None:
    isolated_backup_root = Path(
        isolated_arc_environment[
            "isolated_backup_root"
        ]
    )

    production_backup_root = Path(
        isolated_arc_environment[
            "production_backup_root"
        ]
    )

    assert (
        implementation_runner
        .IMPLEMENTATION_BACKUP_ROOT
        == isolated_backup_root
    )

    assert (
        implementation_runner
        .IMPLEMENTATION_BACKUP_ROOT
        != production_backup_root
    )

    marker = (
        implementation_runner
        .IMPLEMENTATION_BACKUP_ROOT
        / "isolation-marker.txt"
    )

    marker.write_text(
        "isolated",
        encoding="utf-8",
    )

    assert marker.is_file()

    assert not (
        production_backup_root
        / "isolation-marker.txt"
    ).exists()


def test_isolated_project_git_is_clean(
    isolated_arc_environment: dict[str, Any],
) -> None:
    import subprocess

    isolated_project = Path(
        isolated_arc_environment[
            "isolated_project"
        ]
    )

    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
        ],
        cwd=isolated_project,
        text=True,
        capture_output=True,
        check=True,
    )

    assert completed.stdout.strip() == ""
