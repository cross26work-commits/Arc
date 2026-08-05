from app.missions.planner_runner import (
    _apply_step_dependency_safety_rules,
)


def test_test_step_depends_on_backend_step() -> None:
    dependencies, parallel = (
        _apply_step_dependency_safety_rules(
            workstreams=[
                {
                    "position": 1,
                    "category": "BACKEND",
                },
                {
                    "position": 2,
                    "category": "TEST",
                },
            ],
            step_dependencies={
                "step-1": [],
                "step-2": [],
            },
            parallel_step_ids={
                "step-1",
                "step-2",
            },
        )
    )

    assert dependencies == {
        "step-1": [],
        "step-2": ["step-1"],
    }
    assert parallel == set()


def test_preserves_existing_dependency() -> None:
    dependencies, parallel = (
        _apply_step_dependency_safety_rules(
            workstreams=[
                {
                    "position": 1,
                    "category": "BACKEND",
                },
                {
                    "position": 2,
                    "category": "TEST",
                },
            ],
            step_dependencies={
                "step-1": [],
                "step-2": ["step-1"],
            },
            parallel_step_ids=set(),
        )
    )

    assert dependencies[
        "step-2"
    ] == ["step-1"]
    assert parallel == set()


def test_test_depends_on_latest_implementation_step() -> None:
    dependencies, _ = (
        _apply_step_dependency_safety_rules(
            workstreams=[
                {
                    "position": 1,
                    "category": "DATA",
                },
                {
                    "position": 2,
                    "category": "BACKEND",
                },
                {
                    "position": 3,
                    "category": "TEST",
                },
            ],
            step_dependencies={
                "step-1": [],
                "step-2": ["step-1"],
                "step-3": [],
            },
            parallel_step_ids={
                "step-3",
            },
        )
    )

    assert dependencies[
        "step-3"
    ] == ["step-2"]


def test_test_without_implementation_remains_independent() -> None:
    dependencies, parallel = (
        _apply_step_dependency_safety_rules(
            workstreams=[
                {
                    "position": 1,
                    "category": "TEST",
                }
            ],
            step_dependencies={
                "step-1": [],
            },
            parallel_step_ids={
                "step-1",
            },
        )
    )

    assert dependencies[
        "step-1"
    ] == []
    assert parallel == {
        "step-1"
    }
