from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Any


DEPENDENCY_PLANNER_VERSION = (
    "dependency-planner-v0.1"
)


class DependencyPlannerError(Exception):
    """依存関係計画の生成に失敗した場合の例外。"""


class DependencyCycleError(
    DependencyPlannerError
):
    """循環依存を検出した場合の例外。"""

    def __init__(
        self,
        cycles: list[list[str]],
    ) -> None:
        self.cycles = cycles

        rendered = "; ".join(
            " -> ".join(cycle)
            for cycle in cycles
        )

        super().__init__(
            "循環依存を検出しました: "
            + rendered
        )


def _normalize_path(
    value: Any,
) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().replace(
        "\\",
        "/",
    )

    while "//" in normalized:
        normalized = normalized.replace(
            "//",
            "/",
        )

    if not normalized:
        return None

    return normalized


def _deduplicate_paths(
    values: list[Any],
) -> list[str]:
    results: list[str] = []

    for value in values:
        normalized = _normalize_path(value)

        if (
            normalized is not None
            and normalized not in results
        ):
            results.append(normalized)

    return results


def build_dependency_graph(
    selected_files: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}

    for item in selected_files:
        path = _normalize_path(
            item.get("path")
        )

        if path is None:
            continue

        nodes[path] = {
            "path": path,
            "category": item.get(
                "category",
                "OTHER",
            ),
            "language": item.get("language"),
            "risk_level": str(
                item.get("risk_level")
                or "unknown"
            ).lower(),
            "score": item.get("score", 0),
            "dependencies": [],
            "dependents": [],
            "external_dependencies": [],
        }

    selected_paths = set(nodes)

    for item in selected_files:
        path = _normalize_path(
            item.get("path")
        )

        if path not in nodes:
            continue

        dependencies = _deduplicate_paths(
            list(
                item.get(
                    "direct_dependencies",
                    [],
                )
                or []
            )
        )

        for dependency in dependencies:
            if dependency == path:
                nodes[path][
                    "dependencies"
                ].append(dependency)
                continue

            if dependency in selected_paths:
                nodes[path][
                    "dependencies"
                ].append(dependency)

                nodes[dependency][
                    "dependents"
                ].append(path)
            else:
                nodes[path][
                    "external_dependencies"
                ].append(dependency)

    edges: list[dict[str, str]] = []

    for path, node in nodes.items():
        node["dependencies"] = sorted(
            set(node["dependencies"])
        )
        node["dependents"] = sorted(
            set(node["dependents"])
        )
        node["external_dependencies"] = (
            sorted(
                set(
                    node[
                        "external_dependencies"
                    ]
                )
            )
        )

        for dependency in node[
            "dependencies"
        ]:
            edges.append(
                {
                    "from": dependency,
                    "to": path,
                    "type": "REQUIRES",
                }
            )

    edges.sort(
        key=lambda item: (
            item["from"],
            item["to"],
        )
    )

    return {
        "graph_version":
            DEPENDENCY_PLANNER_VERSION,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": [
            nodes[path]
            for path in sorted(nodes)
        ],
        "edges": edges,
    }


def _adjacency(
    graph: dict[str, Any],
) -> tuple[
    dict[str, set[str]],
    dict[str, int],
]:
    paths = {
        node["path"]
        for node in graph.get(
            "nodes",
            [],
        )
    }

    outgoing: dict[str, set[str]] = {
        path: set()
        for path in paths
    }

    indegree: dict[str, int] = {
        path: 0
        for path in paths
    }

    for edge in graph.get("edges", []):
        source = edge.get("from")
        target = edge.get("to")

        if (
            source not in paths
            or target not in paths
        ):
            continue

        if target in outgoing[source]:
            continue

        outgoing[source].add(target)
        indegree[target] += 1

    return outgoing, indegree


def detect_dependency_cycles(
    graph: dict[str, Any],
) -> list[list[str]]:
    outgoing, _ = _adjacency(graph)

    state: dict[str, int] = {
        path: 0
        for path in outgoing
    }
    stack: list[str] = []
    stack_positions: dict[str, int] = {}
    cycles: list[list[str]] = []
    cycle_keys: set[tuple[str, ...]] = set()

    def canonical_cycle(
        cycle: list[str],
    ) -> tuple[str, ...]:
        body = cycle[:-1]

        rotations = [
            tuple(
                body[index:]
                + body[:index]
            )
            for index in range(len(body))
        ]

        canonical = min(rotations)
        return canonical

    def visit(path: str) -> None:
        state[path] = 1
        stack_positions[path] = len(stack)
        stack.append(path)

        for dependent in sorted(
            outgoing[path]
        ):
            if state[dependent] == 0:
                visit(dependent)
                continue

            if state[dependent] != 1:
                continue

            start = stack_positions[
                dependent
            ]
            cycle = (
                stack[start:]
                + [dependent]
            )
            key = canonical_cycle(cycle)

            if key not in cycle_keys:
                cycle_keys.add(key)
                cycles.append(cycle)

        stack.pop()
        stack_positions.pop(path, None)
        state[path] = 2

    for path in sorted(outgoing):
        if state[path] == 0:
            visit(path)

    return cycles


def topological_sort(
    graph: dict[str, Any],
) -> list[str]:
    outgoing, indegree = _adjacency(
        graph
    )

    queue = [
        path
        for path, count in indegree.items()
        if count == 0
    ]
    heapq.heapify(queue)

    order: list[str] = []

    while queue:
        path = heapq.heappop(queue)
        order.append(path)

        for dependent in sorted(
            outgoing[path]
        ):
            indegree[dependent] -= 1

            if indegree[dependent] == 0:
                heapq.heappush(
                    queue,
                    dependent,
                )

    if len(order) != len(indegree):
        cycles = detect_dependency_cycles(
            graph
        )

        raise DependencyCycleError(
            cycles=cycles
            or [["UNKNOWN_CYCLE"]],
        )

    return order


def build_parallel_groups(
    graph: dict[str, Any],
) -> list[list[str]]:
    outgoing, indegree = _adjacency(
        graph
    )

    remaining = set(indegree)
    groups: list[list[str]] = []

    while remaining:
        ready = sorted(
            path
            for path in remaining
            if indegree[path] == 0
        )

        if not ready:
            cycles = detect_dependency_cycles(
                graph
            )

            raise DependencyCycleError(
                cycles=cycles
                or [["UNKNOWN_CYCLE"]],
            )

        groups.append(ready)

        for path in ready:
            remaining.remove(path)

            for dependent in outgoing[
                path
            ]:
                indegree[dependent] -= 1

    return groups


def build_dependency_plan(
    selected_files: list[dict[str, Any]],
) -> dict[str, Any]:
    graph = build_dependency_graph(
        selected_files
    )

    cycles = detect_dependency_cycles(
        graph
    )

    if cycles:
        return {
            "planner_version":
                DEPENDENCY_PLANNER_VERSION,
            "valid": False,
            "graph": graph,
            "cycles": cycles,
            "execution_order": [],
            "parallel_groups": [],
        }

    execution_order = topological_sort(
        graph
    )
    parallel_groups = (
        build_parallel_groups(graph)
    )

    return {
        "planner_version":
            DEPENDENCY_PLANNER_VERSION,
        "valid": True,
        "graph": graph,
        "cycles": [],
        "execution_order":
            execution_order,
        "parallel_groups":
            parallel_groups,
    }
