from app.missions.self_repair_planner import (
    _collect_failures,
)


def test_collect_failures_uses_explicit_suspected_files():
    verification = {
        "passed": False,
        "failure_category": "TEST",
        "results": [
            {
                "name": "pytest",
                "category": "TEST",
                "failure_category": "TEST",
                "passed": False,
                "returncode": 1,
                "stdout": "",
                "stderr": (
                    "tests/test_calculator.py:"
                    " test_multiply failed"
                ),
                "suspected_files": [
                    "src/calculator.py",
                ],
            }
        ],
    }

    failures = _collect_failures(
        verification
    )

    assert len(failures) == 1

    assert failures[0][
        "suspected_files"
    ] == [
        "src/calculator.py",
        "tests/test_calculator.py",
    ]


def test_collect_failures_deduplicates_paths():
    verification = {
        "passed": False,
        "failure_category": "TEST",
        "results": [
            {
                "name": "pytest",
                "passed": False,
                "stderr": (
                    "src/calculator.py:13 failed"
                ),
                "suspected_files": [
                    "src/calculator.py",
                ],
            }
        ],
    }

    failures = _collect_failures(
        verification
    )

    assert failures[0][
        "suspected_files"
    ] == [
        "src/calculator.py",
    ]
