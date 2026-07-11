from __future__ import annotations

import ast
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from app.projects.reader import (
    EXCLUDED_NAMES,
    READABLE_EXTENSIONS,
)


class DependencyGraphError(Exception):
    """依存関係解析に失敗した場合の例外。"""


JS_IMPORT_PATTERN = re.compile(
    r"""
    (?:
        import\s+
        (?:
            [\s\S]*?
            \s+from\s+
        )?
        ["']([^"']+)["']
    )
    |
    (?:
        require\s*\(\s*
        ["']([^"']+)["']
        \s*\)
    )
    |
    (?:
        import\s*\(\s*
        ["']([^"']+)["']
        \s*\)
    )
    """,
    re.VERBOSE,
)

SUPPORTED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
}

RESOLUTION_EXTENSIONS = [
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
]

INDEX_FILES = [
    "index.ts",
    "index.tsx",
    "index.js",
    "index.jsx",
    "__init__.py",
]


def _is_inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _collect_source_files(
    root: Path,
    max_files: int,
) -> list[Path]:
    files: list[Path] = []

    for path in root.rglob("*"):
        if len(files) >= max_files:
            break

        if not path.is_file():
            continue

        if any(part in EXCLUDED_NAMES for part in path.parts):
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            continue

        if not _is_inside(root, resolved):
            continue

        files.append(resolved)

    return sorted(files)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, PermissionError) as error:
        raise DependencyGraphError(
            f"ファイルを読み取れません: {path}"
        ) from error


def _extract_python_imports(content: str) -> list[str]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                alias.name
                for alias in node.names
            )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            prefix = "." * node.level

            if module:
                imports.append(prefix + module)
            else:
                imports.extend(
                    prefix + alias.name
                    for alias in node.names
                )

    return imports


def _extract_js_imports(content: str) -> list[str]:
    imports: list[str] = []

    for match in JS_IMPORT_PATTERN.finditer(content):
        value = (
            match.group(1)
            or match.group(2)
            or match.group(3)
        )

        if value:
            imports.append(value)

    return imports


def _candidate_file_paths(base: Path) -> list[Path]:
    candidates: list[Path] = []

    if base.suffix:
        candidates.append(base)
    else:
        for extension in RESOLUTION_EXTENSIONS:
            candidates.append(
                base.with_suffix(extension)
            )

        for index_file in INDEX_FILES:
            candidates.append(base / index_file)

    return candidates


def _resolve_relative_import(
    *,
    root: Path,
    source: Path,
    import_value: str,
) -> Path | None:
    base = (source.parent / import_value).resolve()

    if not _is_inside(root, base):
        return None

    for candidate in _candidate_file_paths(base):
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    return None


def _resolve_alias_import(
    *,
    root: Path,
    import_value: str,
) -> Path | None:
    alias_prefixes = {
        "@/": root / "frontend/src",
        "src/": root / "frontend/src",
        "app/": root / "backend/app",
    }

    for prefix, base_root in alias_prefixes.items():
        if not import_value.startswith(prefix):
            continue

        relative = import_value[len(prefix):]
        base = (base_root / relative).resolve()

        if not _is_inside(root, base):
            return None

        for candidate in _candidate_file_paths(base):
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()

    return None


def _resolve_python_import(
    *,
    root: Path,
    source: Path,
    import_value: str,
) -> Path | None:
    if import_value.startswith("."):
        dot_count = len(import_value) - len(
            import_value.lstrip(".")
        )
        module = import_value.lstrip(".")

        base = source.parent

        for _ in range(max(dot_count - 1, 0)):
            base = base.parent

        if module:
            base = base / module.replace(".", "/")

        for candidate in _candidate_file_paths(base):
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()

        return None

    module_path = import_value.replace(".", "/")

    candidates = [
        root / "backend" / f"{module_path}.py",
        root / "backend" / module_path / "__init__.py",
        root / f"{module_path}.py",
        root / module_path / "__init__.py",
    ]

    for candidate in candidates:
        resolved = candidate.resolve()

        if (
            _is_inside(root, resolved)
            and resolved.exists()
            and resolved.is_file()
        ):
            return resolved

    return None


