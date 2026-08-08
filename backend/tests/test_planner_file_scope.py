from app.missions.planner_runner import (
    _classify_path,
    _extract_explicit_paths,
    _is_ignored_plan_path,
    _select_files,
)


def _candidate(
    path: str,
    score: int,
) -> dict:
    return {
        "path": path,
        "role": "fixture",
        "language": "python",
        "score": score,
        "reasons": ["matched"],
        "dependency": {},
    }


def test_classifies_python_test_path() -> None:
    assert _classify_path(
        "tests/test_calculator.py"
    ) == "TEST"


def test_classifies_src_python_as_backend() -> None:
    assert _classify_path(
        "src/calculator.py"
    ) == "BACKEND"


def test_classifies_documentation_and_config() -> None:
    assert _classify_path(
        "README.md"
    ) == "DOCUMENTATION"

    assert _classify_path(
        "pyproject.toml"
    ) == "CONFIG"


def test_ignores_generated_directories() -> None:
    assert _is_ignored_plan_path(
        ".pytest_cache/README.md"
    ) is True

    assert _is_ignored_plan_path(
        "src/__pycache__/module.pyc"
    ) is True


def test_extracts_explicit_paths() -> None:
    paths = _extract_explicit_paths(
        (
            "src/calculator.pyへ関数を追加し、"
            "tests/test_calculator.pyへ"
            "テストを追加する。"
        )
    )

    assert paths == {
        "src/calculator.py",
        "tests/test_calculator.py",
    }


def test_explicit_scope_filters_unrelated_files() -> None:
    selected = _select_files(
        [
            _candidate("README.md", 30),
            _candidate(
                "tests/test_calculator.py",
                27,
            ),
            _candidate(
                "src/calculator.py",
                18,
            ),
            _candidate(
                ".pytest_cache/README.md",
                15,
            ),
            _candidate(
                "pyproject.toml",
                12,
            ),
        ],
        explicit_paths={
            "src/calculator.py",
            "tests/test_calculator.py",
        },
    )

    assert [
        item["path"]
        for item in selected
    ] == [
        "tests/test_calculator.py",
        "src/calculator.py",
    ]

    assert {
        item["category"]
        for item in selected
    } == {
        "BACKEND",
        "TEST",
    }



def test_select_files_prioritizes_semantic_warning_candidate() -> None:
    candidates = []

    for index in range(10):
        candidates.append(
            {
                "path": f"backend/app/services/high_{index}.py",
                "role": "service",
                "language": "python",
                "score": 100 - index,
                "reasons": ["search-match"],
                "warnings": [],
                "dependency": {
                    "risk": {
                        "level": "low",
                        "score": 10,
                    },
                },
            }
        )

    candidates.append(
        {
            "path": "backend/app/api/auth.py",
            "role": "auth API routes",
            "language": "python",
            "score": 1,
            "reasons": ["search-match"],
            "warnings": [
                {
                    "level": "medium",
                    "code": "STUB_ROUTE_HANDLER",
                    "message": (
                        "Stub route handlers detected: "
                        "login_stub, register_stub, logout_stub"
                    ),
                }
            ],
            "dependency": {
                "risk": {
                    "level": "low",
                    "score": 10,
                },
            },
        }
    )

    selected = _select_files(
        candidates,
        max_files=10,
    )

    paths = [
        item["path"]
        for item in selected
    ]

    assert "backend/app/api/auth.py" in paths


def test_select_files_preserves_semantic_warnings() -> None:
    selected = _select_files(
        [
            {
                "path": "backend/app/api/auth.py",
                "role": "auth API routes",
                "language": "python",
                "score": 37,
                "reasons": ["search-match"],
                "warnings": [
                    {
                        "level": "medium",
                        "code": "STUB_ROUTE_HANDLER",
                        "message": (
                            "Stub route handlers detected: "
                            "login_stub, register_stub, logout_stub"
                        ),
                    }
                ],
                "dependency": {
                    "risk": {
                        "level": "low",
                        "score": 10,
                    },
                },
            }
        ],
        max_files=10,
    )

    assert len(selected) == 1

    warnings = selected[0]["warnings"]

    assert len(warnings) == 1
    assert (
        warnings[0]["code"]
        == "STUB_ROUTE_HANDLER"
    )
