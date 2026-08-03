from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database import get_connection
from app.missions.models import (
    MissionApprovalDecision,
    MissionCreate,
    MissionStatusUpdate,
    MissionTaskUpdate,
)
from app.missions.planner import generate_initial_plan


class MissionError(Exception):
    """Mission処理に失敗した場合の例外。"""


ACTIVE_STATUSES = (
    "DRAFT",
    "PLANNED",
    "APPROVED",
    "RUNNING",
    "VERIFYING",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_project(project_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, path, status
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()


def _mission_row(mission_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                missions.*,
                projects.name AS project_name
            FROM missions
            INNER JOIN projects
                ON projects.id = missions.project_id
            WHERE missions.id = ?
            """,
            (mission_id,),
        ).fetchone()


def _task_rows(mission_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM mission_tasks
            WHERE mission_id = ?
            ORDER BY position ASC, id ASC
            """,
            (mission_id,),
        ).fetchall()


def _log_rows(mission_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM mission_logs
            WHERE mission_id = ?
            ORDER BY id DESC
            LIMIT 200
            """,
            (mission_id,),
        ).fetchall()


def _row_to_task(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "mission_id": row["mission_id"],
        "position": row["position"],
        "title": row["title"],
        "description": row["description"],
        "task_type": row["task_type"],
        "status": row["status"],
        "target_path": row["target_path"],
        "result": row["result"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_log(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "mission_id": row["mission_id"],
        "level": row["level"],
        "event_type": row["event_type"],
        "message": row["message"],
        "metadata": row["metadata"],
        "created_at": row["created_at"],
    }


def _row_to_mission(
    row,
    *,
    include_details: bool,
) -> dict[str, Any]:
    result = {
        "id": row["id"],
        "project_id": row["project_id"],
        "project_name": row["project_name"],
        "title": row["title"],
        "objective": row["objective"],
        "mission_type": row["mission_type"],
        "status": row["status"],
        "progress": row["progress"],
        "success_criteria": row["success_criteria"],
        "next_action": row["next_action"],
        "error_count": row["error_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

    if include_details:
        result["tasks"] = [
            _row_to_task(task)
            for task in _task_rows(row["id"])
        ]
        result["logs"] = [
            _row_to_log(log)
            for log in _log_rows(row["id"])
        ]

    return result


def add_mission_log(
    *,
    mission_id: int,
    level: str,
    event_type: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO mission_logs (
                mission_id,
                level,
                event_type,
                message,
                metadata,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                level,
                event_type,
                message,
                (
                    json.dumps(
                        metadata,
                        ensure_ascii=False,
                    )
                    if metadata is not None
                    else None
                ),
                _now(),
            ),
        )
        connection.commit()


def create_mission(payload: MissionCreate) -> dict[str, Any]:
    project = _get_project(payload.project_id)

    if project is None:
        raise MissionError(
            "対象プロジェクトが見つかりません。"
        )

    plan = generate_initial_plan(
        objective=payload.objective,
        project_name=project["name"],
        mission_type=payload.mission_type,
    )

    success_criteria = (
        payload.success_criteria.strip()
        if payload.success_criteria
        else plan["success_criteria"]
    )

    now = _now()

    with get_connection() as connection:
        active = connection.execute(
            """
            SELECT id
            FROM missions
            WHERE project_id = ?
              AND status IN (
                'DRAFT',
                'PLANNED',
                'APPROVED',
                'RUNNING',
                'VERIFYING'
              )
            ORDER BY id DESC
            LIMIT 1
            """,
            (payload.project_id,),
        ).fetchone()

        if active is not None:
            raise MissionError(
                "このプロジェクトには未完了のMissionがあります。"
            )

        cursor = connection.execute(
            """
            INSERT INTO missions (
                project_id,
                title,
                objective,
                mission_type,
                status,
                progress,
                success_criteria,
                next_action,
                error_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 'DRAFT', 0, ?, ?, 0, ?, ?)
            """,
            (
                payload.project_id,
                plan["title"],
                payload.objective.strip(),
                payload.mission_type,
                success_criteria,
                plan["next_action"],
                now,
                now,
            ),
        )

        mission_id = int(cursor.lastrowid)

        for task in plan["tasks"]:
            connection.execute(
                """
                INSERT INTO mission_tasks (
                    mission_id,
                    position,
                    title,
                    description,
                    task_type,
                    status,
                    target_path,
                    result,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    mission_id,
                    task["position"],
                    task["title"],
                    task["description"],
                    task["task_type"],
                    task["status"],
                    now,
                    now,
                ),
            )

        connection.execute(
            """
            INSERT INTO mission_logs (
                mission_id,
                level,
                event_type,
                message,
                metadata,
                created_at
            )
            VALUES (?, 'INFO', 'MISSION_CREATED', ?, ?, ?)
            """,
            (
                mission_id,
                "Missionを作成し、初期タスクを生成しました。",
                json.dumps(
                    {
                        "task_count": len(plan["tasks"]),
                        "project_name": project["name"],
                        "mission_type": payload.mission_type,
                    },
                    ensure_ascii=False,
                ),
                now,
            ),
        )

        connection.commit()

    return get_mission(mission_id)


def get_mission(mission_id: int) -> dict[str, Any]:
    row = _mission_row(mission_id)

    if row is None:
        raise MissionError(
            "Missionが見つかりません。"
        )

    return _row_to_mission(
        row,
        include_details=True,
    )


def get_current_mission(
    project_id: int,
) -> dict[str, Any] | None:
    placeholders = ",".join(
        "?"
        for _ in ACTIVE_STATUSES
    )

    with get_connection() as connection:
        row = connection.execute(
            f"""
            SELECT
                missions.*,
                projects.name AS project_name
            FROM missions
            INNER JOIN projects
                ON projects.id = missions.project_id
            WHERE missions.project_id = ?
              AND missions.status IN ({placeholders})
            ORDER BY missions.id DESC
            LIMIT 1
            """,
            (
                project_id,
                *ACTIVE_STATUSES,
            ),
        ).fetchone()

    if row is None:
        return None

    return _row_to_mission(
        row,
        include_details=True,
    )


def list_missions(
    *,
    project_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conditions = ""
    params: list[Any] = []

    if project_id is not None:
        conditions = "WHERE missions.project_id = ?"
        params.append(project_id)

    params.append(limit)

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                missions.*,
                projects.name AS project_name,
                COUNT(mission_tasks.id) AS task_count,
                SUM(
                    CASE
                        WHEN mission_tasks.status = 'COMPLETED'
                        THEN 1
                        ELSE 0
                    END
                ) AS completed_task_count
            FROM missions
            INNER JOIN projects
                ON projects.id = missions.project_id
            LEFT JOIN mission_tasks
                ON mission_tasks.mission_id = missions.id
            {conditions}
            GROUP BY missions.id
            ORDER BY missions.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [
        {
            "id": row["id"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "title": row["title"],
            "objective": row["objective"],
            "status": row["status"],
            "progress": row["progress"],
            "next_action": row["next_action"],
            "task_count": row["task_count"] or 0,
            "completed_task_count": (
                row["completed_task_count"] or 0
            ),
            "error_count": row["error_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def update_mission_status(
    *,
    mission_id: int,
    payload: MissionStatusUpdate,
) -> dict[str, Any]:
    current = _mission_row(mission_id)

    if current is None:
        raise MissionError(
            "Missionが見つかりません。"
        )

    now = _now()

    progress_by_status = {
        "DRAFT": 0,
        "PLANNED": 15,
        "APPROVED": 25,
        "RUNNING": max(current["progress"], 30),
        "VERIFYING": max(current["progress"], 80),
        "COMPLETED": 100,
        "FAILED": current["progress"],
        "CANCELLED": current["progress"],
    }

    default_next_action = {
        "DRAFT": "目的と成功条件を整理する",
        "PLANNED": "実装計画を確認する",
        "APPROVED": "最初の実装タスクを開始する",
        "RUNNING": "実装タスクを継続する",
        "VERIFYING": "構文確認・Build・テストを実行する",
        "COMPLETED": "完了報告を確認する",
        "FAILED": "失敗原因を解析する",
        "CANCELLED": "Missionは中止されました",
    }

    next_action = (
        payload.next_action.strip()
        if payload.next_action
        else default_next_action[payload.status]
    )

    error_increment = (
        1
        if payload.status == "FAILED"
        else 0
    )

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE missions
            SET
                status = ?,
                progress = ?,
                next_action = ?,
                error_count = error_count + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload.status,
                progress_by_status[payload.status],
                next_action,
                error_increment,
                now,
                mission_id,
            ),
        )
        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level=(
            "ERROR"
            if payload.status == "FAILED"
            else "INFO"
        ),
        event_type="STATUS_CHANGED",
        message=(
            f"Mission状態を"
            f"{current['status']}から"
            f"{payload.status}へ変更しました。"
        ),
        metadata={
            "previous_status": current["status"],
            "new_status": payload.status,
        },
    )

    return get_mission(mission_id)


def _get_task_row(
    *,
    mission_id: int,
    task_id: int,
):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM mission_tasks
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                task_id,
                mission_id,
            ),
        ).fetchone()


def _calculate_mission_progress(
    mission_id: int,
) -> int:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT status
            FROM mission_tasks
            WHERE mission_id = ?
            ORDER BY position ASC
            """,
            (mission_id,),
        ).fetchall()

    if not rows:
        return 0

    completed = sum(
        1
        for row in rows
        if row["status"] in {
            "COMPLETED",
            "SKIPPED",
        }
    )

    return round(
        completed / len(rows) * 100
    )


def _next_pending_task(
    *,
    mission_id: int,
    completed_position: int,
):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM mission_tasks
            WHERE mission_id = ?
              AND position > ?
              AND status = 'PENDING'
            ORDER BY position ASC
            LIMIT 1
            """,
            (
                mission_id,
                completed_position,
            ),
        ).fetchone()


