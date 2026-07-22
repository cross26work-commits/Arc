from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.missions.repair_context_builder import (
    REPAIR_PLAN_ROOT,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairExecutionPolicyError(Exception):
    """Repair実行方針の評価失敗時に使用する例外。"""


REPAIR_EXECUTION_POLICY_VERSION = (
    "mission-repair-execution-policy-v0.1"
)

RISK_LEVELS = (
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
)

DECISION_AUTO_APPROVED = "AUTO_APPROVED"
DECISION_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
DECISION_BLOCKED = "BLOCKED"

MAX_POLICY_HISTORY = 100
MAX_AUTO_FILES = 3
MAX_AUTO_CHANGED_LINES = 120

PROTECTED_PATH_PATTERNS = (
    r"(^|/)\.env($|\.)",
    r"(^|/)secrets?(/|$)",
    r"(^|/)credentials?(/|$)",
    r"(^|/)auth(/|$)",
    r"(^|/)security(/|$)",
    r"(^|/)migrations?(/|$)",
    r"(^|/)database(/|$)",
    r"(^|/)payment(s)?(/|$)",
    r"(^|/)billing(/|$)",
    r"(^|/)production(/|$)",
    r"(^|/)deploy(ment)?(/|$)",
    r"(^|/)docker-compose",
    r"(^|/)Dockerfile$",
    r"(^|/)pyproject\.toml$",
    r"(^|/)requirements.*\.txt$",
    r"(^|/)package-lock\.json$",
    r"(^|/)pnpm-lock\.yaml$",
    r"(^|/)yarn\.lock$",
)

CRITICAL_COMMAND_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\bsudo\b",
    r"\bchmod\s+777\b",
    r"\bchown\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-zA-Z]*f",
    r"\bdrop\s+database\b",
    r"\bdrop\s+table\b",
    r"\btruncate\s+table\b",
    r"\bcurl\b.*\|\s*(ba)?sh\b",
    r"\bwget\b.*\|\s*(ba)?sh\b",
)

HIGH_COMMAND_PATTERNS = (
    r"\bpip\s+install\b",
    r"\bnpm\s+install\b",
    r"\bpnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\bbrew\s+install\b",
    r"\bdocker\b",
    r"\bkubectl\b",
    r"\bterraform\b",
    r"\bgit\s+push\b",
    r"\bgit\s+commit\b",
    r"\balembic\b",
    r"\bmigrate\b",
)

SENSITIVE_TEXT_PATTERNS = (
    r"api[_-]?key",
    r"access[_-]?token",
    r"secret[_-]?key",
    r"private[_-]?key",
    r"password",
    r"authorization",
    r"bearer\s+[a-z0-9._-]+",
)

SAFE_FILE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".css",
    ".scss",
    ".html",
}


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _sha256_json(
    value: dict[str, Any],
) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def _mission_directory(
    mission_id: int,
) -> Path:
    return (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
    )


