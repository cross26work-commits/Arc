from typing import Literal

from pydantic import BaseModel, Field


MissionStatus = Literal[
    "DRAFT",
    "PLANNED",
    "APPROVED",
    "RUNNING",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]

TaskStatus = Literal[
    "PENDING",
    "READY",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "SKIPPED",
    "BLOCKED",
]


class MissionCreate(BaseModel):
    project_id: int
    objective: str = Field(min_length=3, max_length=3000)
    success_criteria: str | None = Field(
        default=None,
        max_length=3000,
    )


class MissionStatusUpdate(BaseModel):
    status: MissionStatus
    next_action: str | None = Field(
        default=None,
        max_length=1000,
    )


class MissionApprovalDecision(BaseModel):
    reason: str | None = Field(
        default=None,
        max_length=3000,
    )
    decided_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )


class MissionApprovalResumeRequest(BaseModel):
    action: Literal[
        "APPROVE_MISSION",
        "APPLY_PATCH",
        "COMMIT_CHANGES",
    ]
    reason: str | None = Field(
        default=None,
        max_length=3000,
    )
    decided_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )
    expected_patch_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    commit_message: str | None = Field(
        default=None,
        min_length=3,
        max_length=500,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )
    continue_cycle: bool = True
    max_steps: int = Field(
        default=10,
        ge=1,
        le=50,
    )


class MissionRecoveryResumeRequest(BaseModel):
    """Recovery状態から明示承認付きで再開するRequest。"""

    approved: bool = False
    action: Literal[
        "APPROVE_MISSION",
        "APPLY_PATCH",
        "COMMIT_CHANGES",
    ]
    expected_current_stage: str = Field(
        min_length=1,
        max_length=100,
    )
    expected_patch_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    commit_message: str | None = Field(
        default=None,
        min_length=3,
        max_length=500,
    )
    reason: str | None = Field(
        default=None,
        max_length=3000,
    )
    decided_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )
    continue_cycle: bool = True
    max_steps: int = Field(
        default=10,
        ge=1,
        le=50,
    )


class MissionRepairResumeRequest(BaseModel):
    requested_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )


class MissionRepairApproveAndResumeRequest(BaseModel):
    reason: str | None = Field(
        default=None,
        max_length=3000,
    )
    decided_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )


class MissionPatchCheckRequest(BaseModel):
    patch_text: str = Field(
        min_length=1,
        max_length=500000,
    )
    generated_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )


class MissionPatchApplyRequest(BaseModel):
    confirmation: str = Field(
        min_length=1,
        max_length=100,
    )
    expected_patch_sha256: str = Field(
        min_length=64,
        max_length=64,
    )
    decided_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )


class MissionPatchEdit(BaseModel):
    operation: Literal[
        "REPLACE_UNIQUE",
        "APPEND",
        "INSERT_BEFORE",
        "INSERT_AFTER",
    ]
    path: str = Field(
        min_length=1,
        max_length=1000,
    )
    old_text: str | None = Field(
        default=None,
        max_length=100000,
    )
    new_text: str | None = Field(
        default=None,
        max_length=100000,
    )
    anchor: str | None = Field(
        default=None,
        max_length=100000,
    )
    text: str | None = Field(
        default=None,
        max_length=100000,
    )


class MissionPatchGenerateRequest(BaseModel):
    edits: list[MissionPatchEdit] = Field(
        min_length=1,
        max_length=100,
    )
    generated_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )



class MissionRepairRequestCreate(BaseModel):
    edits: list[MissionPatchEdit] = Field(
        min_length=1,
        max_length=100,
    )
    generated_by: str = Field(
        default="repair-runner-v0.1",
        min_length=1,
        max_length=200,
    )
    note: str | None = Field(
        default=None,
        max_length=3000,
    )


class MissionCommitRequest(BaseModel):
    confirmation: str = Field(
        min_length=1,
        max_length=100,
    )
    message: str = Field(
        min_length=3,
        max_length=500,
    )
    committed_by: str = Field(
        default="master",
        min_length=1,
        max_length=200,
    )


class MissionTaskResponse(BaseModel):
    id: int
    mission_id: int
    position: int
    title: str
    description: str
    task_type: str
    status: TaskStatus
    target_path: str | None
    result: str | None
    created_at: str
    updated_at: str


class MissionLogResponse(BaseModel):
    id: int
    mission_id: int
    level: str
    event_type: str
    message: str
    metadata: str | None
    created_at: str


class MissionResponse(BaseModel):
    id: int
    project_id: int
    project_name: str
    title: str
    objective: str
    status: MissionStatus
    progress: int
    success_criteria: str
    next_action: str
    error_count: int
    created_at: str
    updated_at: str
    tasks: list[MissionTaskResponse] = []
    logs: list[MissionLogResponse] = []


class MissionSummaryResponse(BaseModel):
    id: int
    project_id: int
    project_name: str
    title: str
    objective: str
    status: MissionStatus
    progress: int
    next_action: str
    task_count: int
    completed_task_count: int
    error_count: int
    created_at: str
    updated_at: str


class MissionTaskUpdate(BaseModel):
    status: TaskStatus
    result: str | None = Field(
        default=None,
        max_length=100000,
    )
    target_path: str | None = Field(
        default=None,
        max_length=1000,
    )