def _task_next_action(task_type: str) -> str:
    mapping = {
        "REQUIREMENTS": "目的と成功条件を整理する",
        "ANALYSIS": "対象コードと影響範囲を調査する",
        "PLANNING": "実装計画を作成する",
        "APPROVAL": "実行承認を確認する",
        "IMPLEMENTATION": "承認済みの変更を実装する",
        "VERIFICATION": "Build・構文確認・テストを実行する",
        "REPORTING": "完成条件を確認して報告する",
    }

    return mapping.get(
        task_type,
        "次のタスクを実行する",
    )


def _derive_mission_status(
    *,
    task_type: str,
    task_status: str,
    progress: int,
) -> str:
    if progress >= 100:
        return "COMPLETED"

    if task_status == "FAILED":
        return "FAILED"

    if task_type == "REQUIREMENTS":
        return "DRAFT"

    if task_type in {
        "ANALYSIS",
        "PLANNING",
    }:
        return "PLANNED"

    if task_type == "APPROVAL":
        return "PLANNED"

    if task_type == "IMPLEMENTATION":
        return "RUNNING"

    if task_type == "VERIFICATION":
        return "VERIFYING"

    if task_type == "REPORTING":
        return "VERIFYING"

    return "DRAFT"


def update_mission_task(
    *,
    mission_id: int,
    task_id: int,
    payload,
) -> dict[str, Any]:
    mission = _mission_row(mission_id)

    if mission is None:
        raise MissionError(
            "Missionが見つかりません。"
        )

    task = _get_task_row(
        mission_id=mission_id,
        task_id=task_id,
    )

    if task is None:
        raise MissionError(
            "Mission Taskが見つかりません。"
        )

    if mission["status"] in {
        "COMPLETED",
        "CANCELLED",
    }:
        raise MissionError(
            "完了または中止済みMissionは変更できません。"
        )

    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = ?,
                result = COALESCE(?, result),
                target_path = COALESCE(?, target_path),
                updated_at = ?
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                payload.status,
                (
                    payload.result.strip()
                    if payload.result
                    else None
                ),
                (
                    payload.target_path.strip()
                    if payload.target_path
                    else None
                ),
                now,
                task_id,
                mission_id,
            ),
        )

        if payload.status == "RUNNING":
            connection.execute(
                """
                UPDATE mission_tasks
                SET status = 'PENDING',
                    updated_at = ?
                WHERE mission_id = ?
                  AND status = 'READY'
                  AND id != ?
                """,
                (
                    now,
                    mission_id,
                    task_id,
                ),
            )

        if payload.status == "COMPLETED":
            next_task = _next_pending_task(
                mission_id=mission_id,
                completed_position=task["position"],
            )

            if next_task is not None:
                connection.execute(
                    """
                    UPDATE mission_tasks
                    SET status = 'READY',
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        next_task["id"],
                    ),
                )

        connection.commit()

    progress = _calculate_mission_progress(
        mission_id
    )

    current_tasks = _task_rows(mission_id)

    ready_or_running = next(
        (
            row
            for row in current_tasks
            if row["status"] in {
                "READY",
                "RUNNING",
            }
        ),
        None,
    )

    if progress >= 100:
        next_action = "完成判定と最終報告を確認する"
        mission_status = "COMPLETED"
    elif ready_or_running is not None:
        next_action = _task_next_action(
            ready_or_running["task_type"]
        )
        mission_status = _derive_mission_status(
            task_type=ready_or_running["task_type"],
            task_status=ready_or_running["status"],
            progress=progress,
        )
    else:
        next_action = "次のタスク状態を確認する"
        mission_status = _derive_mission_status(
            task_type=task["task_type"],
            task_status=payload.status,
            progress=progress,
        )

    error_increment = (
        1
        if payload.status == "FAILED"
        else 0
    )

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE missions
            SET
                status = ?,
                progress = ?,
                next_action = ?,
                error_count = error_count + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                mission_status,
                progress,
                next_action,
                error_increment,
                now,
                mission_id,
            ),
        )
        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level=(
            "ERROR"
            if payload.status == "FAILED"
            else "INFO"
        ),
        event_type="TASK_STATUS_CHANGED",
        message=(
            f"Task「{task['title']}」を"
            f"{task['status']}から"
            f"{payload.status}へ変更しました。"
        ),
        metadata={
            "task_id": task_id,
            "task_type": task["task_type"],
            "previous_status": task["status"],
            "new_status": payload.status,
            "progress": progress,
        },
    )

    return get_mission(mission_id)



def _get_task_by_type(
    *,
    mission_id: int,
    task_type: str,
):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM mission_tasks
            WHERE mission_id = ?
              AND task_type = ?
            ORDER BY position ASC
            LIMIT 1
            """,
            (
                mission_id,
                task_type,
            ),
        ).fetchone()


