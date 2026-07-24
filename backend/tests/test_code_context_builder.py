from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.code_context import builder
from app.main import app


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _isolated_connection(
    database_path: Path,
) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        "PRAGMA foreign_keys = ON"
    )
    return connection


def _prepare_database(
    database_path: Path,
    project_path: Path,
) -> None:
    with _isolated_connection(
        database_path
    ) as connection:
        connection.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL
            );

            CREATE TABLE missions (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL,
                success_criteria TEXT NOT NULL,
                next_action TEXT NOT NULL
            );

            CREATE TABLE mission_tasks (
                id INTEGER PRIMARY KEY,
                mission_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                target_path TEXT,
                result TEXT
            );

            CREATE TABLE mission_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mission_id INTEGER NOT NULL,
                level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        connection.execute(
            """
            INSERT INTO projects (
                id,
                name,
                path
            )
            VALUES (?, ?, ?)
            """,
            (
                1,
                "Isolated Project",
                str(project_path),
            ),
        )

        connection.execute(
            """
            INSERT INTO missions (
                id,
                project_id,
                title,
                objective,
                status,
                progress,
                success_criteria,
                next_action
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                "Context Test",
                "sample.pyへ関数を追加する",
                "PLANNED",
                43,
                "Contextを生成できる",
                "Context生成",
            ),
        )

        analysis_result = {
            "analysis_version": (
                "mission-analysis-v0.3"
            ),
            "search_terms": ["sample"],
            "candidate_count": 1,
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "api_files": [],
            "frontend_files": [],
            "backend_files": ["sample.py"],
            "candidates": [
                {
                    "path": "sample.py",
                    "score": 10,
                    "reasons": [
                        "検索語「sample」に一致"
                    ],
                }
            ],
        }

        connection.execute(
            """
            INSERT INTO mission_tasks (
                id,
                mission_id,
                position,
                title,
                description,
                task_type,
                status,
                target_path,
                result
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                2,
                "分析",
                "関連コードを分析する",
                "ANALYSIS",
                "COMPLETED",
                "sample.py",
                json.dumps(
                    analysis_result,
                    ensure_ascii=False,
                ),
            ),
        )

        connection.commit()


@pytest.fixture
def isolated_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project_path = tmp_path / "project"
    project_path.mkdir()

    source = project_path / "sample.py"
    source.write_text(
        (
            "def existing_function() -> str:\n"
            "    return 'ok'\n"
        ),
        encoding="utf-8",
    )

    database_path = tmp_path / "arc-test.db"
    context_root = tmp_path / "contexts"

    _prepare_database(
        database_path,
        project_path,
    )

    def get_test_connection():
        return _isolated_connection(
            database_path
        )

    monkeypatch.setattr(
        builder,
        "get_connection",
        get_test_connection,
    )
    monkeypatch.setattr(
        builder,
        "CONTEXT_ROOT",
        context_root,
    )

    return {
        "database_path": database_path,
        "project_path": project_path,
        "context_root": context_root,
    }


def test_build_code_context_is_read_only(
    isolated_context,
):
    source = (
        isolated_context["project_path"]
        / "sample.py"
    )

    original = source.read_bytes()

    result = builder.build_code_context(1)

    assert (
        result["context_version"]
        == "mission-code-context-v0.1"
    )
    assert result["mission_id"] == 1
    assert result["summary"][
        "candidate_file_count"
    ] == 1
    assert result["summary"][
        "included_file_count"
    ] == 1
    assert result["files"][0][
        "relative_path"
    ] == "sample.py"
    assert result["files"][0]["source"][
        "included"
    ] is True
    assert result["safety"]["read_only"] is True
    assert (
        result["safety"]["files_modified"]
        is False
    )
    assert len(result["context_sha256"]) == 64
    assert source.read_bytes() == original


def test_get_saved_code_context(
    isolated_context,
):
    created = builder.build_code_context(1)
    loaded = builder.get_code_context(1)

    assert (
        loaded["context_sha256"]
        == created["context_sha256"]
    )
    assert loaded["storage"]["exists"] is True


def test_context_requires_completed_analysis(
    isolated_context,
):
    with builder.get_connection() as connection:
        connection.execute(
            """
            UPDATE mission_tasks
            SET status = 'RUNNING'
            WHERE id = 1
            """
        )
        connection.commit()

    with pytest.raises(
        builder.CodeContextError,
        match="ANALYSIS Taskの完了",
    ):
        builder.build_code_context(1)


def test_context_routes_registered():
    openapi = app.openapi()
    paths = openapi["paths"]

    assert (
        "/missions/{mission_id}/context"
        in paths
    )

    methods = paths[
        "/missions/{mission_id}/context"
    ]

    assert "get" in methods
    assert "post" in methods