def _load_json(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(value, dict):
        return None

    return value


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def _collect_strings(
    value: Any,
) -> list[str]:
    strings: list[str] = []

    if isinstance(value, str):
        strings.append(value)

    elif isinstance(value, dict):
        for key, item in value.items():
            strings.append(str(key))
            strings.extend(
                _collect_strings(item)
            )

    elif isinstance(value, list):
        for item in value:
            strings.extend(
                _collect_strings(item)
            )

    return strings


def _extract_candidate_paths(
    value: Any,
) -> list[str]:
    results: set[str] = set()

    path_keys = {
        "path",
        "file",
        "filename",
        "relative_path",
        "target_path",
        "source_path",
    }

    def visit(
        node: Any,
        parent_key: str | None = None,
    ) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                normalized = str(key).lower()

                if (
                    normalized in path_keys
                    and isinstance(item, str)
                ):
                    results.add(
                        item.strip()
                    )

                visit(
                    item,
                    normalized,
                )

        elif isinstance(node, list):
            for item in node:
                visit(
                    item,
                    parent_key,
                )

        elif (
            isinstance(node, str)
            and parent_key in path_keys
        ):
            results.add(
                node.strip()
            )

    visit(value)

    return sorted(
        path
        for path in results
        if path
    )


def _extract_commands(
    value: Any,
) -> list[str]:
    results: set[str] = set()

    command_keys = {
        "command",
        "commands",
        "cmd",
        "shell",
        "verification_command",
    }

    def visit(
        node: Any,
        parent_key: str | None = None,
    ) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                normalized = str(key).lower()

                visit(
                    item,
                    normalized,
                )

        elif isinstance(node, list):
            for item in node:
                visit(
                    item,
                    parent_key,
                )

        elif (
            isinstance(node, str)
            and parent_key in command_keys
        ):
            results.add(
                node.strip()
            )

    visit(value)

    return sorted(
        command
        for command in results
        if command
    )


def _estimate_changed_lines(
    value: Any,
) -> int:
    total = 0

    line_count_keys = {
        "changed_lines",
        "line_count",
        "added_lines",
        "removed_lines",
        "additions",
        "deletions",
    }

    def visit(
        node: Any,
    ) -> None:
        nonlocal total

        if isinstance(node, dict):
            for key, item in node.items():
                normalized = str(key).lower()

                if (
                    normalized in line_count_keys
                    and isinstance(item, int)
                    and not isinstance(item, bool)
                    and item > 0
                ):
                    total += item
                else:
                    visit(item)

        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)

    if total > 0:
        return total

    strings = _collect_strings(value)

    for text in strings:
        if (
            text.startswith("--- ")
            or text.startswith("+++ ")
        ):
            continue

        if text.startswith("+") or text.startswith("-"):
            total += 1

    return total


def _matches_any(
    text: str,
    patterns: tuple[str, ...],
) -> list[str]:
    matches = []

    for pattern in patterns:
        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            matches.append(pattern)

    return matches


def _is_protected_path(
    path: str,
) -> bool:
    normalized = path.replace(
        "\\",
        "/",
    )

    return bool(
        _matches_any(
            normalized,
            PROTECTED_PATH_PATTERNS,
        )
    )


def _contains_path_escape(
    path: str,
) -> bool:
    normalized = path.replace(
        "\\",
        "/",
    )

    parts = [
        part
        for part in normalized.split("/")
        if part not in {
            "",
            ".",
        }
    ]

    return (
        path.startswith("/")
        or ".." in parts
    )


