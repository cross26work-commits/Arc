from pathlib import Path


EXCLUDED_NAMES = {
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
}

MAX_ENTRIES = 3000
MAX_DEPTH = 8


class ProjectReadError(Exception):
    pass


def _is_inside_project(project_root: Path, target: Path) -> bool:
    try:
        target.relative_to(project_root)
        return True
    except ValueError:
        return False


def build_project_tree(
    project_path: str,
    max_depth: int = MAX_DEPTH,
    max_entries: int = MAX_ENTRIES,
) -> dict:
    root = Path(project_path).expanduser().resolve()

    if not root.exists():
        raise ProjectReadError("プロジェクトフォルダが存在しません。")

    if not root.is_dir():
        raise ProjectReadError("プロジェクトパスがフォルダではありません。")

    entry_count = 0
    truncated = False

    def walk(directory: Path, depth: int) -> list[dict]:
        nonlocal entry_count, truncated

        if depth > max_depth or entry_count >= max_entries:
            truncated = True
            return []

        items: list[dict] = []

        try:
            children = sorted(
                directory.iterdir(),
                key=lambda item: (item.is_file(), item.name.lower()),
            )
        except (OSError, PermissionError):
            return items

        for child in children:
            if entry_count >= max_entries:
                truncated = True
                break

            if child.name in EXCLUDED_NAMES:
                continue

            try:
                resolved_child = child.resolve()
            except (OSError, RuntimeError):
                continue

            if not _is_inside_project(root, resolved_child):
                continue

            entry_count += 1

            relative_path = resolved_child.relative_to(root).as_posix()

            if resolved_child.is_dir():
                items.append(
                    {
                        "name": child.name,
                        "path": relative_path,
                        "type": "directory",
                        "children": walk(resolved_child, depth + 1),
                    }
                )
            elif resolved_child.is_file():
                try:
                    size = resolved_child.stat().st_size
                except OSError:
                    size = 0

                items.append(
                    {
                        "name": child.name,
                        "path": relative_path,
                        "type": "file",
                        "size": size,
                    }
                )

        return items

    return {
        "root_name": root.name,
        "root_path": str(root),
        "entries": walk(root, 0),
        "entry_count": entry_count,
        "truncated": truncated,
        "excluded_names": sorted(EXCLUDED_NAMES),
        "max_depth": max_depth,
        "max_entries": max_entries,
    }
