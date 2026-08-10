from __future__ import annotations

import os

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.missions.dependency_planner import (
    build_dependency_plan,
)
from pydantic import ValidationError

from app.missions.models import (
    FileOperation,
    ImplementationPlan,
    ImplementationStep,
    MissionTaskUpdate,
    RequirementAnalyzerResult,
)
from app.missions.service import (
    add_mission_log,
    get_mission,
    update_mission_task,
)


class MissionPlannerError(Exception):
    """Mission計画生成に失敗した場合の例外。"""


def _get_project_path(
    project_id: int,
) -> str:
    with get_connection() as connection:
        project = connection.execute(
            """
            SELECT path
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()

    if project is None:
        raise MissionPlannerError(
            f"Project was not found: {project_id}"
        )

    project_path = str(
        project["path"] or ""
    ).strip()

    if not project_path:
        raise MissionPlannerError(
            f"Project path is empty: {project_id}"
        )

    return project_path


def _load_requirement_contract(
    task: dict[str, Any],
) -> RequirementAnalyzerResult:
    if str(
        task.get("status") or ""
    ).strip().upper() != "COMPLETED":
        raise MissionPlannerError(
            "REQUIREMENTS Taskが完了していません。"
        )

    raw_result = task.get("result")

    if not raw_result:
        raise MissionPlannerError(
            "REQUIREMENTS結果が保存されていません。"
        )

    if isinstance(raw_result, dict):
        payload = raw_result
    elif isinstance(raw_result, str):
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError as error:
            raise MissionPlannerError(
                "REQUIREMENTS結果のJSONを読み取れません。"
            ) from error
    else:
        raise MissionPlannerError(
            "REQUIREMENTS結果の形式が不正です。"
        )

    if not isinstance(payload, dict):
        raise MissionPlannerError(
            "REQUIREMENTS結果はJSON Objectである必要があります。"
        )

    try:
        return RequirementAnalyzerResult.model_validate(
            payload
        )
    except ValidationError as error:
        raise MissionPlannerError(
            "REQUIREMENTS結果がRequirement Contractの"
            "形式に適合していません。"
        ) from error


def _normalize_plan_path(path: str) -> str:
    return str(path).strip().replace(
        "\\",
        "/",
    )


def _is_ignored_plan_path(path: str) -> bool:
    normalized = _normalize_plan_path(
        path
    ).lower()

    parts = {
        part
        for part in normalized.split("/")
        if part
    }

    ignored_parts = {
        ".git",
        ".pytest_cache",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
    }

    return bool(parts & ignored_parts)


def _classify_path(path: str) -> str:
    normalized = _normalize_plan_path(path)
    lowered = normalized.lower()
    name = lowered.rsplit("/", 1)[-1]

    is_python_test = (
        name.startswith("test_")
        and name.endswith(".py")
    )

    is_script_test = name.endswith(
        (
            "_test.py",
            ".test.ts",
            ".test.tsx",
            ".spec.ts",
            ".spec.tsx",
            ".test.js",
            ".test.jsx",
            ".spec.js",
            ".spec.jsx",
        )
    )

    if (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or is_python_test
        or is_script_test
    ):
        return "TEST"

    if (
        lowered.startswith("migrations/")
        or "/migrations/" in lowered
        or lowered.startswith("schemas/")
        or "/schemas/" in lowered
        or lowered.startswith("models/")
        or "/models/" in lowered
        or "database" in lowered
    ):
        return "DATA"

    frontend_extension = lowered.endswith(
        (
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".css",
        )
    )

    if (
        lowered.startswith("frontend/")
        or lowered.startswith("web/")
        or lowered.startswith("client/")
        or lowered.startswith("src/components/")
        or lowered.startswith("src/pages/")
        or (
            lowered.startswith("src/app/")
            and frontend_extension
        )
    ):
        return "FRONTEND"

    if lowered.endswith(
        (
            ".md",
            ".rst",
        )
    ):
        return "DOCUMENTATION"

    if (
        name in {
            "pyproject.toml",
            "package.json",
            "package-lock.json",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "tox.ini",
        }
        or lowered.endswith(
            (
                ".toml",
                ".yaml",
                ".yml",
                ".json",
                ".ini",
                ".cfg",
            )
        )
    ):
        return "CONFIG"

    is_python_backend = (
        lowered.endswith(".py")
        and lowered.startswith(
            (
                "src/",
                "app/",
                "backend/",
            )
        )
    )

    if (
        is_python_backend
        or "/api/" in lowered
        or "/routers/" in lowered
        or "/services/" in lowered
        or "/core/" in lowered
        or name == "main.py"
    ):
        return "BACKEND"

    return "OTHER"


def _extract_explicit_paths(
    *values: str | None,
) -> set[str]:
    import re

    pattern = re.compile(
        r"(?<![A-Za-z0-9_.-])"
        r"((?:[A-Za-z0-9_.-]+/)+"
        r"[A-Za-z0-9_.-]+\."
        r"[A-Za-z0-9]+)"
    )

    paths: set[str] = set()

    for value in values:
        if not isinstance(value, str):
            continue

        for match in pattern.findall(value):
            normalized = _normalize_plan_path(
                match
            )

            if normalized:
                paths.add(normalized)

    return paths

def _risk_weight(level: str | None) -> int:
    return {
        "high": 3,
        "medium": 2,
        "low": 1,
    }.get(level or "", 0)


def _semantic_warning_weight(
    warnings: Any,
) -> int:
    weight = 0

    for warning in warnings or []:
        if not isinstance(warning, dict):
            continue

        level = str(
            warning.get("level") or ""
        ).strip().lower()

        current = {
            "high": 2,
            "medium": 1,
        }.get(level, 0)

        weight = max(
            weight,
            current,
        )

    return weight


def _select_files(
    candidates: list[dict[str, Any]],
    *,
    explicit_paths: set[str] | None = None,
    max_files: int = 10,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    normalized_explicit_paths = {
        _normalize_plan_path(path)
        for path in (
            explicit_paths or set()
        )
        if str(path).strip()
    }

    usable_candidates = []

    for item in candidates:
        raw_path = item.get("path")

        if (
            not isinstance(raw_path, str)
            or not raw_path.strip()
        ):
            continue

        normalized_path = (
            _normalize_plan_path(raw_path)
        )

        if _is_ignored_plan_path(
            normalized_path
        ):
            continue

        usable_candidates.append(
            {
                **item,
                "path": normalized_path,
            }
        )

    candidate_by_path = {
        item["path"]: item
        for item in usable_candidates
    }

    if normalized_explicit_paths:
        explicit_candidates: list[
            dict[str, Any]
        ] = []

        for explicit_path in sorted(
            normalized_explicit_paths
        ):
            existing = candidate_by_path.get(
                explicit_path
            )

            if existing is not None:
                explicit_candidates.append(
                    existing
                )
                continue

            explicit_candidates.append(
                {
                    "path": explicit_path,
                    "role": (
                        "Explicit mission target"
                    ),
                    "language": None,
                    "score": 1000,
                    "dependency": {},
                    "reasons": [
                        (
                            "Explicitly specified "
                            "in Mission objective "
                            "or success criteria."
                        )
                    ],
                    "warnings": [],
                }
            )

        usable_candidates = (
            explicit_candidates
        )

    for item in usable_candidates:
        path = item["path"]

        dependency = item.get(
            "dependency"
        )

        if not isinstance(dependency, dict):
            dependency = {}

        risk = dependency.get("risk")

        if not isinstance(risk, dict):
            risk = {}

        selected.append(
            {
                "path": path,
                "role": item.get("role"),
                "language": item.get(
                    "language"
                ),
                "score": item.get(
                    "score",
                    0,
                ),
                "category": _classify_path(
                    path
                ),
                "risk_level": risk.get(
                    "level",
                    "unknown",
                ),
                "risk_score": risk.get(
                    "score",
                    0,
                ),
                "direct_dependencies": (
                    dependency.get(
                        "direct_dependencies",
                        [],
                    )
                ),
                "direct_dependents": (
                    dependency.get(
                        "direct_dependents",
                        [],
                    )
                ),
                "affected_count": (
                    dependency.get(
                        "affected_count",
                        0,
                    )
                ),
                "reasons": item.get(
                    "reasons",
                    [],
                ),
                "warnings": list(
                    item.get("warnings") or []
                ),
            }
        )

    selected.sort(
        key=lambda item: (
            -_semantic_warning_weight(
                item.get("warnings")
            ),
            -int(item.get("score", 0)),
            item["path"],
        )
    )

    return selected[:max_files]

def _build_read_only_design_context(
    *,
    selected_files: list[dict[str, Any]],
    context_candidates: list[dict[str, Any]] | None,
    max_items: int = 5,
) -> str:
    selected_paths = {
        str(item.get("path") or "")
        for item in selected_files
    }

    details: list[str] = []

    for item in context_candidates or []:
        if not isinstance(item, dict):
            continue

        path = str(
            item.get("path") or ""
        ).strip()

        if (
            not path
            or path in selected_paths
        ):
            continue

        signals: list[str] = []

        for call in item.get("sdk_calls") or []:
            if not isinstance(call, dict):
                continue

            sdk = str(
                call.get("sdk") or ""
            ).strip()

            operation = str(
                call.get("operation") or ""
            ).strip()

            if sdk and operation:
                signals.append(
                    f"{sdk}:{operation}"
                )
            elif sdk:
                signals.append(sdk)
            elif operation:
                signals.append(operation)

        for call in item.get("api_calls") or []:
            if not isinstance(call, dict):
                continue

            method = str(
                call.get("method") or ""
            ).strip().upper()

            url = str(
                call.get("url") or ""
            ).strip()

            client = str(
                call.get("client") or ""
            ).strip()

            if method and url:
                signal = f"{method}:{url}"

                if client:
                    signal = (
                        f"{client}:{signal}"
                    )

                signals.append(signal)

        for warning in item.get("warnings") or []:
            if not isinstance(warning, dict):
                continue

            code = str(
                warning.get("code") or ""
            ).strip()

            if code:
                signals.append(
                    f"warning:{code}"
                )

        if not signals:
            continue

        details.append(
            f"{path} ({', '.join(signals[:6])})"
        )

        if len(details) >= max_items:
            break

    return "; ".join(details)


def _build_semantic_design_guidance(
    *,
    selected_files: list[dict[str, Any]],
    context_candidates: list[dict[str, Any]] | None,
) -> str:
    selected_paths = {
        str(item.get("path") or "")
        for item in selected_files
    }

    warning_codes = {
        str(warning.get("code") or "").strip()
        for item in selected_files
        for warning in (
            item.get("warnings") or []
        )
        if isinstance(warning, dict)
    }

    context_items = [
        item
        for item in (
            context_candidates or []
        )
        if (
            isinstance(item, dict)
            and str(item.get("path") or "")
            not in selected_paths
        )
    ]

    has_sdk_context = any(
        item.get("sdk_calls")
        for item in context_items
    )

    has_api_context = any(
        item.get("api_calls")
        for item in context_items
    )

    guidance: list[str] = []

    if "STUB_ROUTE_HANDLER" in warning_codes:
        guidance.append(
            "Verify route callers before changing "
            "or removing stub handlers."
        )

    if has_sdk_context:
        guidance.append(
            "Avoid duplicate functionality when an "
            "existing SDK-backed implementation "
            "already owns the behavior."
        )

    if has_api_context:
        guidance.append(
            "Preserve referenced API endpoints and "
            "their compatibility."
        )

    return " ".join(guidance)


def _build_workstreams(
    files: list[dict[str, Any]],
    *,
    context_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in files:
        grouped[item["category"]].append(item)

    order = [
        "BACKEND",
        "DATA",
        "FRONTEND",
        "TEST",
        "CONFIG",
        "DOCUMENTATION",
        "OTHER",
    ]

    labels = {
        "BACKEND": "Backend・API",
        "DATA": "DB・データモデル",
        "FRONTEND": "Frontend・画面",
        "TEST": "テスト",
        "CONFIG": "設定",
        "DOCUMENTATION": "ドキュメント",
        "OTHER": "その他",
    }

    design_context = (
        _build_read_only_design_context(
            selected_files=files,
            context_candidates=context_candidates,
        )
    )

    semantic_guidance = (
        _build_semantic_design_guidance(
            selected_files=files,
            context_candidates=context_candidates,
        )
    )

    workstreams: list[dict[str, Any]] = []
    position = 1

    for category in order:
        category_files = grouped.get(category, [])

        if not category_files:
            continue

        workstreams.append(
            {
                "position": position,
                "category": category,
                "title": labels[category],
                "file_count": len(category_files),
                "files": [
                    item["path"]
                    for item in category_files
                ],
                "purpose": (
                    f"{labels[category]}に関係する候補を確認し、"
                    "Mission目的に必要な変更だけを実施する。"
                ),
            }
        )

        if design_context:
            workstreams[-1]["purpose"] = (
                f'{workstreams[-1]["purpose"]} '
                f"Read-only design context: "
                f"{design_context}"
            )

        if semantic_guidance:
            workstreams[-1]["purpose"] = (
                f'{workstreams[-1]["purpose"]} '
                f"Design guidance: "
                f"{semantic_guidance}"
            )

        position += 1

    return workstreams


def _build_verification_commands(
    files: list[dict[str, Any]],
    *,
    requirement: RequirementAnalyzerResult | None = None,
) -> list[dict[str, str]]:
    categories = {
        item["category"]
        for item in files
    }

    commands: list[dict[str, str]] = []

    if os.name == "nt":
        python_command = r"venv\Scripts\python.exe"
    else:
        python_command = "venv/bin/python"

    if {
        "BACKEND",
        "DATA",
    } & categories:
        commands.append(
            {
                "name": "Python構文確認",
                "command": (
                    "cd backend && "
                    f"{python_command} -m compileall -q app"
                ),
            }
        )

    if "FRONTEND" in categories:
        commands.append(
            {
                "name": "Frontend Build",
                "command": "npm run build",
            }
        )

    requirement_text = ""

    if requirement is not None:
        requirement_text = " ".join(
            [
                *requirement.requirements,
                *requirement.success_criteria,
            ]
        ).lower()

    tests_required = (
        "TEST" in categories
        or any(
            marker in requirement_text
            for marker in (
                "test",
                "pytest",
                "regression",
                "???",
                "??",
            )
        )
    )

    if tests_required:
        commands.append(
            {
                "name": "自動テスト",
                "command": (
                    "cd backend && "
                    f"{python_command} -m pytest"
                ),
            }
        )

    commands.append(
        {
            "name": "Git差分確認",
            "command": "git diff --check && git status",
        }
    )

    return commands


def _requirement_requires_test_mutation(
    requirement: RequirementAnalyzerResult,
) -> bool:
    texts = [
        requirement.objective,
        *requirement.requirements,
        *requirement.success_criteria,
    ]

    mutation_phrases = (
        "add test",
        "add tests",
        "add regression test",
        "add regression tests",
        "add focused regression test",
        "add focused regression tests",
        "add or update test",
        "add or update tests",
        "add or update regression test",
        "add or update regression tests",
        "add or update focused regression test",
        "add or update focused regression tests",
        "create test",
        "create tests",
        "create regression test",
        "create regression tests",
        "write test",
        "write tests",
        "write regression test",
        "write regression tests",
        "update test",
        "update tests",
        "update regression test",
        "update regression tests",
        "modify test",
        "modify tests",
        "\u30c6\u30b9\u30c8\u3092\u8ffd\u52a0",
        "\u30c6\u30b9\u30c8\u3092\u4f5c\u6210",
        "\u30c6\u30b9\u30c8\u3092\u66f4\u65b0",
        "\u30c6\u30b9\u30c8\u3092\u5909\u66f4",
        "\u56de\u5e30\u30c6\u30b9\u30c8\u3092\u8ffd\u52a0",
        "\u56de\u5e30\u30c6\u30b9\u30c8\u3092\u4f5c\u6210",
        "\u56de\u5e30\u30c6\u30b9\u30c8\u3092\u66f4\u65b0",
    )

    negated_phrases = (
        "do not add test",
        "do not add tests",
        "do not create test",
        "do not create tests",
        "do not update test",
        "do not update tests",
        "do not write test",
        "do not write tests",
        "must not add test",
        "must not add tests",
        "must not create test",
        "must not create tests",
        "must not update test",
        "must not update tests",
        "must not write test",
        "must not write tests",
        "\u30c6\u30b9\u30c8\u3092\u8ffd\u52a0\u3057\u306a\u3044",
        "\u30c6\u30b9\u30c8\u3092\u4f5c\u6210\u3057\u306a\u3044",
        "\u30c6\u30b9\u30c8\u3092\u66f4\u65b0\u3057\u306a\u3044",
        "\u30c6\u30b9\u30c8\u3092\u5909\u66f4\u3057\u306a\u3044",
    )

    for value in texts:
        normalized = " ".join(
            str(value or "").lower().split()
        )

        if not normalized:
            continue

        if any(
            phrase in normalized
            for phrase in negated_phrases
        ):
            continue

        if any(
            phrase in normalized
            for phrase in mutation_phrases
        ):
            return True

    return False


def _validate_required_mutation_scope(
    *,
    selected_files: list[dict[str, Any]],
    requirement: RequirementAnalyzerResult,
) -> None:
    if not _requirement_requires_test_mutation(
        requirement
    ):
        return

    has_test_target = any(
        str(
            item.get("category") or ""
        ).strip().upper()
        == "TEST"
        for item in selected_files
    )

    if has_test_target:
        return

    raise MissionPlannerError(
        "Requirement requires a TEST mutation, "
        "but selected files contain no TEST target."
    )


def _calculate_plan_risk(
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    high = sum(
        1
        for item in files
        if item["risk_level"] == "high"
    )

    medium = sum(
        1
        for item in files
        if item["risk_level"] == "medium"
    )

    affected = sum(
        int(item.get("affected_count", 0))
        for item in files
    )

    score = min(
        high * 25
        + medium * 12
        + min(affected, 30),
        100,
    )

    if score >= 70:
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
        "high_risk_file_count": high,
        "medium_risk_file_count": medium,
        "affected_reference_count": affected,
        "reason": (
            f"高リスク候補{high}件、"
            f"中リスク候補{medium}件、"
            f"影響参照合計{affected}件"
        ),
    }


def _estimate_effort(
    files: list[dict[str, Any]],
    workstreams: list[dict[str, Any]],
) -> dict[str, Any]:
    file_count = len(files)
    stream_count = len(workstreams)

    points = file_count + stream_count * 2

    if points <= 6:
        level = "small"
        label = "小"
        estimated_minutes = 30
    elif points <= 14:
        level = "medium"
        label = "中"
        estimated_minutes = 90
    else:
        level = "large"
        label = "大"
        estimated_minutes = 180

    return {
        "level": level,
        "label": label,
        "estimated_minutes": estimated_minutes,
        "basis": (
            f"候補ファイル{file_count}件、"
            f"作業領域{stream_count}件"
        ),
        "note": (
            "現時点のルールベース概算。"
            "詳細設計後に再評価する。"
        ),
    }


def _normalize_risk_level(
    value: str | None,
) -> str:
    normalized = str(
        value or "UNKNOWN"
    ).strip().upper()

    if normalized in {
        "LOW",
        "MEDIUM",
        "HIGH",
    }:
        return normalized

    return "UNKNOWN"


def _normalize_effort_level(
    value: str | None,
) -> str:
    normalized = str(
        value or "UNKNOWN"
    ).strip().upper()

    if normalized in {
        "SMALL",
        "MEDIUM",
        "LARGE",
    }:
        return normalized

    return "UNKNOWN"


def _build_clarification_questions(
    requirement: RequirementAnalyzerResult,
) -> list[str]:
    questions: list[str] = []

    for item in requirement.missing_information:
        questions.append(
            f"{item}について追加情報を指定してください。"
        )

    for item in requirement.ambiguities:
        questions.append(
            f"{item}を具体化してください。"
        )

    deduplicated: list[str] = []

    for question in questions:
        if question not in deduplicated:
            deduplicated.append(question)

    return deduplicated[:100]


def _to_file_operation(
    item: dict[str, Any],
    *,
    project_path: str,
) -> FileOperation:
    risk_level = _normalize_risk_level(
        item.get("risk_level")
    )

    reasons = [
        str(reason)
        for reason in item.get("reasons", [])
        if str(reason).strip()
    ]

    purpose = (
        reasons[0]
        if reasons
        else (
            f"{item['path']}をMission目的に"
            "必要な範囲で更新する。"
        )
    )

    project_root = Path(
        project_path
    ).expanduser().resolve()

    target_path = (
        project_root
        / str(item["path"])
    ).resolve()

    try:
        target_path.relative_to(
            project_root
        )
    except ValueError as error:
        raise MissionPlannerError(
            "Planned file path is outside "
            f"the project root: {item['path']}"
        ) from error

    operation = (
        "UPDATE"
        if target_path.exists()
        else "CREATE"
    )

    return FileOperation(
        path=item["path"],
        operation=operation,
        purpose=purpose,
        category=item.get("category", "OTHER"),
        language=item.get("language"),
        depends_on=[
            str(value)
            for value in item.get(
                "direct_dependencies",
                [],
            )
        ],
        affected_files=[
            str(value)
            for value in item.get(
                "direct_dependents",
                [],
            )
        ],
        risk_level=risk_level,
        reasons=reasons,
    )


def _build_step_dependency_context(
    *,
    workstreams: list[dict[str, Any]],
    dependency_plan: dict[str, Any],
) -> dict[str, Any]:
    step_ids = [
        f"step-{int(stream['position'])}"
        for stream in workstreams
    ]

    path_to_step: dict[str, str] = {}

    for stream in workstreams:
        step_id = (
            f"step-{int(stream['position'])}"
        )

        for path in stream.get("files", []):
            normalized = str(path).replace(
                "\\",
                "/",
            )

            path_to_step[normalized] = step_id

    if dependency_plan.get("valid") is not True:
        sequential_dependencies: dict[
            str,
            list[str],
        ] = {}

        previous_step_id: str | None = None

        for step_id in step_ids:
            sequential_dependencies[step_id] = (
                [previous_step_id]
                if previous_step_id
                else []
            )
            previous_step_id = step_id

        return {
            "step_dependencies":
                sequential_dependencies,
            "step_execution_order":
                step_ids,
            "parallel_step_groups": [],
            "parallel_step_ids": set(),
            "file_execution_order": [],
            "fallback_used": True,
        }

    step_dependencies: dict[
        str,
        set[str],
    ] = {
        step_id: set()
        for step_id in step_ids
    }

    graph = dependency_plan.get(
        "graph",
        {},
    )

    for edge in graph.get("edges", []):
        source_path = str(
            edge.get("from") or ""
        ).replace("\\", "/")
        target_path = str(
            edge.get("to") or ""
        ).replace("\\", "/")

        source_step = path_to_step.get(
            source_path
        )
        target_step = path_to_step.get(
            target_path
        )

        if (
            source_step is None
            or target_step is None
            or source_step == target_step
        ):
            continue

        step_dependencies[
            target_step
        ].add(source_step)

    file_execution_order = [
        str(path)
        for path in dependency_plan.get(
            "execution_order",
            [],
        )
    ]

    step_execution_order: list[str] = []

    for path in file_execution_order:
        step_id = path_to_step.get(
            path.replace("\\", "/")
        )

        if (
            step_id is not None
            and step_id
            not in step_execution_order
        ):
            step_execution_order.append(
                step_id
            )

    for step_id in step_ids:
        if step_id not in step_execution_order:
            step_execution_order.append(
                step_id
            )

    parallel_step_groups: list[
        list[str]
    ] = []

    for file_group in dependency_plan.get(
        "parallel_groups",
        [],
    ):
        step_group: list[str] = []

        for path in file_group:
            step_id = path_to_step.get(
                str(path).replace(
                    "\\",
                    "/",
                )
            )

            if (
                step_id is not None
                and step_id not in step_group
            ):
                step_group.append(step_id)

        if len(step_group) < 2:
            continue

        if step_group not in parallel_step_groups:
            parallel_step_groups.append(
                step_group
            )

    parallel_step_ids = {
        step_id
        for group in parallel_step_groups
        for step_id in group
    }

    return {
        "step_dependencies": {
            step_id: sorted(dependencies)
            for step_id, dependencies
            in step_dependencies.items()
        },
        "step_execution_order":
            step_execution_order,
        "parallel_step_groups":
            parallel_step_groups,
        "parallel_step_ids":
            parallel_step_ids,
        "file_execution_order":
            file_execution_order,
        "fallback_used": False,
    }


def _apply_step_dependency_safety_rules(
    *,
    workstreams: list[dict[str, Any]],
    step_dependencies: dict[str, list[str]],
    parallel_step_ids: set[str],
) -> tuple[
    dict[str, list[str]],
    set[str],
]:
    normalized_dependencies = {
        str(step_id): list(
            dict.fromkeys(
                str(value)
                for value in dependencies
                if str(value).strip()
            )
        )
        for step_id, dependencies
        in step_dependencies.items()
    }

    previous_implementation_step_id: (
        str | None
    ) = None

    implementation_categories = {
        "BACKEND",
        "DATA",
        "FRONTEND",
    }

    ordered_streams = sorted(
        workstreams,
        key=lambda item: int(
            item.get("position", 0)
        ),
    )

    for stream in ordered_streams:
        step_id = (
            f"step-{int(stream['position'])}"
        )
        category = str(
            stream.get(
                "category",
                "OTHER",
            )
        ).upper()

        normalized_dependencies.setdefault(
            step_id,
            [],
        )

        if category in implementation_categories:
            previous_implementation_step_id = (
                step_id
            )
            continue

        if (
            category == "TEST"
            and previous_implementation_step_id
            and previous_implementation_step_id
            not in normalized_dependencies[
                step_id
            ]
        ):
            normalized_dependencies[
                step_id
            ].append(
                previous_implementation_step_id
            )

    dependency_targets = {
        dependency
        for dependencies
        in normalized_dependencies.values()
        for dependency in dependencies
    }

    non_parallel_step_ids = {
        step_id
        for step_id, dependencies
        in normalized_dependencies.items()
        if dependencies
    } | dependency_targets

    normalized_parallel_step_ids = {
        step_id
        for step_id in parallel_step_ids
        if step_id
        not in non_parallel_step_ids
    }

    return (
        normalized_dependencies,
        normalized_parallel_step_ids,
    )


def _to_implementation_steps(
    *,
    workstreams: list[dict[str, Any]],
    operations_by_path: dict[str, FileOperation],
    verification_commands: list[dict[str, str]],
    step_dependencies: dict[str, list[str]],
    parallel_step_ids: set[str],
) -> list[ImplementationStep]:
    steps: list[ImplementationStep] = []

    for stream in workstreams:
        position = int(stream["position"])
        step_id = f"step-{position}"

        file_operations = [
            operations_by_path[path]
            for path in stream.get("files", [])
            if path in operations_by_path
        ]

        commands = [
            item["command"]
            for item in verification_commands
            if isinstance(item, dict)
            and item.get("command")
        ]

        risk_levels = {
            operation.risk_level
            for operation in file_operations
        }

        if "HIGH" in risk_levels:
            risk_level = "HIGH"
        elif "MEDIUM" in risk_levels:
            risk_level = "MEDIUM"
        elif "LOW" in risk_levels:
            risk_level = "LOW"
        else:
            risk_level = "UNKNOWN"

        dependencies = list(
            step_dependencies.get(
                step_id,
                [],
            )
        )

        steps.append(
            ImplementationStep(
                step_id=step_id,
                position=position,
                title=stream["title"],
                description=stream["purpose"],
                category=stream.get(
                    "category",
                    "OTHER",
                ),
                file_operations=file_operations,
                depends_on_steps=dependencies,
                can_run_in_parallel=(
                    step_id in parallel_step_ids
                ),
                verification_commands=commands,
                completion_criteria=[
                    (
                        f"{stream['title']}に含まれる"
                        "変更が実装されている。"
                    ),
                    "関連する検証が成功する。",
                ],
                risk_level=risk_level,
            )
        )

    return steps


def _build_typed_implementation_plan(
    *,
    mission: dict[str, Any],
    requirement: RequirementAnalyzerResult,
    selected_files: list[dict[str, Any]],
    workstreams: list[dict[str, Any]],
    verification_commands: list[dict[str, str]],
    risk: dict[str, Any],
    effort: dict[str, Any],
    approval_summary: str,
) -> ImplementationPlan:
    _validate_required_mutation_scope(
        selected_files=selected_files,
        requirement=requirement,
    )

    project_path = _get_project_path(
        mission["project_id"]
    )

    file_operations = [
        _to_file_operation(
            item,
            project_path=project_path,
        )
        for item in selected_files
    ]

    operations_by_path = {
        operation.path: operation
        for operation in file_operations
    }

    dependency_plan = build_dependency_plan(
        selected_files
    )

    dependency_context = (
        _build_step_dependency_context(
            workstreams=workstreams,
            dependency_plan=dependency_plan,
        )
    )

    (
        safe_step_dependencies,
        safe_parallel_step_ids,
    ) = _apply_step_dependency_safety_rules(
        workstreams=workstreams,
        step_dependencies=(
            dependency_context[
                "step_dependencies"
            ]
        ),
        parallel_step_ids=(
            dependency_context[
                "parallel_step_ids"
            ]
        ),
    )

    dependency_context[
        "step_dependencies"
    ] = safe_step_dependencies
    dependency_context[
        "parallel_step_ids"
    ] = safe_parallel_step_ids

    steps = _to_implementation_steps(
        workstreams=workstreams,
        operations_by_path=operations_by_path,
        verification_commands=verification_commands,
        step_dependencies=(
            safe_step_dependencies
        ),
        parallel_step_ids=(
            safe_parallel_step_ids
        ),
    )

    clarification_questions = (
        _build_clarification_questions(
            requirement
        )
    )

    command_values = [
        item["command"]
        for item in verification_commands
        if isinstance(item, dict)
        and item.get("command")
    ]

    success_criteria = list(
        requirement.success_criteria
    )

    if not success_criteria:
        raw_success_criteria = str(
            mission.get("success_criteria") or ""
        ).strip()

        if raw_success_criteria:
            success_criteria = [
                raw_success_criteria
            ]

    return ImplementationPlan(
        mission_id=mission["id"],
        project_id=mission["project_id"],
        project_name=mission["project_name"],
        objective=mission["objective"],
        success_criteria=success_criteria,
        requirement_contract_version=(
            requirement.contract_version
        ),
        requirement_contract=requirement,
        implementation_possible=(
            requirement.implementation_possible
        ),
        clarification_required=bool(
            clarification_questions
            or not requirement.implementation_possible
        ),
        clarification_questions=(
            clarification_questions
        ),
        selected_files=file_operations,
        steps=steps,
        execution_order=(
            dependency_context[
                "step_execution_order"
            ]
        ),
        file_execution_order=(
            dependency_context[
                "file_execution_order"
            ]
        ),
        dependency_graph=(
            dependency_plan.get(
                "graph",
                {},
            )
        ),
        dependency_cycles=(
            dependency_plan.get(
                "cycles",
                [],
            )
        ),
        parallel_groups=(
            dependency_context[
                "parallel_step_groups"
            ]
        ),
        verification_commands=command_values,
        overall_risk_level=(
            _normalize_risk_level(
                risk.get("level")
            )
        ),
        estimated_effort_level=(
            _normalize_effort_level(
                effort.get("level")
            )
        ),
        approval_summary=approval_summary,
    )


def _build_approval_summary(
    *,
    mission: dict[str, Any],
    files: list[dict[str, Any]],
    workstreams: list[dict[str, Any]],
    risk: dict[str, Any],
    effort: dict[str, Any],
) -> str:
    top_files = [
        item["path"]
        for item in files[:5]
    ]

    return (
        f"Mission「{mission['title']}」について、"
        f"{len(files)}件の変更候補と"
        f"{len(workstreams)}領域の作業計画を作成しました。"
        f"総合リスクは{risk['label']}、"
        f"概算規模は{effort['label']}です。"
        f"優先確認対象: {', '.join(top_files)}"
    )


def _recover_planning_failure(
    *,
    mission_id: int,
    error: Exception,
) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        task = connection.execute(
            """
            SELECT id
            FROM mission_tasks
            WHERE mission_id = ?
              AND task_type = 'PLANNING'
            LIMIT 1
            """,
            (mission_id,),
        ).fetchone()

        if task is None:
            return

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'READY',
                result = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    {
                        "status": "FAILED_RETRYABLE",
                        "error_type": error.__class__.__name__,
                        "error": str(error),
                    },
                    ensure_ascii=False,
                ),
                now,
                task["id"],
            ),
        )

        connection.execute(
            """
            UPDATE missions
            SET
                status = 'PLANNED',
                progress = 29,
                next_action =
                    '前回の計画生成エラーを確認し、再試行する',
                error_count = error_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                mission_id,
            ),
        )

        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="ERROR",
        event_type="MISSION_PLANNING_FAILED",
        message=(
            "Mission計画生成に失敗したため、"
            "PLANNING TaskをREADYへ復旧しました。"
        ),
        metadata={
            "error_type": error.__class__.__name__,
            "error": str(error),
            "retryable": True,
        },
    )