def _evaluate_risk(
    *,
    draft: dict[str, Any],
) -> dict[str, Any]:
    paths = _extract_candidate_paths(
        draft
    )

    commands = _extract_commands(
        draft
    )

    changed_lines = (
        _estimate_changed_lines(
            draft
        )
    )

    all_text = "\n".join(
        _collect_strings(draft)
    )

    reasons: list[str] = []
    controls: list[str] = []

    risk_score = 0
    critical = False

    unsafe_paths = [
        path
        for path in paths
        if _contains_path_escape(path)
    ]

    protected_paths = [
        path
        for path in paths
        if _is_protected_path(path)
    ]

    unsupported_extensions = [
        path
        for path in paths
        if (
            Path(path).suffix
            and Path(path).suffix.lower()
            not in SAFE_FILE_EXTENSIONS
        )
    ]

    critical_commands = []

    for command in commands:
        if _matches_any(
            command,
            CRITICAL_COMMAND_PATTERNS,
        ):
            critical_commands.append(
                command
            )

    high_commands = []

    for command in commands:
        if _matches_any(
            command,
            HIGH_COMMAND_PATTERNS,
        ):
            high_commands.append(
                command
            )

    sensitive_matches = (
        _matches_any(
            all_text,
            SENSITIVE_TEXT_PATTERNS,
        )
    )

    if unsafe_paths:
        critical = True
        risk_score += 100
        reasons.append(
            "プロジェクト外へ到達可能なPathを含みます。"
        )

    if critical_commands:
        critical = True
        risk_score += 100
        reasons.append(
            "破壊的または重大なShell Commandを含みます。"
        )

    if protected_paths:
        risk_score += 50
        reasons.append(
            "保護対象ファイルまたはディレクトリを変更します。"
        )

    if sensitive_matches:
        risk_score += 45
        reasons.append(
            "認証情報・秘密情報に関係する可能性があります。"
        )

    if high_commands:
        risk_score += 35
        reasons.append(
            "依存関係・Git・Infrastructure操作を含みます。"
        )

    if len(paths) > MAX_AUTO_FILES:
        risk_score += 25
        reasons.append(
            (
                "自動承認可能な変更ファイル数を"
                "超えています。"
            )
        )

    if changed_lines > MAX_AUTO_CHANGED_LINES:
        risk_score += 20
        reasons.append(
            (
                "自動承認可能な変更行数を"
                "超えています。"
            )
        )

    if unsupported_extensions:
        risk_score += 15
        reasons.append(
            "通常のSource修復対象外の拡張子を含みます。"
        )

    if not paths:
        risk_score += 20
        reasons.append(
            "変更対象ファイルを確定できません。"
        )

    if not commands:
        controls.append(
            "Verification Commandが未検出です。"
        )

    controls.extend(
        [
            "Patch Checkを必須とします。",
            "Verificationを必須とします。",
            "Rollback情報を保持します。",
            "auto_apply_overrideは禁止します。",
        ]
    )

    if critical:
        risk_level = "CRITICAL"
        decision = DECISION_BLOCKED
        auto_approved = False

    elif risk_score >= 60:
        risk_level = "HIGH"
        decision = DECISION_APPROVAL_REQUIRED
        auto_approved = False

    elif risk_score >= 25:
        risk_level = "MEDIUM"
        decision = DECISION_APPROVAL_REQUIRED
        auto_approved = False

    else:
        risk_level = "LOW"
        decision = DECISION_AUTO_APPROVED
        auto_approved = True

    if not reasons:
        reasons.append(
            "限定されたSource変更で重大な危険要素は未検出です。"
        )

    return {
        "risk_level": risk_level,
        "risk_score": risk_score,
        "decision": decision,
        "auto_approved": auto_approved,
        "file_count": len(paths),
        "changed_lines_estimate": changed_lines,
        "target_paths": paths,
        "commands": commands,
        "unsafe_paths": unsafe_paths,
        "protected_paths": protected_paths,
        "unsupported_extensions": unsupported_extensions,
        "critical_commands": critical_commands,
        "high_risk_commands": high_commands,
        "sensitive_pattern_count": len(
            sensitive_matches
        ),
        "reasons": reasons,
        "required_controls": controls,
    }


def _load_policy_history(
    mission_id: int,
) -> list[dict[str, Any]]:
    data = _load_json(
        _mission_directory(mission_id)
        / "repair-execution-policy-history.json"
    )

    if not isinstance(data, dict):
        return []

    history = data.get("evaluations")

    if not isinstance(history, list):
        return []

    return [
        item
        for item in history
        if isinstance(item, dict)
    ][-MAX_POLICY_HISTORY:]


def _save_policy_history(
    *,
    mission_id: int,
    evaluation: dict[str, Any],
) -> Path:
    path = (
        _mission_directory(mission_id)
        / "repair-execution-policy-history.json"
    )

    history = _load_policy_history(
        mission_id
    )

    history.append(evaluation)

    history = history[
        -MAX_POLICY_HISTORY:
    ]

    payload = {
        "policy_version": (
            REPAIR_EXECUTION_POLICY_VERSION
        ),
        "mission_id": mission_id,
        "updated_at": _now(),
        "latest_evaluation": evaluation,
        "evaluations": history,
    }

    _write_json_atomic(
        path,
        payload,
    )

    return path


