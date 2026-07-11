from fastapi import APIRouter, HTTPException, Query

from app.indexer.service import (
    IndexingError,
    get_index_summary,
    index_project,
    search_project,
    search_symbols,
)


router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["code-index"],
)


@router.post("/index")
def create_project_index(project_id: int) -> dict:
    try:
        return index_project(project_id)
    except IndexingError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.get("/index/summary")
def project_index_summary(project_id: int) -> dict:
    try:
        return get_index_summary(project_id)
    except IndexingError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error


@router.get("/search")
def project_search(
    project_id: int,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    try:
        return search_project(
            project_id=project_id,
            query=q,
            max_results=limit,
        )
    except IndexingError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.get("/symbols/search")
def project_symbol_search(
    project_id: int,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    try:
        return search_symbols(
            project_id=project_id,
            query=q,
            max_results=limit,
        )
    except IndexingError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