def _run_mission_planner_impl(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    requirements_task = next(
        (
            task
            for task in mission["tasks"]
            if task["task_type"] == "REQUIREMENTS"
        ),
        None,
    )

    analysis_task = next(
        (
            task
            for task in mission["tasks"]
            if task["task_type"] == "ANALYSIS"
        ),
        None,
    )

    planning_task = next(
        (
            task
            for task in mission["tasks"]
            if task["task_type"] == "PLANNING"
        ),
        None,
    )

    if (
        requirements_task is None
        or analysis_task is None
        or planning_task is None
    ):
        raise MissionPlannerError(
            "ANALYSISまたはPLANNING Taskがありません。"
        )

    if analysis_task["status"] != "COMPLETED":
        raise MissionPlannerError(
            "ANALYSIS Taskが完了していません。"
        )

    if not analysis_task["result"]:
        raise MissionPlannerError(
            "ANALYSIS結果が保存されていません。"
        )

    if planning_task["status"] not in {
        "READY",
        "RUNNING",
    }:
        raise MissionPlannerError(
            "PLANNING Taskは実行可能状態ではありません。"
        )

    if planning_task["status"] == "READY":
        mission = update_mission_task(
            mission_id=mission_id,
            task_id=planning_task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

        planning_task = next(
            task
            for task in mission["tasks"]
            if task["task_type"] == "PLANNING"
        )

    try:
        analysis = json.loads(
            analysis_task["result"]
        )
    except json.JSONDecodeError as error:
        raise MissionPlannerError(
            "ANALYSIS結果のJSONを読み取れません。"
        ) from error

    candidates = analysis.get("candidates", [])

    if not candidates:
        raise MissionPlannerError(
            "計画へ使用できる候補ファイルがありません。"
        )

    explicit_paths = _extract_explicit_paths(
        mission.get("objective"),
        mission.get("success_criteria"),
    )

    selected_files = _select_files(
        candidates,
        explicit_paths=explicit_paths,
    )
    workstreams = _build_workstreams(
        selected_files,
        context_candidates=candidates,
    )
    requirement = _load_requirement_contract(
        requirements_task
    )

    verification = _build_verification_commands(
        selected_files,
        requirement=requirement,
    )
    risk = _calculate_plan_risk(selected_files)
    effort = _estimate_effort(
        selected_files,
        workstreams,
    )

    requirement_payload = requirement.model_dump(
        mode="json"
    )

    plan = {
        "plan_version": "mission-planner-v0.2",
        "mission_id": mission_id,
        "project_id": mission["project_id"],
        "project_name": mission["project_name"],
        "objective": mission["objective"],
        "success_criteria": mission["success_criteria"],
        "requirement_contract_version": (
            requirement.contract_version
        ),
        "requirement_contract": requirement_payload,
        "implementation_possible": (
            requirement.implementation_possible
        ),
        "ambiguity_count": len(
            requirement.ambiguities
        ),
        "missing_information_count": len(
            requirement.missing_information
        ),
        "requirement_risk_count": len(
            requirement.risks
        ),
        "analysis_version": analysis.get(
            "analysis_version"
        ),
        "selected_file_count": len(selected_files),
        "selected_files": selected_files,
        "workstreams": workstreams,
        "execution_order": [
            stream["title"]
            for stream in workstreams
        ],
        "verification_commands": verification,
        "risk": risk,
        "effort": effort,
    }

    plan["approval_summary"] = _build_approval_summary(
        mission=mission,
        files=selected_files,
        workstreams=workstreams,
        risk=risk,
        effort=effort,
    )

    typed_plan = _build_typed_implementation_plan(
        mission=mission,
        requirement=requirement,
        selected_files=selected_files,
        workstreams=workstreams,
        verification_commands=verification,
        risk=risk,
        effort=effort,
        approval_summary=plan["approval_summary"],
    )

    plan["typed_plan"] = typed_plan.model_dump(
        mode="json"
    )
    plan["typed_plan_version"] = (
        typed_plan.plan_version
    )
    plan["dependency_plan"] = {
        "planner_version": (
            typed_plan.dependency_graph.get(
                "graph_version"
            )
        ),
        "valid": not bool(
            typed_plan.dependency_cycles
        ),
        "cycles": (
            typed_plan.dependency_cycles
        ),
        "file_execution_order": (
            typed_plan.file_execution_order
        ),
        "parallel_groups": (
            typed_plan.parallel_groups
        ),
    }

    result_text = json.dumps(
        plan,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionPlannerError(
            "生成した実装計画が保存上限を超えました。"
        )

    target_path = (
        selected_files[0]["path"]
        if selected_files
        else None
    )

    mission = update_mission_task(
        mission_id=mission_id,
        task_id=planning_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
            target_path=target_path,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="MISSION_PLANNING_COMPLETED",
        message=(
            f"候補ファイル{len(selected_files)}件、"
            f"作業領域{len(workstreams)}件の"
            "実装計画を作成しました。"
        ),
        metadata={
            "selected_file_count": len(selected_files),
            "workstream_count": len(workstreams),
            "risk": risk,
            "effort": effort,
            "requirement_contract_version": (
                requirement.contract_version
            ),
            "implementation_possible": (
                requirement.implementation_possible
            ),
            "ambiguity_count": len(
                requirement.ambiguities
            ),
            "missing_information_count": len(
                requirement.missing_information
            ),
            "requirement_risk_count": len(
                requirement.risks
            ),
            "typed_plan_version": (
                typed_plan.plan_version
            ),
            "typed_step_count": len(
                typed_plan.steps
            ),
            "clarification_required": (
                typed_plan.clarification_required
            ),
            "dependency_node_count": (
                typed_plan.dependency_graph.get(
                    "node_count",
                    0,
                )
            ),
            "dependency_edge_count": (
                typed_plan.dependency_graph.get(
                    "edge_count",
                    0,
                )
            ),
            "dependency_cycle_count": len(
                typed_plan.dependency_cycles
            ),
            "parallel_group_count": len(
                typed_plan.parallel_groups
            ),
        },
    )

    return {
        "mission": mission,
        "plan": plan,
    }


def run_mission_planner(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return _run_mission_planner_impl(mission_id)

    except Exception as error:
        _recover_planning_failure(
            mission_id=mission_id,
            error=error,
        )

        if isinstance(error, MissionPlannerError):
            raise

        raise MissionPlannerError(
            "Mission計画生成に失敗しました。"
            "PLANNING Taskを再試行可能な状態へ復旧しました。"
            f" 原因: {error}"
        ) from error