def evaluate_repair_execution_policy(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(
        mission_id
    )

    mission_dir = _mission_directory(
        mission_id
    )

    request = _load_json(
        mission_dir
        / "repair-request.json"
    )

    context = _load_json(
        mission_dir
        / "repair-context.json"
    )

    draft = _load_json(
        mission_dir
        / "repair-edit-draft.json"
    )

    if request is None:
        raise MissionRepairExecutionPolicyError(
            "Repair Requestが存在しません。"
        )

    if context is None:
        raise MissionRepairExecutionPolicyError(
            "Repair Contextが存在しません。"
        )

    if draft is None:
        raise MissionRepairExecutionPolicyError(
            "Repair Edit Draftが存在しません。"
        )

    draft_status = draft.get("status")

    if draft_status != "EDIT_READY":
        raise MissionRepairExecutionPolicyError(
            (
                "Execution Policyを評価できる"
                "Edit Draft状態ではありません。"
                f" status={draft_status}"
            )
        )

    result = _evaluate_risk(
        draft=draft
    )

    created_at = _now()

    evaluation_seed = {
        "mission_id": mission_id,
        "created_at": created_at,
        "draft_id": draft.get(
            "draft_id"
        ),
        "result": result,
    }

    evaluation = {
        "evaluation_id": (
            "repair-policy-"
            + _sha256_json(
                evaluation_seed
            )[:16]
        ),
        "policy_version": (
            REPAIR_EXECUTION_POLICY_VERSION
        ),
        "mission_id": mission_id,
        "created_at": created_at,
        "request_id": request.get(
            "request_id"
        ),
        "context_id": context.get(
            "context_id"
        ),
        "draft_id": draft.get(
            "draft_id"
        ),
        **result,
        "execution_policy": {
            "may_auto_continue": (
                result["decision"]
                == DECISION_AUTO_APPROVED
            ),
            "requires_explicit_approval": (
                result["decision"]
                == DECISION_APPROVAL_REQUIRED
            ),
            "execution_blocked": (
                result["decision"]
                == DECISION_BLOCKED
            ),
            "patch_check_required": True,
            "verification_required": True,
            "rollback_required": True,
            "auto_apply_override": False,
        },
    }

    history_path = _save_policy_history(
        mission_id=mission_id,
        evaluation=evaluation,
    )

    event_type = {
        DECISION_AUTO_APPROVED: (
            "MISSION_REPAIR_POLICY_AUTO_APPROVED"
        ),
        DECISION_APPROVAL_REQUIRED: (
            "MISSION_REPAIR_POLICY_APPROVAL_REQUIRED"
        ),
        DECISION_BLOCKED: (
            "MISSION_REPAIR_POLICY_BLOCKED"
        ),
    }[result["decision"]]

    log_level = (
        "INFO"
        if result["decision"]
        == DECISION_AUTO_APPROVED
        else "WARNING"
    )

    add_mission_log(
        mission_id=mission_id,
        level=log_level,
        event_type=event_type,
        message=(
            "Repair Execution Policyを評価しました。"
            f" risk={result['risk_level']}"
            f" decision={result['decision']}"
        ),
        metadata={
            "policy_version": (
                REPAIR_EXECUTION_POLICY_VERSION
            ),
            "evaluation_id": evaluation[
                "evaluation_id"
            ],
            "draft_id": draft.get(
                "draft_id"
            ),
            "risk_level": result[
                "risk_level"
            ],
            "risk_score": result[
                "risk_score"
            ],
            "decision": result[
                "decision"
            ],
            "auto_approved": result[
                "auto_approved"
            ],
            "auto_apply_override": False,
        },
    )

    return {
        "mission": mission,
        **evaluation,
        "history_path": str(
            history_path
        ),
    }


def evaluate_repair_execution_policy_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return evaluate_repair_execution_policy(
            mission_id
        )
    except (
        MissionRepairExecutionPolicyError,
        MissionError,
    ):
        raise
