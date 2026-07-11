import ast
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_connection
from app.projects.reader import EXCLUDED_NAMES


ALLOWED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".sql",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".css",
    ".scss",
    ".html",
    ".rs",
    ".sh",
}

MAX_FILE_SIZE_BYTES = 512 * 1024
MAX_INDEX_FILES = 5000
MAX_SEARCH_RESULTS = 100


LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".json": "json",
    ".sql": "sql",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".css": "css",
    ".scss": "scss",
    ".html": "html",
    ".rs": "rust",
    ".sh": "shell",
}


class IndexingError(Exception):
    pass


def _get_project(project_id: int):
    with get_connection() as connection:
        project = connection.execute(
            """
            SELECT id, name, path
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()

    if project is None:
        raise IndexingError("プロジェクトが見つかりません。")

    return project


def _is_inside_root(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _iter_source_files(root: Path):
    count = 0

    for path in root.rglob("*"):
        if count >= MAX_INDEX_FILES:
            break

        if any(part in EXCLUDED_NAMES for part in path.parts):
            continue

        if not path.is_file():
            continue

        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            continue

        if not _is_inside_root(root, resolved):
            continue

        try:
            size = resolved.stat().st_size
        except OSError:
            continue

        if size > MAX_FILE_SIZE_BYTES:
            continue

        count += 1
        yield resolved


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return ""


def _extract_python_symbols(content: str) -> list[dict]:
    symbols: list[dict] = []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return symbols

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append(
                {
                    "symbol_type": "class",
                    "name": node.name,
                    "line_number": node.lineno,
                    "metadata": {},
                }
            )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                {
                    "symbol_type": "function",
                    "name": node.name,
                    "line_number": node.lineno,
                    "metadata": {
                        "async": isinstance(node, ast.AsyncFunctionDef),
                    },
                }
            )

        elif isinstance(node, ast.Import):
            for alias in node.names:
                symbols.append(
                    {
                        "symbol_type": "import",
                        "name": alias.name,
                        "line_number": getattr(node, "lineno", None),
                        "metadata": {},
                    }
                )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""

            symbols.append(
                {
                    "symbol_type": "import",
                    "name": module,
                    "line_number": getattr(node, "lineno", None),
                    "metadata": {
                        "members": [alias.name for alias in node.names],
                    },
                }
            )

    return symbols


def _extract_web_symbols(content: str) -> list[dict]:
    symbols: list[dict] = []

    patterns = [
        (
            "class",
            re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)"),
        ),
        (
            "function",
            re.compile(
                r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
            ),
        ),
        (
            "function",
            re.compile(
                r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="
                r"\s*(?:async\s*)?\([^)]*\)\s*=>"
            ),
        ),
        (
            "import",
            re.compile(
                r"\bimport(?:[\s\S]*?\sfrom\s*)?[\"']([^\"']+)[\"']"
            ),
        ),
    ]

    for symbol_type, pattern in patterns:
        for match in pattern.finditer(content):
            line_number = content.count("\n", 0, match.start()) + 1

            symbols.append(
                {
                    "symbol_type": symbol_type,
                    "name": match.group(1),
                    "line_number": line_number,
                    "metadata": {},
                }
            )

    return symbols


def _extract_symbols(language: str, content: str) -> list[dict]:
    if language == "python":
        return _extract_python_symbols(content)

    if language in {
        "typescript",
        "typescript-react",
        "javascript",
        "javascript-react",
    }:
        return _extract_web_symbols(content)

    return []


def index_project(project_id: int) -> dict:
    project = _get_project(project_id)
    root = Path(project["path"]).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        raise IndexingError(
            "登録済みプロジェクトフォルダが存在しません。"
        )

    indexed_at = datetime.now(timezone.utc).isoformat()
    language_counts: Counter[str] = Counter()
    total_symbols = 0
    total_files = 0
    skipped_empty = 0

    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM code_symbols
            WHERE project_file_id IN (
                SELECT id
                FROM project_files
                WHERE project_id = ?
            )
            """,
            (project_id,),
        )

        connection.execute(
            """
            DELETE FROM project_files
            WHERE project_id = ?
            """,
            (project_id,),
        )

        for path in _iter_source_files(root):
            content = _read_text(path)

            if not content and path.stat().st_size > 0:
                skipped_empty += 1
                continue

            relative_path = path.relative_to(root).as_posix()
            language = LANGUAGE_BY_EXTENSION.get(
                path.suffix.lower(),
                "text",
            )
            size_bytes = path.stat().st_size
            line_count = content.count("\n") + (
                1 if content else 0
            )
            content_hash = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()

            cursor = connection.execute(
                """
                INSERT INTO project_files (
                    project_id,
                    relative_path,
                    language,
                    size_bytes,
                    line_count,
                    content_hash,
                    indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    relative_path,
                    language,
                    size_bytes,
                    line_count,
                    content_hash,
                    indexed_at,
                ),
            )

            project_file_id = cursor.lastrowid
            symbols = _extract_symbols(language, content)

            for symbol in symbols:
                connection.execute(
                    """
                    INSERT INTO code_symbols (
                        project_file_id,
                        symbol_type,
                        name,
                        line_number,
                        metadata
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        project_file_id,
                        symbol["symbol_type"],
                        symbol["name"],
                        symbol["line_number"],
                        json.dumps(
                            symbol["metadata"],
                            ensure_ascii=False,
                        ),
                    ),
                )

            language_counts[language] += 1
            total_symbols += len(symbols)
            total_files += 1

        connection.commit()

    return {
        "project_id": project_id,
        "project_name": project["name"],
        "indexed_files": total_files,
        "indexed_symbols": total_symbols,
        "skipped_files": skipped_empty,
        "languages": dict(
            sorted(
                language_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "indexed_at": indexed_at,
    }


def get_index_summary(project_id: int) -> dict:
    project = _get_project(project_id)

    with get_connection() as connection:
        file_summary = connection.execute(
            """
            SELECT
                COUNT(*) AS file_count,
                COALESCE(SUM(line_count), 0) AS total_lines,
                COALESCE(SUM(size_bytes), 0) AS total_bytes,
                MAX(indexed_at) AS last_indexed_at
            FROM project_files
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()

        symbol_summary = connection.execute(
            """
            SELECT COUNT(*) AS symbol_count
            FROM code_symbols
            WHERE project_file_id IN (
                SELECT id
                FROM project_files
                WHERE project_id = ?
            )
            """,
            (project_id,),
        ).fetchone()

        languages = connection.execute(
            """
            SELECT language, COUNT(*) AS count
            FROM project_files
            WHERE project_id = ?
            GROUP BY language
            ORDER BY count DESC, language ASC
            """,
            (project_id,),
        ).fetchall()

        symbol_types = connection.execute(
            """
            SELECT symbol_type, COUNT(*) AS count
            FROM code_symbols
            WHERE project_file_id IN (
                SELECT id
                FROM project_files
                WHERE project_id = ?
            )
            GROUP BY symbol_type
            ORDER BY count DESC, symbol_type ASC
            """,
            (project_id,),
        ).fetchall()

    return {
        "project_id": project_id,
        "project_name": project["name"],
        "file_count": file_summary["file_count"],
        "total_lines": file_summary["total_lines"],
        "total_bytes": file_summary["total_bytes"],
        "symbol_count": symbol_summary["symbol_count"],
        "last_indexed_at": file_summary["last_indexed_at"],
        "languages": {
            row["language"]: row["count"]
            for row in languages
        },
        "symbol_types": {
            row["symbol_type"]: row["count"]
            for row in symbol_types
        },
    }


def search_project(
    project_id: int,
    query: str,
    max_results: int = 30,
) -> dict:
    project = _get_project(project_id)
    root = Path(project["path"]).expanduser().resolve()

    normalized_query = query.strip().lower()

    if not normalized_query:
        raise IndexingError("検索語を入力してください。")

    results: list[dict] = []

    for path in _iter_source_files(root):
        if len(results) >= min(max_results, MAX_SEARCH_RESULTS):
            break

        relative_path = path.relative_to(root).as_posix()
        content = _read_text(path)

        path_match = normalized_query in relative_path.lower()

        for line_number, line in enumerate(
            content.splitlines(),
            start=1,
        ):
            if normalized_query not in line.lower():
                continue

            results.append(
                {
                    "path": relative_path,
                    "line_number": line_number,
                    "preview": line.strip()[:300],
                    "match_type": "content",
                }
            )

            if len(results) >= min(
                max_results,
                MAX_SEARCH_RESULTS,
            ):
                break

        if (
            path_match
            and not any(
                result["path"] == relative_path
                for result in results
            )
            and len(results) < min(
                max_results,
                MAX_SEARCH_RESULTS,
            )
        ):
            results.append(
                {
                    "path": relative_path,
                    "line_number": None,
                    "preview": relative_path,
                    "match_type": "path",
                }
            )

    return {
        "project_id": project_id,
        "project_name": project["name"],
        "query": query,
        "count": len(results),
        "results": results,
    }


def search_symbols(
    project_id: int,
    query: str,
    max_results: int = 50,
) -> dict:
    project = _get_project(project_id)
    normalized_query = query.strip()

    if not normalized_query:
        raise IndexingError("検索語を入力してください。")

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                pf.relative_path,
                cs.symbol_type,
                cs.name,
                cs.line_number,
                cs.metadata
            FROM code_symbols cs
            INNER JOIN project_files pf
                ON pf.id = cs.project_file_id
            WHERE
                pf.project_id = ?
                AND LOWER(cs.name) LIKE LOWER(?)
            ORDER BY
                cs.name ASC,
                pf.relative_path ASC
            LIMIT ?
            """,
            (
                project_id,
                f"%{normalized_query}%",
                min(max_results, MAX_SEARCH_RESULTS),
            ),
        ).fetchall()

    return {
        "project_id": project_id,
        "project_name": project["name"],
        "query": query,
        "count": len(rows),
        "results": [
            {
                "path": row["relative_path"],
                "symbol_type": row["symbol_type"],
                "name": row["name"],
                "line_number": row["line_number"],
                "metadata": json.loads(
                    row["metadata"] or "{}"
                ),
            }
            for row in rows
        ],
    }