def approve_mission(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    mission = _mission_row(mission_id)

    if mission is None:
        raise MissionError(
            "Missionが見つかりません。"
        )

    if mission["status"] in {
        "COMPLETED",
        "CANCELLED",
        "FAILED",
    }:
        raise MissionError(
            "完了・中止・失敗済みMissionは承認できません。"
        )

    planning_task = _get_task_by_type(
        mission_id=mission_id,
        task_type="PLANNING",
    )
    approval_task = _get_task_by_type(
        mission_id=mission_id,
        task_type="APPROVAL",
    )

    if planning_task is None:
        raise MissionError(
            "PLANNING Taskが見つかりません。"
        )

    if approval_task is None:
        raise MissionError(
            "APPROVAL Taskが見つかりません。"
        )

    if planning_task["status"] != "COMPLETED":
        raise MissionError(
            "PLANNING Taskが完了していません。"
        )

    if approval_task["status"] != "READY":
        if approval_task["status"] == "COMPLETED":
            raise MissionError(
                "このMissionは既に承認されています。"
            )

        raise MissionError(
            "APPROVAL Taskは承認可能な状態ではありません。"
        )

    decision_result = json.dumps(
        {
            "decision": "APPROVED",
            "reason": (
                payload.reason.strip()
                if payload.reason
                else None
            ),
            "decided_by": payload.decided_by.strip(),
            "decided_at": _now(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    update_mission_task(
        mission_id=mission_id,
        task_id=approval_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=decision_result,
        ),
    )

    approved_task_result = get_mission(mission_id)
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE missions
            SET
                status = 'APPROVED',
                next_action = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                (
                    "承認済みです。"
                    "Implementation Runnerを開始してください。"
                ),
                now,
                mission_id,
            ),
        )
        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="STATUS_CHANGED",
        message=(
            "Mission状態を"
            f"{approved_task_result['status']}から"
            "APPROVEDへ変更しました。"
        ),
        metadata={
            "previous_status": approved_task_result["status"],
            "new_status": "APPROVED",
        },
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type="MISSION_APPROVED",
        message="Missionの実装計画を承認しました。",
        metadata={
            "decision": "APPROVED",
            "reason": (
                payload.reason.strip()
                if payload.reason
                else None
            ),
            "decided_by": payload.decided_by.strip(),
        },
    )

    return get_mission(mission_id)


