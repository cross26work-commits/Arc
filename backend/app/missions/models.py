from typing import Any, Literal

from pydantic import BaseModel, Field


MissionType = Literal[
    "IMPLEMENTATION",
    "ANALYSIS",
]


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


class RequirementRisk(BaseModel):
    category: str = Field(
        min_length=1,
        max_length=100,
    )
    level: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
    ] = "LOW"
    description: str = Field(
        min_length=1,
        max_length=1000,
    )
    mitigation: str | None = Field(
        default=None,
        max_length=1000,
    )


class RequirementAnalyzerResult(BaseModel):
    contract_version: str = Field(
        default="requirement-contract-v0.1",
        min_length=1,
        max_length=100,
    )
    objective: str = Field(
        min_length=3,
        max_length=3000,
    )
    requirements: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    in_scope: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    out_of_scope: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    constraints: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    missing_information: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    risks: list[RequirementRisk] = Field(
        default_factory=list,
        max_length=100,
    )
    implementation_possible: bool
    analysis_summary: str = Field(
        min_length=1,
        max_length=3000,
    )


FileOperationType = Literal[
    "CREATE",
    "UPDATE",
    "DELETE",
    "RENAME",
    "TEST",
    "VERIFY",
]


class FileOperation(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=1000,
    )
    operation: FileOperationType
    purpose: str = Field(
        min_length=1,
        max_length=3000,
    )
    category: Literal[
        "BACKEND",
        "DATA",
        "FRONTEND",
        "TEST",
        "OTHER",
    ] = "OTHER"
    language: str | None = Field(
        default=None,
        max_length=100,
    )
    depends_on: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    affected_files: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    risk_level: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "UNKNOWN",
    ] = "UNKNOWN"
    reasons: list[str] = Field(
        default_factory=list,
        max_length=100,
    )


class ImplementationStep(BaseModel):
    step_id: str = Field(
        min_length=1,
        max_length=200,
    )
    position: int = Field(
        ge=1,
        le=1000,
    )
    title: str = Field(
        min_length=1,
        max_length=500,
    )
    description: str = Field(
        min_length=1,
        max_length=3000,
    )
    category: Literal[
        "BACKEND",
        "DATA",
        "FRONTEND",
        "TEST",
        "VERIFICATION",
        "OTHER",
    ] = "OTHER"
    file_operations: list[FileOperation] = Field(
        default_factory=list,
        max_length=100,
    )
    depends_on_steps: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    can_run_in_parallel: bool = False
    verification_commands: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    completion_criteria: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    risk_level: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "UNKNOWN",
    ] = "UNKNOWN"


class ImplementationPlan(BaseModel):
    plan_version: str = Field(
        default="implementation-plan-v0.1",
        min_length=1,
        max_length=100,
    )
    mission_id: int = Field(
        ge=1,
    )
    project_id: int = Field(
        ge=1,
    )
    project_name: str = Field(
        min_length=1,
        max_length=500,
    )
    objective: str = Field(
        min_length=3,
        max_length=3000,
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    requirement_contract_version: str = Field(
        min_length=1,
        max_length=100,
    )
    requirement_contract: RequirementAnalyzerResult
    implementation_possible: bool
    clarification_required: bool = False
    clarification_questions: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    selected_files: list[FileOperation] = Field(
        default_factory=list,
        max_length=100,
    )
    steps: list[ImplementationStep] = Field(
        default_factory=list,
        max_length=1000,
    )
    execution_order: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    verification_commands: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    file_execution_order: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    dependency_graph: dict = Field(
        default_factory=dict,
    )
    dependency_cycles: list[list[str]] = Field(
        default_factory=list,
        max_length=100,
    )
    parallel_groups: list[list[str]] = Field(
        default_factory=list,
        max_length=1000,
    )
    overall_risk_level: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "UNKNOWN",
    ] = "UNKNOWN"
    estimated_effort_level: Literal[
        "SMALL",
        "MEDIUM",
        "LARGE",
        "UNKNOWN",
    ] = "UNKNOWN"
    approval_summary: str = Field(
        min_length=1,
        max_length=5000,
    )


StepExecutionStatus = Literal[
    "PENDING",
    "GENERATING",
    "PATCH_READY",
    "PATCH_APPLIED",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
]


class ImplementationStepResult(BaseModel):
    step_id: str = Field(
        min_length=1,
        max_length=200,
    )
    status: StepExecutionStatus = "PENDING"
    attempt_count: int = Field(
        default=0,
        ge=0,
        le=100,
    )
    prompt_version: str | None = Field(
        default=None,
        max_length=100,
    )
    context_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    contract_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    patch_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    changed_files: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    verification_passed: bool | None = None
    error: str | None = Field(
        default=None,
        max_length=5000,
    )
    started_at: str | None = Field(
        default=None,
        max_length=100,
    )
    completed_at: str | None = Field(
        default=None,
        max_length=100,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class ImplementationStepExecution(BaseModel):
    execution_version: str = Field(
        default="implementation-step-execution-v0.1",
        min_length=1,
        max_length=100,
    )
    current_step_id: str | None = Field(
        default=None,
        max_length=200,
    )
    completed_step_ids: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    remaining_step_ids: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    blocked_step_ids: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    results: dict[str, ImplementationStepResult] = Field(
        default_factory=dict,
    )
    execution_completed: bool = False
    total_attempt_count: int = Field(
        default=0,
        ge=0,
        le=10000,
    )


class CodeGenerationPrompt(BaseModel):
    prompt_version: str = Field(
        default="code-generation-prompt-v0.1",
        min_length=1,
        max_length=100,
    )
    system_prompt: str = Field(
        min_length=1,
        max_length=30000,
    )
    user_prompt: str = Field(
        min_length=1,
        max_length=200000,
    )
    mission_id: int = Field(
        ge=1,
    )
    implementation_step_id: str | None = Field(
        default=None,
        max_length=200,
    )
    target_files: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    dependency_order: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    completed_dependencies: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    remaining_dependencies: list[str] = Field(
        default_factory=list,
        max_length=1000,
    )
    verification_commands: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class MissionCreate(BaseModel):
    project_id: int
    objective: str = Field(min_length=3, max_length=3000)
    mission_type: MissionType = "IMPLEMENTATION"
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
    mission_type: MissionType
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
    mission_type: MissionType
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
