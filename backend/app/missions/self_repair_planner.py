from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.missions.repair_policy import (
    get_repair_policy,
    normalize_failure_category,
    serialize_repair_policy,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionSelfRepairPlannerError(Exception):
    """Self Repair Plannerの処理に失敗した場合の例外。"""


ARC_ROOT = Path(__file__).resolve().parents[3]
REPAIR_PLAN_ROOT = ARC_ROOT / "data" / "repair_plans"

REPAIR_VERSION = "mission-self-repair-planner-v0.1"
MAX_TEXT_CHARS = 20000
MAX_FAILURES = 50

def _safe_relative(
    path: Path,
) -> str:
    try:
        return (
            path.relative_to(ARC_ROOT)
            .as_posix()
        )
    except ValueError:
        return path.as_posix()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in mission.get("tasks", [])
            if item.get("task_type") == task_type
        ),
        None,
    )

    if task is None:
        raise MissionSelfRepairPlannerError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _load_json_result(
    task: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    raw_result = task.get("result")

    if not raw_result:
        raise MissionSelfRepairPlannerError(
            f"{label}結果が保存されていません。"
        )

    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError as error:
        raise MissionSelfRepairPlannerError(
            f"{label}結果のJSONを読み取れません。"
        ) from error

    if not isinstance(result, dict):
        raise MissionSelfRepairPlannerError(
            f"{label}結果の形式が不正です。"
        )

    return result


def _truncate(value: Any) -> str:
    text = str(value or "")

    if len(text) <= MAX_TEXT_CHARS:
        return text

    return text[:MAX_TEXT_CHARS] + "\n...[truncated]..."


def _normalize_category(value: Any) -> str:
    return normalize_failure_category(value).value


def _extract_path_candidates(text: str) -> list[str]:
    patterns = [
        r'File\s+"([^"]+)"',
        r"(?m)^([^:\n]+\.(?:py|pyi|js|jsx|ts|tsx|json|toml|yaml|yml))"
        r":\d+(?::\d+)?",
        r"(?m)([A-Za-z0-9_./-]+\.(?:py|pyi|js|jsx|ts|tsx|json|toml|yaml|yml))",
    ]

    candidates: list[str] = []
    seen: set[str] = set()

    for pattern in patterns:
        for match in re.findall(pattern, text):
            value = str(match).strip()

            if not value:
                continue

            normalized = value.replace("\\", "/")

            if normalized.startswith(str(ARC_ROOT).replace("\\", "/")):
                try:
                    normalized = (
                        Path(normalized)
                        .resolve()
                        .relative_to(ARC_ROOT)
                        .as_posix()
                    )
                except ValueError:
                    continue

            normalized = normalized.lstrip("./")

            if (
                not normalized
                or normalized.startswith("../")
                or normalized in seen
            ):
                continue

            seen.add(normalized)
            candidates.append(normalized)

            if len(candidates) >= 30:
                return candidates

    return candidates


def _collect_failures(
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_results = verification.get("results")

    if not isinstance(raw_results, list):
        raw_results = []

    failures: list[dict[str, Any]] = []

    for index, item in enumerate(raw_results):
        if not isinstance(item, dict):
            continue

        if item.get("passed") is True:
            continue

        stdout = _truncate(item.get("stdout"))
        stderr = _truncate(item.get("stderr"))
        output = "\n".join(
            part
            for part in [
                stdout,
                stderr,
            ]
            if part
        )

        category = _normalize_category(
            item.get("failure_category")
            or item.get("category")
            or verification.get("failure_category")
        )

        explicit_suspected_files = (
            item.get("suspected_files")
        )

        if not isinstance(
            explicit_suspected_files,
            list,
        ):
            explicit_suspected_files = []

        suspected_files = _unique_strings(
            [
                *[
                    str(value)
                    for value in (
                        explicit_suspected_files
                    )
                    if str(value).strip()
                ],
                *_extract_path_candidates(
                    output
                ),
            ]
        )

        failures.append(
            {
                "index": index,
                "name": item.get("name"),
                "command": item.get("command"),
                "category": item.get("category"),
                "failure_category": category,
                "returncode": item.get("returncode"),
                "timed_out": bool(item.get("timed_out")),
                "cwd": item.get("cwd"),
                "stdout": stdout,
                "stderr": stderr,
                "suspected_files": (
                    suspected_files
                ),
            }
        )

        if len(failures) >= MAX_FAILURES:
            break

    if failures:
        return failures

    fallback_category = _normalize_category(
        verification.get("failure_category")
    )

    return [
        {
            "index": 0,
            "name": "Verification",
            "command": None,
            "category": None,
            "failure_category": fallback_category,
            "returncode": None,
            "timed_out": (
                fallback_category == "TIMEOUT"
            ),
            "cwd": None,
            "stdout": "",
            "stderr": "",
            "suspected_files": [],
        }
    ]


def _category_guidance(
    category: str,
) -> dict[str, list[str]]:
    guidance: dict[str, dict[str, list[str]]] = {
        "SYNTAX": {
            "causes": [
                "構文記号、括弧、引用符またはインデントの不整合",
                "Patch適用位置の誤り",
                "編集対象コードの文法破損",
            ],
            "strategy": [
                "エラー対象ファイルと行番号を特定する",
                "該当範囲を最小単位で修正する",
                "構文確認を先に再実行する",
            ],
            "checks": [
                "Python compileallまたは対象言語の構文確認",
                "変更差分の目視確認",
                "git diff --check",
            ],
        },
        "IMPORT": {
            "causes": [
                "Module名またはimport pathの誤り",
                "循環import",
                "依存モジュールの不足",
            ],
            "strategy": [
                "失敗したimport文と対象Moduleを特定する",
                "既存Package構造とimport規則を確認する",
                "必要最小限のimport修正案を作成する",
            ],
            "checks": [
                "対象Moduleの単体import",
                "compileall",
                "関連テスト",
            ],
        },
        "DEPENDENCY": {
            "causes": [
                "必要な実行ファイルまたはPackageが存在しない",
                "依存関係の定義漏れ",
                "実行Pathまたは作業Directoryの誤り",
            ],
            "strategy": [
                "不足しているDependency名を抽出する",
                "既存依存定義を確認する",
                "環境変更が必要な場合は自動適用せず承認対象にする",
            ],
            "checks": [
                "Dependency存在確認",
                "実行CommandのPath確認",
                "再Verification",
            ],
        },
        "PERMISSION": {
            "causes": [
                "対象ファイルまたはCommandの権限不足",
                "書込禁止領域へのアクセス",
                "実行権限の不足",
            ],
            "strategy": [
                "権限不足の対象を特定する",
                "Project内で安全な代替Pathを検討する",
                "権限変更は自動実行せず承認対象にする",
            ],
            "checks": [
                "所有者とPermission確認",
                "Project境界確認",
                "再Verification",
            ],
        },
        "LINT": {
            "causes": [
                "Lint規則違反",
                "未使用importまたは型・記法の不整合",
                "Framework固有規則への違反",
            ],
            "strategy": [
                "Lint ruleと対象行を抽出する",
                "振る舞いを変えない最小修正を設計する",
                "対象Lintと全体Lintを再実行する",
            ],
            "checks": [
                "対象ファイルLint",
                "全体Lint",
                "Build",
            ],
        },
        "TEST": {
            "causes": [
                "期待値と実装結果の不一致",
                "既存仕様の回帰",
                "Test fixtureまたは前提条件の不整合",
            ],
            "strategy": [
                "失敗Test名とAssertionを抽出する",
                "実装とTestのどちらが仕様に反するか確認する",
                "関連範囲だけを最小修正する",
            ],
            "checks": [
                "失敗Test単体実行",
                "関連Test実行",
                "全体Test実行",
            ],
        },
        "BUILD": {
            "causes": [
                "型エラーまたはCompileエラー",
                "依存関係または設定の不整合",
                "Frontend・Backend間Interfaceの不一致",
            ],
            "strategy": [
                "最初のBuild errorを優先して解析する",
                "エラー発生元と波及エラーを分離する",
                "最小修正後にBuildを再実行する",
            ],
            "checks": [
                "型確認",
                "Lint",
                "Build",
            ],
        },
        "GIT": {
            "causes": [
                "想定外ファイル変更",
                "Whitespace error",
                "未追跡ファイルまたはWorking Tree不整合",
            ],
            "strategy": [
                "git statusとgit diffを解析する",
                "Planner対象外変更を除外する",
                "想定差分だけが残る状態へ戻す",
            ],
            "checks": [
                "git diff --check",
                "git status --porcelain",
                "変更対象Manifest照合",
            ],
        },
        "TIMEOUT": {
            "causes": [
                "処理時間が上限を超過",
                "TestまたはBuildの停止",
                "外部Processまたは待機処理の長期化",
            ],
            "strategy": [
                "停止したCommandと最終出力を特定する",
                "無限ループ、待機、重い処理を調査する",
                "Timeout延長のみで解決せず原因を先に修正する",
            ],
            "checks": [
                "対象Commandの限定実行",
                "Process終了条件確認",
                "再Verification",
            ],
        },
        "COMMAND": {
            "causes": [
                "Commandが非ゼロ終了した",
                "Command引数または作業Directoryが不正",
                "分類不能な実行時エラー",
            ],
            "strategy": [
                "終了Codeと標準エラーを解析する",
                "実行条件とCommand定義を確認する",
                "原因に応じて具体的Categoryへ再分類する",
            ],
            "checks": [
                "対象Command単体実行",
                "作業Directory確認",
                "再Verification",
            ],
        },
        "UNKNOWN": {
            "causes": [
                "Verification出力だけでは原因を確定できない",
                "複数の原因が混在している可能性",
            ],
            "strategy": [
                "失敗Command、標準出力、標準エラーを再収集する",
                "最初に発生したエラーを特定する",
                "原因確定前に自動修正を行わない",
            ],
            "checks": [
                "詳細ログ取得",
                "対象Command単体実行",
                "追加解析後に再分類",
            ],
        },
    }

    return guidance.get(
        category,
        guidance["UNKNOWN"],
    )


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = str(value).strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return result


def _build_repair_plan(
    *,
    mission: dict[str, Any],
    verification: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    categories = _unique_strings(
        [
            _normalize_category(
                failure.get("failure_category")
            )
            for failure in failures
        ]
    )

    primary_category = (
        categories[0]
        if categories
        else _normalize_category(
            verification.get("failure_category")
        )
    )

    policy_rule = get_repair_policy(
        primary_category
    )
    serialized_policy = serialize_repair_policy(
        policy_rule
    )

    suspected_files = _unique_strings(
        [
            path
            for failure in failures
            for path in failure.get(
                "suspected_files",
                [],
            )
        ]
    )

    root_causes: list[str] = []
    repair_strategy: list[str] = []
    recommended_checks: list[str] = []

    for category in categories or [primary_category]:
        guidance = _category_guidance(category)
        root_causes.extend(guidance["causes"])
        repair_strategy.extend(guidance["strategy"])
        recommended_checks.extend(guidance["checks"])

    plan_id = uuid4().hex

    return {
        "repair_version": REPAIR_VERSION,
        "repair_plan_id": plan_id,
        "mission": {
            "id": mission["id"],
            "project_id": mission["project_id"],
            "project_name": mission["project_name"],
            "title": mission["title"],
            "objective": mission["objective"],
        },
        "failure_source": str(
            verification.get(
                "failure_source"
            )
            or FAILURE_SOURCE_VERIFICATION
        ),
        "failure_source_version": (
            verification.get(
                "source_version"
            )
            or verification.get(
                "verification_version"
            )
        ),
        "verification": {
            "verification_version": (
                verification.get(
                    "verification_version"
                )
            ),
            "passed": False,
            "failure_category": primary_category,
            "failure_categories": categories,
            "requested_command_count": (
                verification.get(
                    "requested_command_count"
                )
            ),
            "executed_command_count": (
                verification.get(
                    "executed_command_count"
                )
            ),
        },
        "failure_count": len(failures),
        "failures": failures,
        "suspected_files": suspected_files,
        "suspected_root_causes": _unique_strings(
            root_causes
        ),
        "repair_strategy": _unique_strings(
            repair_strategy
        ),
        "recommended_checks": _unique_strings(
            recommended_checks
        ),
        "repair_policy": serialized_policy,
        "status": "PLANNED",
        "auto_apply": False,
        "patch_generated": False,
        "patch_applied": False,
        "retry_started": False,
        "created_at": _now(),
    }


def _plan_directory(mission_id: int) -> Path:
    return REPAIR_PLAN_ROOT / f"mission-{mission_id}"


def _latest_plan_path(mission_id: int) -> Path:
    return _plan_directory(mission_id) / "repair-plan.json"


def _archive_plan_path(
    *,
    mission_id: int,
    plan_id: str,
) -> Path:
    return (
        _plan_directory(mission_id)
        / f"repair-plan-{plan_id}.json"
    )


def _load_existing_plan(
    mission_id: int,
) -> dict[str, Any] | None:
    path = _latest_plan_path(mission_id)

    if not path.exists():
        return None

    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(value, dict):
        return None

    return value


def _failure_signature(
    verification: dict[str, Any],
    failures: list[dict[str, Any]],
) -> str:
    import hashlib

    payload = {
        "verification_version": (
            verification.get("verification_version")
        ),
        "failure_category": (
            verification.get("failure_category")
        ),
        "results": [
            {
                "name": failure.get("name"),
                "command": failure.get("command"),
                "failure_category": (
                    failure.get("failure_category")
                ),
                "returncode": failure.get("returncode"),
                "timed_out": failure.get("timed_out"),
                "stdout": failure.get("stdout"),
                "stderr": failure.get("stderr"),
            }
            for failure in failures
        ],
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        f".{path.name}.{uuid4().hex}.tmp"
    )

    text = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )

    temporary.write_text(
        text + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        path,
    )


FAILURE_SOURCE_VERIFICATION = "VERIFICATION"
FAILURE_SOURCE_CODE_GENERATION = "CODE_GENERATION"
FAILURE_SOURCE_IMPLEMENTATION_PATCH = (
    "IMPLEMENTATION_PATCH"
)


def _load_optional_task_result(
    task: dict[str, Any],
) -> dict[str, Any] | None:
    raw_result = task.get("result")

    if not raw_result:
        return None

    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError as error:
        raise MissionSelfRepairPlannerError(
            "Task result JSON is invalid."
        ) from error

    if not isinstance(result, dict):
        raise MissionSelfRepairPlannerError(
            "Task result must be an object."
        )

    return result


def _patch_failure_payload(
    *,
    implementation_result: dict[str, Any],
) -> dict[str, Any] | None:
    failure = implementation_result.get(
        "last_patch_failure"
    )

    if not isinstance(failure, dict):
        return None

    category = _normalize_category(
        failure.get("failure_category")
    )

    classification = failure.get(
        "failure_classification"
    )

    if not isinstance(classification, dict):
        classification = {}

    stage = str(
        failure.get("stage")
        or "PATCH"
    ).strip()

    error_text = str(
        failure.get("error")
        or ""
    )

    suspected_files: list[str] = []

    step_execution = implementation_result.get(
        "step_execution"
    )

    if isinstance(step_execution, dict):
        current_step_id = step_execution.get(
            "current_step_id"
        )
        results = step_execution.get("results")

        if (
            current_step_id
            and isinstance(results, dict)
        ):
            current_result = results.get(
                str(current_step_id)
            )

            if isinstance(current_result, dict):
                metadata = current_result.get(
                    "metadata"
                )

                if isinstance(metadata, dict):
                    for key in (
                        "changed_files",
                        "target_files",
                        "suspected_files",
                    ):
                        values = metadata.get(key)

                        if isinstance(values, list):
                            suspected_files.extend(
                                str(value)
                                for value in values
                                if str(value).strip()
                            )

    return {
        "failure_source": (
            FAILURE_SOURCE_IMPLEMENTATION_PATCH
        ),
        "source_version": (
            "implementation-patch-failure-v0.1"
        ),
        "passed": False,
        "failure_category": category,
        "results": [
            {
                "passed": False,
                "name": stage,
                "command": None,
                "category": "PATCH",
                "failure_category": category,
                "returncode": None,
                "timed_out": (
                    category == "TIMEOUT"
                ),
                "cwd": None,
                "stdout": "",
                "stderr": error_text,
                "suspected_files": (
                    _unique_strings(
                        suspected_files
                    )
                ),
                "failure_classification": (
                    classification
                ),
                "failed_at": failure.get(
                    "failed_at"
                ),
            }
        ],
    }


def _resolve_repair_failure_source(
    *,
    mission: dict[str, Any],
    implementation_task: dict[str, Any],
    verification_task: dict[str, Any],
) -> dict[str, Any]:
    implementation_result = (
        _load_optional_task_result(
            implementation_task
        )
    )

    if isinstance(
        implementation_result,
        dict,
    ):
        patch_payload = _patch_failure_payload(
            implementation_result=(
                implementation_result
            )
        )

        if patch_payload is not None:
            return patch_payload

    verification = _load_json_result(
        verification_task,
        label="VERIFICATION",
    )

    if verification.get("passed") is True:
        raise MissionSelfRepairPlannerError(
            "Successful Verification cannot "
            "be used as a repair source."
        )

    if verification.get("passed") is not False:
        raise MissionSelfRepairPlannerError(
            "Verification failure state "
            "could not be confirmed."
        )

    return {
        **verification,
        "failure_source": (
            FAILURE_SOURCE_VERIFICATION
        ),
    }


def run_self_repair_planner(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    if mission["status"] in {
        "COMPLETED",
        "CANCELLED",
    }:
        raise MissionSelfRepairPlannerError(
            "完了または中止済みMissionでは"
            "Repair Planを生成できません。"
        )

    if implementation_task["status"] not in {
        "READY",
        "PENDING",
        "RUNNING",
    }:
        raise MissionSelfRepairPlannerError(
            "IMPLEMENTATION Taskが"
            "修復計画を作成可能な状態ではありません。"
        )

    if verification_task["status"] not in {
        "PENDING",
        "FAILED",
    }:
        raise MissionSelfRepairPlannerError(
            "Verification失敗後に"
            "Repair Planを生成してください。"
        )

    failure_source = (
        _resolve_repair_failure_source(
            mission=mission,
            implementation_task=(
                implementation_task
            ),
            verification_task=(
                verification_task
            ),
        )
    )

    failures = _collect_failures(
        failure_source
    )

    signature = _failure_signature(
        failure_source,
        failures,
    )

    existing_plan = _load_existing_plan(
        mission_id
    )

    if (
        existing_plan is not None
        and existing_plan.get(
            "verification_failure_signature"
        )
        == signature
    ):
        return {
            "mission": mission,
            "repair_plan": existing_plan,
            "storage": {
                "latest_path": (
                    _safe_relative(
                        _latest_plan_path(
                            mission_id
                        )
                    )
                ),
                "duplicate": True,
            },
        }

    repair_plan = _build_repair_plan(
        mission=mission,
        verification=failure_source,
        failures=failures,
    )

    repair_plan[
        "verification_failure_signature"
    ] = signature

    latest_path = _latest_plan_path(
        mission_id
    )
    archive_path = _archive_plan_path(
        mission_id=mission_id,
        plan_id=repair_plan[
            "repair_plan_id"
        ],
    )

    _write_json_atomic(
        archive_path,
        repair_plan,
    )
    _write_json_atomic(
        latest_path,
        repair_plan,
    )

    add_mission_log(
        mission_id=mission_id,
        level="WARNING",
        event_type=(
            "MISSION_REPAIR_PLAN_CREATED"
        ),
        message=(
            "Verification失敗結果を解析し、"
            "自動適用を伴わないRepair Planを"
            "生成しました。"
        ),
        metadata={
            "repair_version": REPAIR_VERSION,
            "repair_plan_id": (
                repair_plan["repair_plan_id"]
            ),
            "failure_source": (
                repair_plan.get(
                    "failure_source"
                )
            ),
            "failure_category": (
                repair_plan["verification"][
                    "failure_category"
                ]
            ),
            "failure_count": (
                repair_plan["failure_count"]
            ),
            "repair_action": (
                repair_plan["repair_policy"][
                    "repair_action"
                ]
            ),
            "resume_stage": (
                repair_plan["repair_policy"][
                    "resume_stage"
                ]
            ),
            "max_retries": (
                repair_plan["repair_policy"][
                    "max_retries"
                ]
            ),
            "requires_approval": (
                repair_plan["repair_policy"][
                    "requires_approval"
                ]
            ),
            "suspected_file_count": len(
                repair_plan["suspected_files"]
            ),
            "status": "PLANNED",
            "auto_apply": False,
            "latest_path": (
                _safe_relative(
                    latest_path
                )
            ),
        },
    )

    return {
        "mission": get_mission(mission_id),
        "repair_plan": repair_plan,
        "storage": {
            "latest_path": (
                _safe_relative(
                    latest_path
                )
            ),
            "archive_path": (
                _safe_relative(
                    archive_path
                )
            ),
            "duplicate": False,
        },
    }


def run_self_repair_planner_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_self_repair_planner(
            mission_id
        )
    except (
        MissionSelfRepairPlannerError,
        MissionError,
    ):
        raise
