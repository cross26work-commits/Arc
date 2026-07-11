from fastapi import APIRouter, HTTPException, Query

from app.database import get_connection
from app.dependencies.service import (
    DependencyGraphError,
    analyze_dependency_tree,
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
    include_graph: bool = Query(default=False),
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
            include_graph=include_graph,
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


@router.get("/dependencies/tree")
def project_dependency_tree(
    project_id: int,
    path: str = Query(
        min_length=1,
        max_length=1000,
    ),
    direction: str = Query(default="both"),
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
    max_nodes: int = Query(
        default=300,
        ge=10,
        le=2000,
    ),
) -> dict:
    project = _get_project(project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="プロジェクトが見つかりません。",
        )

    try:
        result = analyze_dependency_tree(
            project_path=project["path"],
            target_path=path,
            direction=direction,
            max_files=max_files,
            max_depth=max_depth,
            max_nodes=max_nodes,
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
