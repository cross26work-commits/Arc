from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database import get_connection
from app.missions.models import (
    MissionCreate,
    MissionStatusUpdate,
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
                status,
                progress,
                success_criteria,
                next_action,
                error_count,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'DRAFT', 0, ?, ?, 0, ?, ?)
            """,
            (
                payload.project_id,
                plan["title"],
                payload.objective.strip(),
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
