from __future__ import annotations

from typing import Any

from app.code_context.builder import (
    CodeContextError,
    get_code_context_safe,
)


class CodeContextQualityError(Exception):
    """Code Context Quality Gate失敗。"""


QUALITY_GATE_VERSION = (
    "mission-code-context-quality-v0.1"
)

MIN_INCLUDED_RATIO = 0.80
MAX_ANALYSIS_ERROR_RATIO = 0.20
MAX_DEPENDENCY_ERROR_RATIO = 0.20


def _ratio(
    numerator: int,
    denominator: int,
) -> float:
    if denominator <= 0:
        return 0.0

    return round(
        numerator / denominator,
        4,
    )


def _check(
    *,
    name: str,
    passed: bool,
    severity: str,
    message: str,
    actual: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "severity": severity,
        "message": message,
        "actual": actual,
        "expected": expected,
    }


def evaluate_code_context(
    context: dict[str, Any],
) -> dict[str, Any]:
    files = context.get("files")

    if not isinstance(files, list):
        files = []

    summary = context.get("summary")

    if not isinstance(summary, dict):
        summary = {}

    mission = context.get("mission")

    if not isinstance(mission, dict):
        mission = {}

    limits = context.get("limits")

    if not isinstance(limits, dict):
        limits = {}

    candidate_count = int(
        summary.get(
            "candidate_file_count",
            len(files),
        )
        or 0
    )

    included_count = int(
        summary.get(
            "included_file_count",
            0,
        )
        or 0
    )

    analysis_error_count = int(
        summary.get(
            "analysis_error_count",
            0,
        )
        or 0
    )

    dependency_error_count = int(
        summary.get(
            "dependency_error_count",
            0,
        )
        or 0
    )

    included_total_bytes = int(
        summary.get(
            "included_total_bytes",
            0,
        )
        or 0
    )

    maximum_total_bytes = int(
        limits.get(
            "maximum_total_bytes",
            0,
        )
        or 0
    )

    included_ratio = _ratio(
        included_count,
        candidate_count,
    )

    analysis_error_ratio = _ratio(
        analysis_error_count,
        candidate_count,
    )

    dependency_error_ratio = _ratio(
        dependency_error_count,
        candidate_count,
    )

    missing_sha256: list[str] = []
    missing_content: list[str] = []
    missing_static_analysis: list[str] = []
    missing_dependency_data: list[str] = []

    for item in files:
        if not isinstance(item, dict):
            continue

        path = str(
            item.get("relative_path")
            or "<unknown>"
        )

        source = item.get("source")

        if not isinstance(source, dict):
            source = {}

        static_analysis = item.get(
            "static_analysis"
        )

        if not isinstance(
            static_analysis,
            dict,
        ):
            static_analysis = {}

        dependency = item.get("dependency")

        if not isinstance(dependency, dict):
            dependency = {}

        if not source.get("sha256"):
            missing_sha256.append(path)

        if (
            source.get("included") is not True
            or not isinstance(
                source.get("content"),
                str,
            )
        ):
            missing_content.append(path)

        has_static_information = any(
            key in static_analysis
            for key in (
                "role",
                "language",
                "metrics",
                "imports",
                "functions",
                "classes",
                "routes",
            )
        )

        if not has_static_information:
            missing_static_analysis.append(
                path
            )

        has_dependency_information = any(
            key in dependency
            for key in (
                "summary",
                "direct_dependencies",
                "direct_dependents",
                "affected_files",
                "risk",
            )
        )

        if not has_dependency_information:
            missing_dependency_data.append(
                path
            )

    objective = mission.get("objective")

    checks = [
        _check(
            name="context_version",
            passed=(
                context.get("context_version")
                == "mission-code-context-v0.1"
            ),
            severity="critical",
            message=(
                "対応するContext versionであること。"
            ),
            actual=context.get(
                "context_version"
            ),
            expected=(
                "mission-code-context-v0.1"
            ),
        ),
        _check(
            name="context_sha256",
            passed=(
                isinstance(
                    context.get(
                        "context_sha256"
                    ),
                    str,
                )
                and len(
                    context.get(
                        "context_sha256",
                    )
                )
                == 64
            ),
            severity="critical",
            message=(
                "Context全体のSHA-256が"
                "存在すること。"
            ),
            actual=context.get(
                "context_sha256"
            ),
            expected="64-character SHA-256",
        ),
        _check(
            name="mission_objective",
            passed=(
                isinstance(objective, str)
                and bool(objective.strip())
            ),
            severity="critical",
            message=(
                "Mission目的がContext内に"
                "保持されていること。"
            ),
            actual=objective,
            expected="non-empty objective",
        ),
        _check(
            name="candidate_files",
            passed=candidate_count > 0,
            severity="critical",
            message=(
                "コード候補ファイルが"
                "1件以上あること。"
            ),
            actual=candidate_count,
            expected=">= 1",
        ),
        _check(
            name="included_ratio",
            passed=(
                included_ratio
                >= MIN_INCLUDED_RATIO
            ),
            severity="critical",
            message=(
                "候補ファイルの80%以上で"
                "本文取得できること。"
            ),
            actual=included_ratio,
            expected=(
                f">= {MIN_INCLUDED_RATIO}"
            ),
        ),
        _check(
            name="analysis_error_ratio",
            passed=(
                analysis_error_ratio
                <= MAX_ANALYSIS_ERROR_RATIO
            ),
            severity="critical",
            message=(
                "静的解析エラー率が"
                "20%以下であること。"
            ),
            actual=analysis_error_ratio,
            expected=(
                f"<= {MAX_ANALYSIS_ERROR_RATIO}"
            ),
        ),
        _check(
            name="dependency_error_ratio",
            passed=(
                dependency_error_ratio
                <= MAX_DEPENDENCY_ERROR_RATIO
            ),
            severity="critical",
            message=(
                "依存関係解析エラー率が"
                "20%以下であること。"
            ),
            actual=dependency_error_ratio,
            expected=(
                f"<= {MAX_DEPENDENCY_ERROR_RATIO}"
            ),
        ),
        _check(
            name="total_size_limit",
            passed=(
                maximum_total_bytes <= 0
                or included_total_bytes
                <= maximum_total_bytes
            ),
            severity="critical",
            message=(
                "Context本文が設定された"
                "総容量制限内であること。"
            ),
            actual=included_total_bytes,
            expected=(
                f"<= {maximum_total_bytes}"
            ),
        ),
        _check(
            name="source_sha256",
            passed=not missing_sha256,
            severity="critical",
            message=(
                "全取得ファイルにSHA-256が"
                "存在すること。"
            ),
            actual=missing_sha256,
            expected=[],
        ),
        _check(
            name="source_content",
            passed=not missing_content,
            severity="critical",
            message=(
                "全対象ファイルの本文を"
                "利用できること。"
            ),
            actual=missing_content,
            expected=[],
        ),
        _check(
            name="static_analysis_data",
            passed=(
                not missing_static_analysis
            ),
            severity="warning",
            message=(
                "全対象ファイルに静的解析情報が"
                "存在すること。"
            ),
            actual=missing_static_analysis,
            expected=[],
        ),
        _check(
            name="dependency_data",
            passed=(
                not missing_dependency_data
            ),
            severity="warning",
            message=(
                "全対象ファイルに依存関係情報が"
                "存在すること。"
            ),
            actual=missing_dependency_data,
            expected=[],
        ),
    ]

    failed_critical = [
        item
        for item in checks
        if (
            item["severity"] == "critical"
            and item["passed"] is False
        )
    ]

    failed_warning = [
        item
        for item in checks
        if (
            item["severity"] == "warning"
            and item["passed"] is False
        )
    ]

    passed = not failed_critical

    if passed and not failed_warning:
        quality_level = "READY"
    elif passed:
        quality_level = "READY_WITH_WARNINGS"
    else:
        quality_level = "BLOCKED"

    score = round(
        (
            sum(
                1
                for item in checks
                if item["passed"]
            )
            / len(checks)
        )
        * 100
    )

    return {
        "quality_gate_version": (
            QUALITY_GATE_VERSION
        ),
        "passed": passed,
        "quality_level": quality_level,
        "score": score,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(
                1
                for item in checks
                if item["passed"]
            ),
            "failed_critical_count": len(
                failed_critical
            ),
            "failed_warning_count": len(
                failed_warning
            ),
            "candidate_file_count": (
                candidate_count
            ),
            "included_file_count": (
                included_count
            ),
            "included_ratio": included_ratio,
            "analysis_error_ratio": (
                analysis_error_ratio
            ),
            "dependency_error_ratio": (
                dependency_error_ratio
            ),
        },
        "checks": checks,
        "blocking_reasons": [
            item["message"]
            for item in failed_critical
        ],
        "warnings": [
            item["message"]
            for item in failed_warning
        ],
        "next_stage": (
            "CODE_GENERATION"
            if passed
            else "CONTEXT_REBUILD_REQUIRED"
        ),
    }


def evaluate_mission_code_context(
    mission_id: int,
) -> dict[str, Any]:
    try:
        context = get_code_context_safe(
            mission_id
        )
    except CodeContextError as error:
        raise CodeContextQualityError(
            str(error)
        ) from error

    result = evaluate_code_context(context)

    return {
        "mission_id": mission_id,
        "context_sha256": context.get(
            "context_sha256"
        ),
        **result,
    }


def evaluate_mission_code_context_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return evaluate_mission_code_context(
            mission_id
        )
    except CodeContextQualityError:
        raise
    except Exception as error:
        raise CodeContextQualityError(
            "Context Quality Gate実行に"
            f"失敗しました: {error}"
        ) from error
