import sqlite3
from pathlib import Path


ARC_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ARC_ROOT / "data"
DATABASE_PATH = DATA_DIR / "arc.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                project_type TEXT NOT NULL DEFAULT 'software',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                relative_path TEXT NOT NULL,
                language TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                line_count INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                indexed_at TEXT NOT NULL,

                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE CASCADE,

                UNIQUE(project_id, relative_path)
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS code_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_file_id INTEGER NOT NULL,
                symbol_type TEXT NOT NULL,
                name TEXT NOT NULL,
                line_number INTEGER,
                metadata TEXT,

                FOREIGN KEY (project_file_id)
                    REFERENCES project_files(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_project_files_project_id
            ON project_files(project_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_code_symbols_file_id
            ON code_symbols(project_file_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_code_symbols_name
            ON code_symbols(name)
            """
        )

        connection.commit()
