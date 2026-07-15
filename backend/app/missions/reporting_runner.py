from __future__ import annotations

import json
from typing import Any

from app.missions.models import MissionTaskUpdate
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
    update_mission_task,
)


class MissionReportingError(Exception):
    """Reporting Runnerの処理に失敗した場合の例外。"""


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in mission["tasks"]
            if item["task_type"] == task_type
        ),
        None,
    )

    if task is None:
        raise MissionReportingError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _load_result(
    task: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    raw = task.get("result")

    if not raw:
        raise MissionReportingError(
            f"{label}結果が保存されていません。"
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MissionReportingError(
            f"{label}結果のJSONを読み取れません。"
        ) from error

    if not isinstance(result, dict):
        raise MissionReportingError(
            f"{label}結果の形式が不正です。"
        )

    return result


def _collect_verification_summary(
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    results = verification.get("results")

    if not isinstance(results, list):
        return []

    summary: list[dict[str, Any]] = []

    for item in results:
        if not isinstance(item, dict):
            continue

        summary.append(
            {
                "name": item.get("name"),
                "category": item.get("category"),
                "passed": item.get("passed"),
                "failure_category": item.get(
                    "failure_category"
                ),
                "cwd": item.get("cwd"),
            }
        )

    return summary


def _build_human_summary(
    *,
    mission: dict[str, Any],
    implementation: dict[str, Any],
    verification: dict[str, Any],
    commit: dict[str, Any],
) -> str:
    changed_files = commit.get(
        "changed_files",
        [],
    )

    lines = [
        f"Mission「{mission['title']}」を完了しました。",
        "",
        f"目的: {mission['objective']}",
        f"Project: {mission['project_name']}",
        f"変更ファイル数: {len(changed_files)}",
    ]

    if changed_files:
        lines.append("変更ファイル:")

        for path in changed_files:
            lines.append(f"- {path}")

    lines.extend(
        [
            "",
            "Verification: PASS",
            (
                "Commit: "
                f"{commit.get('commit_hash', '')}"
            ),
            (
                "Branch: "
                f"{commit.get('branch', '')}"
            ),
            (
                "Commit Message: "
                f"{commit.get('commit_subject', '')}"
            ),
        ]
    )

    risk = implementation.get("risk")

    if isinstance(risk, dict):
        lines.extend(
            [
                "",
                (
                    "計画時Risk: "
                    f"{risk.get('label') or risk.get('level')}"
                ),
                (
                    "Risk理由: "
                    f"{risk.get('reason', '')}"
                ),
            ]
        )

    return "\n".join(lines)


def run_mission_reporting(
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
    reporting_task = _task_by_type(
        mission,
        "REPORTING",
    )

    if implementation_task["status"] != "COMPLETED":
        raise MissionReportingError(
            "IMPLEMENTATION Taskが完了していません。"
        )

    if verification_task["status"] != "COMPLETED":
        raise MissionReportingError(
            "VERIFICATION Taskが完了していません。"
        )

    if reporting_task["status"] not in {
        "PENDING",
        "READY",
        "RUNNING",
    }:
        raise MissionReportingError(
            "REPORTING Taskは実行可能状態ではありません。"
        )

    implementation = _load_result(
        implementation_task,
        label="IMPLEMENTATION",
    )

    verification = _load_result(
        verification_task,
        label="VERIFICATION",
    )

    if implementation.get("mode") != "COMMITTED":
        raise MissionReportingError(
            "Commit完了後にReportingを実行してください。"
        )

    if verification.get("passed") is not True:
        raise MissionReportingError(
            "Verificationが成功していません。"
        )

    commit = implementation.get("commit")

    if not isinstance(commit, dict):
        raise MissionReportingError(
            "Commit情報が保存されていません。"
        )

    if commit.get("committed") is not True:
        raise MissionReportingError(
            "Commit成功状態ではありません。"
        )

    verification_summary = (
        _collect_verification_summary(
            verification
        )
    )

    report = {
        "reporting_version": (
            "mission-reporting-v0.1"
        ),
        "mission": {
            "id": mission["id"],
            "title": mission["title"],
            "objective": mission["objective"],
            "success_criteria": (
                mission["success_criteria"]
            ),
            "project_id": mission["project_id"],
            "project_name": (
                mission["project_name"]
            ),
        },
        "implementation": {
            "mode": implementation.get("mode"),
            "implementation_version": (
                implementation.get(
                    "implementation_version"
                )
            ),
            "files_modified": (
                implementation.get(
                    "files_modified"
                )
            ),
            "modified_files": (
                implementation.get(
                    "modified_files",
                    [],
                )
            ),
            "risk": implementation.get("risk"),
            "effort": implementation.get(
                "effort"
            ),
        },
        "verification": {
            "passed": True,
            "verification_version": (
                verification.get(
                    "verification_version"
                )
            ),
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
            "results": verification_summary,
        },
        "commit": commit,
        "completion": {
            "success": True,
            "remaining_risks": [],
            "rollback_required": False,
            "working_tree_clean": (
                commit.get(
                    "working_tree_clean"
                )
            ),
        },
    }

    report["summary"] = _build_human_summary(
        mission=mission,
        implementation=implementation,
        verification=verification,
        commit=commit,
    )

    result_text = json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(result_text) > 95000:
        raise MissionReportingError(
            "Reporting結果が保存上限を超えました。"
        )

    if reporting_task["status"] != "RUNNING":
        update_mission_task(
            mission_id=mission_id,
            task_id=reporting_task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

    updated_mission = update_mission_task(
        mission_id=mission_id,
        task_id=reporting_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=result_text,
        ),
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="MISSION_REPORTING_COMPLETED",
        message=(
            "Missionの変更内容・検証結果・"
            "Commit情報をまとめ、"
            "最終報告を作成しました。"
        ),
        metadata={
            "reporting_version": (
                "mission-reporting-v0.1"
            ),
            "success": True,
            "changed_file_count": (
                commit.get(
                    "changed_file_count",
                    0,
                )
            ),
            "commit_hash": commit.get(
                "commit_hash"
            ),
            "verification_passed": True,
        },
    )

    return {
        "mission": updated_mission,
        "report": report,
    }


def run_mission_reporting_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_mission_reporting(
            mission_id
        )
    except MissionReportingError:
        raise
    except MissionError as error:
        raise MissionReportingError(
            str(error)
        ) from error
    except Exception as error:
        raise MissionReportingError(
            "Reporting Runnerで予期しない"
            f"エラーが発生しました: {error}"
        ) from error