def _resolve_import(
    *,
    root: Path,
    source: Path,
    import_value: str,
) -> Path | None:
    if import_value.startswith("."):
        return _resolve_relative_import(
            root=root,
            source=source,
            import_value=import_value,
        )

    alias_result = _resolve_alias_import(
        root=root,
        import_value=import_value,
    )

    if alias_result:
        return alias_result

    if source.suffix.lower() == ".py":
        return _resolve_python_import(
            root=root,
            source=source,
            import_value=import_value,
        )

    return None


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _extract_imports(path: Path) -> list[str]:
    content = _read_text(path)

    if path.suffix.lower() == ".py":
        return _extract_python_imports(content)

    return _extract_js_imports(content)


def _build_edges(
    *,
    root: Path,
    files: list[Path],
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    list[dict[str, str]],
]:
    file_set = {
        path.resolve()
        for path in files
    }

    outbound: dict[str, set[str]] = defaultdict(set)
    inbound: dict[str, set[str]] = defaultdict(set)
    unresolved: list[dict[str, str]] = []

    for source in files:
        source_relative = _relative(root, source)

        for import_value in _extract_imports(source):
            target = _resolve_import(
                root=root,
                source=source,
                import_value=import_value,
            )

            if target is None or target not in file_set:
                if import_value.startswith(
                    (".", "@/", "src/", "app/")
                ):
                    unresolved.append(
                        {
                            "source": source_relative,
                            "import": import_value,
                        }
                    )
                continue

            target_relative = _relative(root, target)

            if target_relative == source_relative:
                continue

            outbound[source_relative].add(target_relative)
            inbound[target_relative].add(source_relative)

    outbound_result = {
        key: sorted(values)
        for key, values in outbound.items()
    }

    inbound_result = {
        key: sorted(values)
        for key, values in inbound.items()
    }

    return (
        outbound_result,
        inbound_result,
        unresolved,
    )


def _transitive_impact(
    *,
    target: str,
    inbound: dict[str, list[str]],
    max_depth: int,
) -> list[dict[str, Any]]:
    queue: deque[tuple[str, int]] = deque(
        [(target, 0)]
    )
    visited = {target}
    affected: list[dict[str, Any]] = []

    while queue:
        current, depth = queue.popleft()

        if depth >= max_depth:
            continue

        for parent in inbound.get(current, []):
            if parent in visited:
                continue

            visited.add(parent)
            next_depth = depth + 1

            affected.append(
                {
                    "path": parent,
                    "depth": next_depth,
                }
            )

            queue.append((parent, next_depth))

    return sorted(
        affected,
        key=lambda item: (
            item["depth"],
            item["path"],
        ),
    )


def analyze_project_dependencies(
    *,
    project_path: str,
    target_path: str | None = None,
    max_files: int = 3000,
    max_impact_depth: int = 5,
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        raise DependencyGraphError(
            "登録済みプロジェクトが存在しません。"
        )

    files = _collect_source_files(
        root=root,
        max_files=max_files,
    )

    outbound, inbound, unresolved = _build_edges(
        root=root,
        files=files,
    )

    nodes = sorted(
        _relative(root, path)
        for path in files
    )

    edge_count = sum(
        len(values)
        for values in outbound.values()
    )

    result: dict[str, Any] = {
        "summary": {
            "file_count": len(nodes),
            "edge_count": edge_count,
            "files_with_dependencies": len(outbound),
            "files_with_dependents": len(inbound),
            "unresolved_internal_imports": len(unresolved),
        },
        "nodes": nodes,
        "outbound": outbound,
        "inbound": inbound,
        "unresolved": unresolved[:500],
        "truncated": len(files) >= max_files,
        "analysis_engine": "arc-dependency-graph-v0.1",
    }

    if target_path:
        normalized = target_path.strip().lstrip("/")

        if normalized not in nodes:
            raise DependencyGraphError(
                "指定ファイルは依存関係解析対象に存在しません。"
            )

        direct_dependencies = outbound.get(
            normalized,
            [],
        )

        direct_dependents = inbound.get(
            normalized,
            [],
        )

        affected = _transitive_impact(
            target=normalized,
            inbound=inbound,
            max_depth=max_impact_depth,
        )

        risk_level = "low"

        if len(affected) >= 20:
            risk_level = "high"
        elif len(affected) >= 5:
            risk_level = "medium"

        result["target"] = {
            "path": normalized,
            "direct_dependencies": direct_dependencies,
            "direct_dependents": direct_dependents,
            "affected_files": affected,
            "affected_count": len(affected),
            "risk_level": risk_level,
        }

    return result
