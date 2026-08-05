from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.missions.models import (
    ImplementationPlan,
    ImplementationStepExecution,
    ImplementationStepResult,
)


STEP_EXECUTION_STATE_VERSION = (
    "implementation-step-state-v0.1"
)


class ImplementationStepStateError(Exception):
    """Step実行状態の操作に失敗した場合の例外。"""


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def initialize_step_execution(
    implementation_plan: (
        ImplementationPlan
        | dict[str, Any]
    ),
) -> ImplementationStepExecution:
    try:
        plan = (
            implementation_plan
            if isinstance(
                implementation_plan,
                ImplementationPlan,
            )
            else ImplementationPlan.model_validate(
                implementation_plan
            )
        )
    except Exception as error:
        raise ImplementationStepStateError(
            "Implementation Planの形式が不正です。"
        ) from error

    ordered_step_ids = list(
        plan.execution_order
    )

    if not ordered_step_ids:
        ordered_step_ids = [
            step.step_id
            for step in sorted(
                plan.steps,
                key=lambda item: item.position,
            )
        ]

    results = {
        step_id: ImplementationStepResult(
            step_id=step_id,
        )
        for step_id in ordered_step_ids
    }

    current_step_id = (
        ordered_step_ids[0]
        if ordered_step_ids
        else None
    )

    return ImplementationStepExecution(
        current_step_id=current_step_id,
        completed_step_ids=[],
        remaining_step_ids=ordered_step_ids,
        blocked_step_ids=[],
        results=results,
        execution_completed=(
            not ordered_step_ids
        ),
    )


def load_step_execution(
    value: (
        ImplementationStepExecution
        | dict[str, Any]
    ),
) -> ImplementationStepExecution:
    if isinstance(
        value,
        ImplementationStepExecution,
    ):
        return value

    try:
        return ImplementationStepExecution.model_validate(
            value
        )
    except Exception as error:
        raise ImplementationStepStateError(
            "Step Execution Stateの形式が不正です。"
        ) from error


def start_current_step(
    state: (
        ImplementationStepExecution
        | dict[str, Any]
    ),
) -> ImplementationStepExecution:
    execution = load_step_execution(state)

    step_id = execution.current_step_id

    if step_id is None:
        raise ImplementationStepStateError(
            "開始可能なStepがありません。"
        )

    result = execution.results.get(step_id)

    if result is None:
        raise ImplementationStepStateError(
            f"Step Resultがありません: {step_id}"
        )

    if result.status not in {
        "PENDING",
        "FAILED",
    }:
        raise ImplementationStepStateError(
            "Stepを開始できない状態です: "
            f"{result.status}"
        )

    result.status = "GENERATING"
    result.attempt_count += 1
    result.started_at = _now()
    result.completed_at = None
    result.error = None

    execution.total_attempt_count += 1

    return execution


def update_current_step_status(
    state: (
        ImplementationStepExecution
        | dict[str, Any]
    ),
    *,
    status: str,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> ImplementationStepExecution:
    execution = load_step_execution(state)

    step_id = execution.current_step_id

    if step_id is None:
        raise ImplementationStepStateError(
            "更新対象のCurrent Stepがありません。"
        )

    result = execution.results.get(step_id)

    if result is None:
        raise ImplementationStepStateError(
            f"Step Resultがありません: {step_id}"
        )

    result.status = status
    result.error = error

    if metadata:
        result.metadata.update(metadata)

    if status in {
        "COMPLETED",
        "FAILED",
        "BLOCKED",
    }:
        result.completed_at = _now()

    return execution


def complete_current_step(
    state: (
        ImplementationStepExecution
        | dict[str, Any]
    ),
    *,
    verification_passed: bool,
    changed_files: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ImplementationStepExecution:
    execution = load_step_execution(state)

    step_id = execution.current_step_id

    if step_id is None:
        raise ImplementationStepStateError(
            "完了対象のCurrent Stepがありません。"
        )

    result = execution.results.get(step_id)

    if result is None:
        raise ImplementationStepStateError(
            f"Step Resultがありません: {step_id}"
        )

    if verification_passed is not True:
        result.status = "FAILED"
        result.verification_passed = False
        result.completed_at = _now()

        raise ImplementationStepStateError(
            f"Step Verificationに失敗しました: {step_id}"
        )

    result.status = "COMPLETED"
    result.verification_passed = True
    result.changed_files = list(
        changed_files or []
    )
    result.completed_at = _now()
    result.error = None

    if metadata:
        result.metadata.update(metadata)

    if step_id not in execution.completed_step_ids:
        execution.completed_step_ids.append(
            step_id
        )

    execution.remaining_step_ids = [
        candidate
        for candidate in execution.remaining_step_ids
        if candidate != step_id
    ]

    if execution.remaining_step_ids:
        execution.current_step_id = (
            execution.remaining_step_ids[0]
        )
        execution.execution_completed = False
    else:
        execution.current_step_id = None
        execution.execution_completed = True

    return execution


def block_current_step(
    state: (
        ImplementationStepExecution
        | dict[str, Any]
    ),
    *,
    reason: str,
) -> ImplementationStepExecution:
    execution = load_step_execution(state)

    step_id = execution.current_step_id

    if step_id is None:
        raise ImplementationStepStateError(
            "Block対象のCurrent Stepがありません。"
        )

    result = execution.results.get(step_id)

    if result is None:
        raise ImplementationStepStateError(
            f"Step Resultがありません: {step_id}"
        )

    result.status = "BLOCKED"
    result.error = reason
    result.completed_at = _now()

    if step_id not in execution.blocked_step_ids:
        execution.blocked_step_ids.append(
            step_id
        )

    return execution
