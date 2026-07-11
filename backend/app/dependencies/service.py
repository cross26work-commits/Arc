from __future__ import annotations

import ast
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


class DependencyGraphError(Exception):
    """依存関係解析に失敗した場合の例外。"""


SOURCE_ROOT_NAMES = (
    "backend",
    "frontend",
)

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".idea",
    ".vscode",
    ".next",
    ".turbo",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "coverage",
    "target",
    "backups",
    "backup",
    "logs",
}

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


def _is_inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _is_excluded(path: Path) -> bool:
    return any(
        part in EXCLUDED_DIRECTORY_NAMES
        for part in path.parts
    )


def _collect_source_files(
    root: Path,
    max_files: int,
) -> list[Path]:
    files: list[Path] = []

    source_roots = [
        root / name
        for name in SOURCE_ROOT_NAMES
        if (root / name).exists()
        and (root / name).is_dir()
    ]

    if not source_roots:
        raise DependencyGraphError(
            "backendまたはfrontendフォルダが見つかりません。"
        )

    for source_root in source_roots:
        for path in source_root.rglob("*"):
            if len(files) >= max_files:
                return sorted(files)

            if not path.is_file():
                continue

            if _is_excluded(path):
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

    return (
        {
            key: sorted(values)
            for key, values in outbound.items()
        },
        {
            key: sorted(values)
            for key, values in inbound.items()
        },
        unresolved,
    )


def _build_tree(
    *,
    root_path: str,
    edges: dict[str, list[str]],
    max_depth: int,
    max_nodes: int,
) -> dict[str, Any]:
    node_counter = 0

    def walk(
        current_path: str,
        depth: int,
        ancestors: set[str],
    ) -> dict[str, Any]:
        nonlocal node_counter

        node_counter += 1

        node: dict[str, Any] = {
            "path": current_path,
            "name": Path(current_path).name,
            "depth": depth,
            "children": [],
            "cycle": False,
            "truncated": False,
        }

        if current_path in ancestors:
            node["cycle"] = True
            return node

        if depth >= max_depth:
            if edges.get(current_path):
                node["truncated"] = True
            return node

        if node_counter >= max_nodes:
            node["truncated"] = True
            return node

        next_ancestors = {
            *ancestors,
            current_path,
        }

        for child_path in edges.get(current_path, []):
            if node_counter >= max_nodes:
                node["truncated"] = True
                break

            node["children"].append(
                walk(
                    current_path=child_path,
                    depth=depth + 1,
                    ancestors=next_ancestors,
                )
            )

        return node

    tree = walk(
        current_path=root_path,
        depth=0,
        ancestors=set(),
    )

    return {
        "tree": tree,
        "node_count": node_counter,
        "max_depth": max_depth,
        "max_nodes": max_nodes,
    }


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


def _calculate_risk(
    *,
    direct_dependents: int,
    affected_count: int,
) -> dict[str, Any]:
    indirect_affected = max(
        affected_count - direct_dependents,
        0,
    )

    score = (
        direct_dependents * 10
        + indirect_affected * 4
    )

    score = min(score, 100)

    if score >= 75:
        level = "high"
        label = "高"
    elif score >= 35:
        level = "medium"
        label = "中"
    else:
        level = "low"
        label = "低"

    return {
        "level": level,
        "label": label,
        "score": score,
        "direct_dependent_count": direct_dependents,
        "indirect_affected_count": indirect_affected,
        "reason": (
            f"直接利用元{direct_dependents}件、"
            f"間接影響候補{indirect_affected}件"
        ),
    }


def analyze_project_dependencies(
    *,
    project_path: str,
    target_path: str | None = None,
    max_files: int = 3000,
    max_impact_depth: int = 5,
    include_graph: bool = False,
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
        "unresolved": unresolved[:200],
        "truncated": len(files) >= max_files,
        "analysis_engine": "arc-dependency-graph-v1.1",
    }

    if include_graph:
        result["nodes"] = nodes
        result["outbound"] = outbound
        result["inbound"] = inbound

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

        risk = _calculate_risk(
            direct_dependents=len(direct_dependents),
            affected_count=len(affected),
        )

        result["target"] = {
            "path": normalized,
            "direct_dependencies": direct_dependencies,
            "direct_dependents": direct_dependents,
            "affected_files": affected,
            "affected_count": len(affected),
            "indirect_affected_count": max(
                len(affected) - len(direct_dependents),
                0,
            ),
            "risk": risk,
        }

    return result


def analyze_dependency_tree(
    *,
    project_path: str,
    target_path: str,
    direction: str = "both",
    max_files: int = 3000,
    max_depth: int = 5,
    max_nodes: int = 300,
) -> dict[str, Any]:
    if direction not in {
        "dependencies",
        "dependents",
        "both",
    }:
        raise DependencyGraphError(
            "directionはdependencies、dependents、bothのいずれかです。"
        )

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

    nodes = {
        _relative(root, path)
        for path in files
    }

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
        max_depth=max_depth,
    )

    risk = _calculate_risk(
        direct_dependents=len(direct_dependents),
        affected_count=len(affected),
    )

    result: dict[str, Any] = {
        "target": normalized,
        "direction": direction,
        "summary": {
            "file_count": len(nodes),
            "edge_count": sum(
                len(values)
                for values in outbound.values()
            ),
            "direct_dependency_count": len(
                direct_dependencies
            ),
            "direct_dependent_count": len(
                direct_dependents
            ),
            "affected_count": len(affected),
            "indirect_affected_count": max(
                len(affected) - len(direct_dependents),
                0,
            ),
            "unresolved_internal_imports": len(
                unresolved
            ),
        },
        "direct_dependencies": direct_dependencies,
        "direct_dependents": direct_dependents,
        "affected_files": affected,
        "risk": risk,
        "analysis_engine": "arc-dependency-tree-v1.1",
    }

    if direction in {
        "dependencies",
        "both",
    }:
        result["dependency_tree"] = _build_tree(
            root_path=normalized,
            edges=outbound,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )

    if direction in {
        "dependents",
        "both",
    }:
        result["dependent_tree"] = _build_tree(
            root_path=normalized,
            edges=inbound,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )

    return result
