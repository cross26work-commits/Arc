from pathlib import Path

from app.missions.verification_runner import (
    _resolve_command,
    _resolve_python_verification_layout,
)


def _create_root_project(
    tmp_path: Path,
) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    return tmp_path


def test_root_python_project_layout(
    tmp_path: Path,
) -> None:
    root = _create_root_project(tmp_path)

    result = (
        _resolve_python_verification_layout(
            root
        )
    )

    assert result["working_root"] == (
        root.resolve()
    )
    assert result["compile_targets"] == [
        "src",
        "tests",
    ]
    assert result["backend_exists"] is False


def test_backend_python_project_layout(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    (backend / "app").mkdir(
        parents=True
    )

    result = (
        _resolve_python_verification_layout(
            tmp_path
        )
    )

    assert result["working_root"] == (
        backend.resolve()
    )
    assert result["compile_targets"] == [
        "app"
    ]
    assert result["backend_exists"] is True


def test_legacy_compile_command_uses_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _create_root_project(tmp_path)

    monkeypatch.setattr(
        "app.missions.verification_runner."
        "_resolve_python_executable",
        lambda project_root: "python",
    )

    result = _resolve_command(
        project_root=root,
        name="Compile",
        command=(
            "cd backend && "
            r"venv\Scripts\python.exe "
            "-m compileall -q app"
        ),
    )

    assert result["cwd"] == root.resolve()
    assert result["argv"] == [
        "python",
        "-m",
        "compileall",
        "-q",
        "src",
        "tests",
    ]


def test_legacy_pytest_command_uses_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _create_root_project(tmp_path)

    monkeypatch.setattr(
        "app.missions.verification_runner."
        "_resolve_python_executable",
        lambda project_root: "python",
    )

    result = _resolve_command(
        project_root=root,
        name="Tests",
        command=(
            "cd backend && "
            r"venv\Scripts\python.exe "
            "-m pytest"
        ),
    )

    assert result["cwd"] == root.resolve()
    assert result["argv"] == [
        "python",
        "-m",
        "pytest",
    ]