def reject_mission(
    *,
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict[str, Any]:
    mission = _mission_row(mission_id)

    if mission is None:
        raise MissionError(
            "Missionが見つかりません。"
        )

    if mission["status"] in {
        "COMPLETED",
        "CANCELLED",
    }:
        raise MissionError(
            "完了または中止済みMissionは却下できません。"
        )

    planning_task = _get_task_by_type(
        mission_id=mission_id,
        task_type="PLANNING",
    )
    approval_task = _get_task_by_type(
        mission_id=mission_id,
        task_type="APPROVAL",
    )

    if planning_task is None:
        raise MissionError(
            "PLANNING Taskが見つかりません。"
        )

    if approval_task is None:
        raise MissionError(
            "APPROVAL Taskが見つかりません。"
        )

    if planning_task["status"] != "COMPLETED":
        raise MissionError(
            "PLANNING Taskが完了していません。"
        )

    if approval_task["status"] != "READY":
        raise MissionError(
            "APPROVAL Taskは却下可能な状態ではありません。"
        )

    reason = (
        payload.reason.strip()
        if payload.reason
        else "承認者により再計画が要求されました。"
    )
    now = _now()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'READY',
                updated_at = ?
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                now,
                planning_task["id"],
                mission_id,
            ),
        )

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'PENDING',
                result = NULL,
                updated_at = ?
            WHERE id = ?
              AND mission_id = ?
            """,
            (
                now,
                approval_task["id"],
                mission_id,
            ),
        )

        connection.execute(
            """
            UPDATE mission_tasks
            SET
                status = 'PENDING',
                updated_at = ?
            WHERE mission_id = ?
              AND position > ?
            """,
            (
                now,
                mission_id,
                approval_task["position"],
            ),
        )

        progress_rows = connection.execute(
            """
            SELECT status
            FROM mission_tasks
            WHERE mission_id = ?
            ORDER BY position ASC
            """,
            (mission_id,),
        ).fetchall()

        completed_count = sum(
            1
            for row in progress_rows
            if row["status"] in {
                "COMPLETED",
                "SKIPPED",
            }
        )

        progress = (
            round(
                completed_count
                / len(progress_rows)
                * 100
            )
            if progress_rows
            else 0
        )

        connection.execute(
            """
            UPDATE missions
            SET
                status = 'PLANNED',
                progress = ?,
                next_action = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                progress,
                "却下理由を反映して実装計画を再作成する",
                now,
                mission_id,
            ),
        )

        connection.commit()

    add_mission_log(
        mission_id=mission_id,
        level="WARNING",
        event_type="MISSION_REJECTED",
        message=(
            "Missionの実装計画を却下し、"
            "PLANNING Taskを再実行可能にしました。"
        ),
        metadata={
            "decision": "REJECTED",
            "reason": reason,
            "decided_by": payload.decided_by.strip(),
        },
    )

    return get_mission(mission_id)



def advance_mission(
    mission_id: int,
) -> dict[str, Any]:
    mission = _mission_row(mission_id)

    if mission is None:
        raise MissionError(
            "Missionが見つかりません。"
        )

    tasks = _task_rows(mission_id)

    active_task = next(
        (
            task
            for task in tasks
            if task["status"] in {
                "READY",
                "RUNNING",
            }
        ),
        None,
    )

    if active_task is None:
        raise MissionError(
            "進行可能なTaskがありません。"
        )

    from app.missions.models import MissionTaskUpdate

    if active_task["status"] == "READY":
        return update_mission_task(
            mission_id=mission_id,
            task_id=active_task["id"],
            payload=MissionTaskUpdate(
                status="RUNNING",
            ),
        )

    return update_mission_task(
        mission_id=mission_id,
        task_id=active_task["id"],
        payload=MissionTaskUpdate(
            status="COMPLETED",
            result=(
                "Task Controller v0.1により"
                "手動進行処理を完了しました。"
            ),
        ),
    )
