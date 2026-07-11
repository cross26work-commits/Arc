from fastapi import APIRouter, HTTPException, Query

from app.analyzer.service import (
    FileAnalysisError,
    analyze_project_file,
)
from app.database import get_connection


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["file-analysis"],
)


def _get_project(project_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, path
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()


@router.get("/file/analyze")
def analyze_file(
    project_id: int,
    path: str = Query(min_length=1, max_length=1000),
) -> dict:
    project = _get_project(project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="プロジェクトが見つかりません。",
        )

    try:
        result = analyze_project_file(
            project_path=project["path"],
            relative_path=path,
        )
    except FileAnalysisError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return {
        "project_id": project["id"],
        "project_name": project["name"],
        **result,
    }
