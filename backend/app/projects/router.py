from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.database import get_connection
from app.projects.models import ProjectCreate, ProjectResponse


router = APIRouter(prefix="/projects", tags=["projects"])


def _row_to_project(row) -> ProjectResponse:
    return ProjectResponse(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        project_type=row["project_type"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects() -> list[ProjectResponse]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                path,
                project_type,
                status,
                created_at,
                updated_at
            FROM projects
            ORDER BY updated_at DESC
            """
        ).fetchall()

    return [_row_to_project(row) for row in rows]


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(payload: ProjectCreate) -> ProjectResponse:
    project_path = Path(payload.path).expanduser().resolve()

    if not project_path.exists():
        raise HTTPException(
            status_code=400,
            detail="指定されたプロジェクトフォルダが存在しません。",
        )

    if not project_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail="指定されたパスはフォルダではありません。",
        )

    now = datetime.now(timezone.utc).isoformat()

    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects (
                    name,
                    path,
                    project_type,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (
                    payload.name.strip(),
                    str(project_path),
                    payload.project_type.strip() or "software",
                    now,
                    now,
                ),
            )
            connection.commit()

            row = connection.execute(
                """
                SELECT
                    id,
                    name,
                    path,
                    project_type,
                    status,
                    created_at,
                    updated_at
                FROM projects
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

    except Exception as error:
        if "UNIQUE constraint failed" in str(error):
            raise HTTPException(
                status_code=409,
                detail="このプロジェクトはすでに登録されています。",
            ) from error

        raise

    return _row_to_project(row)
