from fastapi import APIRouter, HTTPException, Query, status

from app.missions.models import (
    MissionApprovalDecision,
    MissionCommitRequest,
    MissionPatchApplyRequest,
    MissionPatchGenerateRequest,
    MissionPatchCheckRequest,
    MissionCreate,
    MissionRepairRequestCreate,
    MissionRepairResumeRequest,
    MissionRepairApproveAndResumeRequest,
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
from app.missions.reporting_runner import (
    MissionReportingError,
    run_mission_reporting_safe,
)
from app.missions.self_repair_planner import (
    MissionSelfRepairPlannerError,
    run_self_repair_planner_safe,
)
from app.missions.repair_request_builder import (
    MissionRepairRequestError,
    create_repair_patch_request_safe,
)
from app.missions.repair_patch_connector import (
    MissionRepairPatchConnectorError,
    connect_repair_request_to_patch_generator_safe,
)
from app.missions.repair_patch_apply import (
    MissionRepairPatchApplyError,
    apply_repair_patch_safe,
)
from app.missions.repair_verification_runner import (
    MissionRepairVerificationError,
    run_repair_verification_safe,
)
from app.missions.retry_controller import (
    MissionRetryControllerError,
    prepare_repair_retry_safe,
)
from app.missions.repair_context_builder import (
    MissionRepairContextError,
    build_repair_context_safe,
)
from app.missions.repair_edit_generator import (
    MissionRepairEditGeneratorError,
    generate_repair_edit_safe,
)
from app.missions.repair_edit_connector import (
    MissionRepairEditConnectorError,
    connect_repair_edit_safe,
)
from app.missions.repair_cycle_orchestrator import (
    MissionRepairCycleOrchestratorError,
    run_repair_cycle_step_safe,
)
from app.missions.repair_cycle_runner import (
    MissionRepairCycleRunnerError,
    run_repair_cycle_safe,
)
from app.missions.repair_supervisor import (
    MissionRepairSupervisorError,
    supervise_repair_safe,
)
from app.missions.repair_execution_policy import (
    MissionRepairExecutionPolicyError,
    evaluate_repair_execution_policy_safe,
)
from app.missions.repair_approval_workflow import (
    MissionRepairApprovalError,
    approve_repair_safe,
    get_repair_approval_safe,
    reject_repair_safe,
)
from app.missions.repair_approval_resume_runner import (
    MissionRepairApprovalResumeError,
    approve_and_resume_repair_safe,
    resume_repair_safe,
)
from app.missions.commit_runner import (
    MissionCommitError,
    commit_mission_changes_safe,
)
from app.missions.patch_generator import (
    MissionPatchGeneratorError,
    generate_mission_patch_safe,
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


@router.post(
    "/{mission_id}/repair-plan",
)
def create_mission_repair_plan_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_self_repair_planner_safe(
            mission_id
        )
    except (
        MissionSelfRepairPlannerError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/repair-request",
)
def create_mission_repair_request_endpoint(
    mission_id: int,
    payload: MissionRepairRequestCreate,
) -> dict:
    try:
        return create_repair_patch_request_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairRequestError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-patch-generate",
)
def generate_mission_repair_patch_endpoint(
    mission_id: int,
) -> dict:
    try:
        return (
            connect_repair_request_to_patch_generator_safe(
                mission_id
            )
        )
    except (
        MissionRepairPatchConnectorError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-patch-apply",
)
def apply_mission_repair_patch_endpoint(
    mission_id: int,
) -> dict:
    try:
        return apply_repair_patch_safe(
            mission_id=mission_id,
        )
    except (
        MissionRepairPatchApplyError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-verify",
)
def verify_mission_repair_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_repair_verification_safe(
            mission_id
        )
    except (
        MissionRepairVerificationError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-retry",
)
def prepare_mission_repair_retry_endpoint(
    mission_id: int,
    max_retries: int | None = Query(
        default=None,
        ge=1,
        le=10,
    ),
) -> dict:
    try:
        return prepare_repair_retry_safe(
            mission_id=mission_id,
            max_retries=max_retries,
        )
    except (
        MissionRetryControllerError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.get(
    "/{mission_id}/repair-approval",
)
def get_repair_approval_endpoint(
    mission_id: int,
) -> dict:
    try:
        return get_repair_approval_safe(
            mission_id
        )
    except (
        MissionRepairApprovalError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/repair-approve",
)
def approve_repair_endpoint(
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict:
    try:
        return approve_repair_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/repair-reject",
)
def reject_repair_endpoint(
    mission_id: int,
    payload: MissionApprovalDecision,
) -> dict:
    try:
        return reject_repair_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/repair-resume",
)
def resume_repair_endpoint(
    mission_id: int,
    payload: MissionRepairResumeRequest,
) -> dict:
    try:
        return resume_repair_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalResumeError,
        MissionRepairApprovalError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/repair-approve-and-resume",
)
def approve_and_resume_repair_endpoint(
    mission_id: int,
    payload: MissionRepairApproveAndResumeRequest,
) -> dict:
    try:
        return approve_and_resume_repair_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionRepairApprovalResumeError,
        MissionRepairApprovalError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/repair-policy-evaluate",
)
def evaluate_mission_repair_policy_endpoint(
    mission_id: int,
) -> dict:
    try:
        return (
            evaluate_repair_execution_policy_safe(
                mission_id
            )
        )
    except (
        MissionRepairExecutionPolicyError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-supervise",
)
def supervise_mission_repair_endpoint(
    mission_id: int,
    max_steps: int = Query(
        default=8,
        ge=1,
        le=20,
    ),
) -> dict:
    try:
        return supervise_repair_safe(
            mission_id=mission_id,
            max_steps=max_steps,
        )
    except (
        MissionRepairSupervisorError,
        MissionRepairCycleRunnerError,
        MissionRepairCycleOrchestratorError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/repair-cycle-run",
)
def run_mission_repair_cycle_endpoint(
    mission_id: int,
    max_steps: int = Query(
        default=8,
        ge=1,
        le=20,
    ),
) -> dict:
    try:
        return run_repair_cycle_safe(
            mission_id=mission_id,
            max_steps=max_steps,
        )
    except (
        MissionRepairCycleRunnerError,
        MissionRepairCycleOrchestratorError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-cycle-step",
)
def run_mission_repair_cycle_step_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_repair_cycle_step_safe(
            mission_id
        )
    except (
        MissionRepairCycleOrchestratorError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-edit-connect",
)
def connect_mission_repair_edit_endpoint(
    mission_id: int,
) -> dict:
    try:
        return connect_repair_edit_safe(
            mission_id
        )
    except (
        MissionRepairEditConnectorError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-edit-generate",
)
def generate_mission_repair_edit_endpoint(
    mission_id: int,
) -> dict:
    try:
        return generate_repair_edit_safe(
            mission_id
        )
    except (
        MissionRepairEditGeneratorError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/repair-context",
)
def build_mission_repair_context_endpoint(
    mission_id: int,
) -> dict:
    try:
        return build_repair_context_safe(
            mission_id
        )
    except (
        MissionRepairContextError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error



@router.post(
    "/{mission_id}/implementation/patch-generate",
)
def generate_mission_patch_endpoint(
    mission_id: int,
    payload: MissionPatchGenerateRequest,
) -> dict:
    try:
        return generate_mission_patch_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionPatchGeneratorError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/commit",
)
def commit_mission_changes_endpoint(
    mission_id: int,
    payload: MissionCommitRequest,
) -> dict:
    try:
        return commit_mission_changes_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except (
        MissionCommitError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/{mission_id}/report",
)
def report_mission_endpoint(
    mission_id: int,
) -> dict:
    try:
        return run_mission_reporting_safe(
            mission_id
        )
    except (
        MissionReportingError,
        MissionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

