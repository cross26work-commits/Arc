import pytest

from app.missions.dependency_planner import (
    DependencyCycleError,
    build_dependency_graph,
    build_dependency_plan,
    build_parallel_groups,
    detect_dependency_cycles,
    topological_sort,
)


def _file(
    path: str,
    dependencies: list[str] | None = None,
) -> dict:
    return {
        "path": path,
        "category": "BACKEND",
        "language": "python",
        "risk_level": "low",
        "score": 1,
        "direct_dependencies": (
            dependencies or []
        ),
    }


def test_builds_dependency_graph() -> None:
    graph = build_dependency_graph(
        [
            _file("app/models.py"),
            _file(
                "app/service.py",
                ["app/models.py"],
            ),
            _file(
                "app/router.py",
                ["app/service.py"],
            ),
        ]
    )

    assert graph["node_count"] == 3
    assert graph["edge_count"] == 2
    assert graph["edges"] == [
        {
            "from": "app/models.py",
            "to": "app/service.py",
            "type": "REQUIRES",
        },
        {
            "from": "app/service.py",
            "to": "app/router.py",
            "type": "REQUIRES",
        },
    ]


def test_topological_sort_orders_dependencies_first() -> None:
    graph = build_dependency_graph(
        [
            _file(
                "app/router.py",
                ["app/service.py"],
            ),
            _file(
                "app/service.py",
                ["app/models.py"],
            ),
            _file("app/models.py"),
        ]
    )

    order = topological_sort(graph)

    assert order.index(
        "app/models.py"
    ) < order.index(
        "app/service.py"
    )
    assert order.index(
        "app/service.py"
    ) < order.index(
        "app/router.py"
    )


def test_builds_parallel_groups() -> None:
    graph = build_dependency_graph(
        [
            _file("app/a.py"),
            _file("app/b.py"),
            _file(
                "app/c.py",
                [
                    "app/a.py",
                    "app/b.py",
                ],
            ),
        ]
    )

    groups = build_parallel_groups(
        graph
    )

    assert groups == [
        [
            "app/a.py",
            "app/b.py",
        ],
        [
            "app/c.py",
        ],
    ]


def test_detects_cycle() -> None:
    graph = build_dependency_graph(
        [
            _file(
                "app/a.py",
                ["app/b.py"],
            ),
            _file(
                "app/b.py",
                ["app/a.py"],
            ),
        ]
    )

    cycles = detect_dependency_cycles(
        graph
    )

    assert len(cycles) == 1
    assert cycles[0][0] == cycles[0][-1]


def test_topological_sort_rejects_cycle() -> None:
    graph = build_dependency_graph(
        [
            _file(
                "app/a.py",
                ["app/b.py"],
            ),
            _file(
                "app/b.py",
                ["app/a.py"],
            ),
        ]
    )

    with pytest.raises(
        DependencyCycleError,
    ):
        topological_sort(graph)


def test_dependency_plan_reports_cycle_safely() -> None:
    plan = build_dependency_plan(
        [
            _file(
                "app/a.py",
                ["app/b.py"],
            ),
            _file(
                "app/b.py",
                ["app/a.py"],
            ),
        ]
    )

    assert plan["valid"] is False
    assert len(plan["cycles"]) == 1
    assert plan["execution_order"] == []
    assert plan["parallel_groups"] == []


def test_external_dependencies_are_preserved() -> None:
    graph = build_dependency_graph(
        [
            _file(
                "app/service.py",
                [
                    "app/models.py",
                    "external/library.py",
                ],
            ),
            _file("app/models.py"),
        ]
    )

    service = next(
        node
        for node in graph["nodes"]
        if node["path"]
        == "app/service.py"
    )

    assert service[
        "dependencies"
    ] == [
        "app/models.py"
    ]
    assert service[
        "external_dependencies"
    ] == [
        "external/library.py"
    ]


def test_normalizes_windows_paths() -> None:
    plan = build_dependency_plan(
        [
            _file(
                r"app\service.py",
                [r"app\models.py"],
            ),
            _file(r"app\models.py"),
        ]
    )

    assert plan["valid"] is True
    assert plan[
        "execution_order"
    ] == [
        "app/models.py",
        "app/service.py",
    ]
