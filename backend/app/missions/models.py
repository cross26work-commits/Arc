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
