from fastapi import APIRouter, HTTPException, Query, status

from app.missions.models import (
    MissionApprovalDecision,
    MissionPatchApplyRequest,
    MissionPatchCheckRequest,
    MissionCreate,
    MissionResponse,
    MissionStatusUpdate,
    MissionSummaryResponse,
    MissionTaskUpdate,
)
from app.missions.analysis_runner import (
    MissionAnalysisError,
    run_mission_analysis,
)
from app.missions.planner_runner import (
    MissionPlannerError,
    run_mission_planner,
)
from app.missions.verification_runner import (
    MissionVerificationError,
    run_mission_verification_safe,
)
from app.missions.implementation_runner import (
    MissionImplementationError,
    apply_mission_implementation_patch_safe,
    check_mission_implementation_patch_safe,
    create_mission_implementation_backup_safe,
    run_mission_implementation_safe,
)
from app.missions.service import (
    MissionError,
    advance_mission,
    approve_mission,
    create_mission,
    get_current_mission,
    get_mission,
    list_missions,
    reject_mission,
    update_mission_status,
    update_mission_task,
)


router = APIRouter(
    prefix="/missions",
    tags=["missions"],
)


@router.post(
    "",
    response_model=MissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_mission_endpoint(
    payload: MissionCreate,
) -> MissionResponse:
    try:
        return MissionResponse(
            **create_mission(payload)
        )
    except MissionError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.get(
    "",
    response_model=list[MissionSummaryResponse],
)
def list_missions_endpoint(
    project_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MissionSummaryResponse]:
    return [
        MissionSummaryResponse(**item)
        for item in list_missions(
            project_id=project_id,
            limit=limit,
        )
    ]


@router.get(
    "/current",
    response_model=MissionResponse | None,
)
def current_mission_endpoint(
    project_id: int = Query(ge=1),
) -> MissionResponse | None:
    result = get_current_mission(project_id)

    if result is None:
        return None

    return MissionResponse(**result)


@router.get(
    "/{mission_id}",
    response_model=MissionResponse,
)
def get_mission_endpoint(
    mission_id: int,
) -> MissionResponse:
    try:
        return MissionResponse(
            **get_mission(mission_id)
        )
    except MissionError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error


@router.patch(
    "/{mission_id}/status",
    response_model=MissionResponse,
)
def update_mission_status_endpoint(
    mission_id: int,
    payload: MissionStatusUpdate,
) -> MissionResponse:
    try:
        return MissionResponse(
            **update_mission_status(
                mission_id=mission_id,
                payload=payload,
            )
        )
    except MissionError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.patch(
    "/{mission_id}/tasks/{task_id}",
    response_model=MissionResponse,
)
def update_mission_task_endpoint(
    mission_id: int,
    task_id: int,
    payload: MissionTaskUpdate,
) -> MissionResponse:
    try:
        return MissionResponse(
            **update_mission_task(
                mission_id=mission_id,
                task_id=task_id,
                payload=payload,
            )
        )
    except MissionError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/approve",
    response_model=MissionResponse,
)
def approve_mission_endpoint(
    mission_id: int,
    payload: MissionApprovalDecision,
) -> MissionResponse:
    try:
        return MissionResponse(
            **approve_mission(
                mission_id=mission_id,
                payload=payload,
            )
        )
    except MissionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/reject",
    response_model=MissionResponse,
)
def reject_mission_endpoint(
    mission_id: int,
    payload: MissionApprovalDecision,
) -> MissionResponse:
    try:
        return MissionResponse(
            **reject_mission(
                mission_id=mission_id,
                payload=payload,
            )
        )
    except MissionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/advance",
    response_model=MissionResponse,
)
def advance_mission_endpoint(
    mission_id: int,
) -> MissionResponse:
    try:
        return MissionResponse(
            **advance_mission(mission_id)
        )
    except MissionError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/analyze",
)
def analyze_mission_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_mission_analysis(mission_id)
    except (
        MissionAnalysisError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/plan",
)
def plan_mission_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_mission_planner(mission_id)
    except (
        MissionPlannerError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/implement",
)
def implement_mission_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_mission_implementation_safe(
            mission_id
        )
    except (
        MissionImplementationError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/implementation/backup",
)
def backup_mission_implementation_endpoint(
    mission_id: int,
) -> dict:
    try:
        return create_mission_implementation_backup_safe(
            mission_id
        )
    except (
        MissionImplementationError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/implementation/patch-check",
)
def check_mission_implementation_patch_endpoint(
    mission_id: int,
    payload: MissionPatchCheckRequest,
) -> dict:
    try:
        return check_mission_implementation_patch_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionImplementationError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/implementation/patch-apply",
)
def apply_mission_implementation_patch_endpoint(
    mission_id: int,
    payload: MissionPatchApplyRequest,
) -> dict:
    try:
        return apply_mission_implementation_patch_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionImplementationError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/verify",
)
def verify_mission_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_mission_verification_safe(
            mission_id
        )
    except (
        MissionVerificationError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

