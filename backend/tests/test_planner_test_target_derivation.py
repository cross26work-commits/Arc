from app.missions import planner_runner


def _backend_file() -> dict:
    return {
        "path": "backend/app/api/auth.py",
        "role": "auth API routes",
        "language": "python",
        "score": 50,
        "category": "BACKEND",
        "risk_level": "low",
        "risk_score": 10,
        "direct_dependencies": [],
        "direct_dependents": [],
        "affected_count": 0,
        "reasons": [
            "Authentication backend target.",
        ],
        "warnings": [],
        "dependency": {},
    }


def test_does_not_invent_test_target_without_framework_evidence(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()

    (backend / "requirements.txt").write_text(
        "fastapi==0.138.2\n"
        "httpx==0.28.1\n",
        encoding="utf-8",
    )

    derive = getattr(
        planner_runner,
        "_derive_test_mutation_target",
        None,
    )

    assert derive is not None, (
        "Planner must provide evidence-based "
        "TEST target derivation."
    )

    target = derive(
        project_path=str(tmp_path),
        selected_files=[
            _backend_file(),
        ],
    )

    assert target is None


def test_derives_backend_pytest_target_when_pytest_is_declared(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    api_dir = backend / "app" / "api"

    api_dir.mkdir(
        parents=True,
    )

    (backend / "requirements.txt").write_text(
        "fastapi==0.138.2\n"
        "pytest==8.4.1\n",
        encoding="utf-8",
    )

    (api_dir / "auth.py").write_text(
        "def current_user():\n"
        "    return None\n",
        encoding="utf-8",
    )

    target = planner_runner._derive_test_mutation_target(
        project_path=str(tmp_path),
        selected_files=[
            _backend_file(),
        ],
    )

    assert target is not None
    assert target["path"] == (
        "backend/tests/test_auth.py"
    )
    assert target["category"] == "TEST"


def test_does_not_treat_pytest_plugin_as_pytest_evidence(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()

    (backend / "requirements.txt").write_text(
        "fastapi==0.138.2\n"
        "pytest-asyncio==1.1.0\n",
        encoding="utf-8",
    )

    target = planner_runner._derive_test_mutation_target(
        project_path=str(tmp_path),
        selected_files=[
            _backend_file(),
        ],
    )

    assert target is None


def test_does_not_choose_one_of_multiple_backend_targets(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()

    (backend / "requirements.txt").write_text(
        "pytest==8.4.1\n",
        encoding="utf-8",
    )

    auth_target = _backend_file()

    users_target = {
        **_backend_file(),
        "path": "backend/app/api/users.py",
        "role": "users API routes",
    }

    target = planner_runner._derive_test_mutation_target(
        project_path=str(tmp_path),
        selected_files=[
            auth_target,
            users_target,
        ],
    )

    assert target is None


def test_prefers_existing_backend_test_directory_convention(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    api_dir = backend / "app" / "api"
    test_dir = backend / "tests" / "api"

    api_dir.mkdir(
        parents=True,
    )
    test_dir.mkdir(
        parents=True,
    )

    (backend / "requirements.txt").write_text(
        "fastapi==0.138.2\n"
        "pytest==8.4.1\n",
        encoding="utf-8",
    )

    (api_dir / "auth.py").write_text(
        "def current_user():\n"
        "    return None\n",
        encoding="utf-8",
    )

    (test_dir / "test_users.py").write_text(
        "def test_users():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    target = planner_runner._derive_test_mutation_target(
        project_path=str(tmp_path),
        selected_files=[
            _backend_file(),
        ],
    )

    assert target is not None
    assert target["path"] == (
        "backend/tests/api/test_auth.py"
    )
    assert target["category"] == "TEST"


def test_does_not_treat_empty_matching_directory_as_test_convention(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    api_dir = backend / "app" / "api"
    test_dir = backend / "tests" / "api"

    api_dir.mkdir(
        parents=True,
    )
    test_dir.mkdir(
        parents=True,
    )

    (backend / "requirements.txt").write_text(
        "pytest==8.4.1\n",
        encoding="utf-8",
    )

    (api_dir / "auth.py").write_text(
        "def current_user():\n"
        "    return None\n",
        encoding="utf-8",
    )

    target = planner_runner._derive_test_mutation_target(
        project_path=str(tmp_path),
        selected_files=[
            _backend_file(),
        ],
    )

    assert target is not None
    assert target["path"] == (
        "backend/tests/test_auth.py"
    )
