from fastapi import APIRouter, HTTPException, status

from app.code_context.builder import (
    CodeContextError,
    build_code_context_safe,
    get_code_context_safe,
)


router = APIRouter(
    prefix="/missions",
    tags=["mission-code-context"],
)


@router.post(
    "/{mission_id}/context",
)
def build_mission_code_context_endpoint(
    mission_id: int,
) -> dict:
    """Missionのコード生成用Contextを構築する。"""
    try:
        return build_code_context_safe(
            mission_id
        )
    except CodeContextError as error:
        detail = str(error)

        status_code = (
            status.HTTP_404_NOT_FOUND
            if "見つかりません" in detail
            else status.HTTP_409_CONFLICT
        )

        raise HTTPException(
            status_code=status_code,
            detail=detail,
        ) from error


@router.get(
    "/{mission_id}/context",
)
def get_mission_code_context_endpoint(
    mission_id: int,
) -> dict:
    """保存済みCode Contextを読み取り専用で取得する。"""
    try:
        return get_code_context_safe(
            mission_id
        )
    except CodeContextError as error:
        detail = str(error)

        status_code = (
            status.HTTP_404_NOT_FOUND
            if (
                "見つかりません" in detail
                or "まだ生成されていません"
                in detail
            )
            else status.HTTP_409_CONFLICT
        )

        raise HTTPException(
            status_code=status_code,
            detail=detail,
        ) from error
