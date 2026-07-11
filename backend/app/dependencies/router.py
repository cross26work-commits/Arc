from fastapi import APIRouter, HTTPException, Query

from app.database import get_connection
from app.dependencies.service import (
    DependencyGraphError,
    analyze_project_dependencies,
)


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["dependency-graph"],
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


@router.get("/dependencies")
def project_dependencies(
    project_id: int,
    path: str | None = Query(
        default=None,
        max_length=1000,
    ),
    max_files: int = Query(
        default=3000,
        ge=10,
        le=10000,
    ),
    max_depth: int = Query(
        default=5,
        ge=1,
        le=10,
    ),
) -> dict:
    project = _get_project(project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="プロジェクトが見つかりません。",
        )

    try:
        result = analyze_project_dependencies(
            project_path=project["path"],
            target_path=path,
            max_files=max_files,
            max_impact_depth=max_depth,
        )
    except DependencyGraphError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return {
        "project_id": project["id"],
        "project_name": project["name"],
        **result,
    }
