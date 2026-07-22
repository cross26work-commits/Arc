from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.missions.repair_context_builder import (
    REPAIR_PLAN_ROOT,
    build_repair_context_safe,
)
from app.missions.repair_edit_connector import (
    connect_repair_edit_safe,
)
from app.missions.repair_edit_generator import (
    generate_repair_edit_safe,
)
from app.missions.repair_patch_apply import (
    apply_repair_patch_safe,
)
from app.missions.repair_patch_connector import (
    connect_repair_request_to_patch_generator_safe,
)
from app.missions.repair_verification_runner import (
    run_repair_verification_safe,
)
from app.missions.retry_controller import (
    prepare_repair_retry_safe,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairCycleOrchestratorError(Exception):
    """Repair Cycle進行管理失敗時の例外。"""


REPAIR_CYCLE_ORCHESTRATOR_VERSION = (
    "mission-repair-cycle-orchestrator-v0.1"
)

MAX_STEP_HISTORY = 100

TERMINAL_STATUSES = {
    "REPAIR_VERIFIED",
    "COMPLETED",
}

RETRY_STATUSES = {
    "REPAIR_FAILED",
}

PATCH_CHECK_STATUSES = {
    "AWAITING_REPAIR_PATCH_CHECK",
}

PATCH_APPLY_STATUSES = {
    "PATCH_CHECKED",
    "READY",
    "APPLY_PATCH",
}

VERIFY_STATUSES = {
    "PATCH_APPLIED",
}

BLOCKED_STATUSES = {
    "PATCH_APPLY_FAILED",
    "PATCH_GENERATION_FAILED",
    "REPAIR_VERIFICATION_ERROR",
}

REPAIR_REQUEST_STATUSES = {
    "AWAITING_REPAIR_REQUEST",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_json(
    value: dict[str, Any],
) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        canonical
    ).hexdigest()


def _mission_directory(
    mission_id: int,
) -> Path:
    return (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
    )


def _load_json(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(value, dict):
        return None

    return value


def _write_json_atomic(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def _repair_request(
    mission_id: int,
) -> dict[str, Any] | None:
    return _load_json(
        _mission_directory(mission_id)
        / "repair-request.json"
    )


def _repair_context(
    mission_id: int,
) -> dict[str, Any] | None:
    return _load_json(
        _mission_directory(mission_id)
        / "repair-context.json"
    )


def _repair_edit_draft(
    mission_id: int,
) -> dict[str, Any] | None:
    return _load_json(
        _mission_directory(mission_id)
        / "repair-edit-draft.json"
    )


def _repair_connection(
    mission_id: int,
) -> dict[str, Any] | None:
    return _load_json(
        _mission_directory(mission_id)
        / "repair-edit-connection.json"
    )


def _status(
    request: dict[str, Any] | None,
) -> str | None:
    if not isinstance(request, dict):
        return None

    value = request.get("status")

    if not isinstance(value, str):
        return None

    normalized = value.strip().upper()

    return normalized or None


def _context_matches_request(
    *,
    context: dict[str, Any] | None,
    request: dict[str, Any],
) -> bool:
    if not isinstance(context, dict):
        return False

    if (
        context.get("mission_id")
        != request.get("mission_id")
    ):
        return False

    context_request = context.get(
        "repair_request"
    )

    if not isinstance(
        context_request,
        dict,
    ):
        return False

    request_id = request.get(
        "request_id"
    )

    context_request_id = (
        context_request.get("request_id")
    )

    if (
        isinstance(request_id, str)
        and isinstance(
            context_request_id,
            str,
        )
    ):
        return request_id == context_request_id

    return True


def _draft_matches_context(
    *,
    draft: dict[str, Any] | None,
    context: dict[str, Any],
) -> bool:
    if not isinstance(draft, dict):
        return False

    return (
        draft.get("context_id")
        == context.get("context_id")
    )


def _connection_matches_draft(
    *,
    connection: dict[str, Any] | None,
    draft: dict[str, Any],
) -> bool:
    if not isinstance(connection, dict):
        return False

    return (
        connection.get("draft_id")
        == draft.get("draft_id")
    )


def _load_history(
    mission_id: int,
) -> list[dict[str, Any]]:
    data = _load_json(
        _mission_directory(mission_id)
        / "repair-cycle-state.json"
    )

    if not isinstance(data, dict):
        return []

    history = data.get("history")

    if not isinstance(history, list):
        return []

    return [
        item
        for item in history
        if isinstance(item, dict)
    ][-MAX_STEP_HISTORY:]


def _save_cycle_state(
    *,
    mission_id: int,
    step_record: dict[str, Any],
) -> Path:
    mission_dir = _mission_directory(
        mission_id
    )

    state_path = (
        mission_dir
        / "repair-cycle-state.json"
    )

    history = _load_history(
        mission_id
    )

    history.append(step_record)

    history = history[
        -MAX_STEP_HISTORY:
    ]

    state = {
        "orchestrator_version": (
            REPAIR_CYCLE_ORCHESTRATOR_VERSION
        ),
        "mission_id": mission_id,
        "updated_at": _now(),
        "last_step": step_record,
        "history": history,
    }

    _write_json_atomic(
        state_path,
        state,
    )

    return state_path


def _step_signature(
    *,
    mission_id: int,
    stage: str,
    request: dict[str, Any] | None,
    context: dict[str, Any] | None,
    draft: dict[str, Any] | None,
) -> str:
    payload = {
        "mission_id": mission_id,
        "stage": stage,
        "request_id": (
            request.get("request_id")
            if isinstance(request, dict)
            else None
        ),
        "request_status": _status(request),
        "context_id": (
            context.get("context_id")
            if isinstance(context, dict)
            else None
        ),
        "draft_id": (
            draft.get("draft_id")
            if isinstance(draft, dict)
            else None
        ),
        "retry_count": (
            request.get("retry_count")
            if isinstance(request, dict)
            else None
        ),
    }

    return _sha256_json(payload)


def _last_step_is_duplicate(
    *,
    mission_id: int,
    signature: str,
) -> bool:
    history = _load_history(
        mission_id
    )

    if not history:
        return False

    last = history[-1]

    return (
        last.get("step_signature")
        == signature
        and last.get("outcome")
        == "COMPLETED"
    )


def _determine_stage(
    *,
    mission_id: int,
    request: dict[str, Any] | None,
    context: dict[str, Any] | None,
    draft: dict[str, Any] | None,
    connection: dict[str, Any] | None,
) -> tuple[str, str]:
    if request is None:
        raise MissionRepairCycleOrchestratorError(
            "Repair Requestが存在しません。"
        )

    request_status = _status(request)

    if request_status is None:
        raise MissionRepairCycleOrchestratorError(
            "Repair Request Statusが不正です。"
        )

    if request_status in TERMINAL_STATUSES:
        return (
            "CYCLE_COMPLETED",
            "Repair Cycleは完了済みです。",
        )

    if request_status in BLOCKED_STATUSES:
        return (
            "STATE_BLOCKED",
            (
                "自動進行できない失敗状態です。"
                f" status={request_status}"
            ),
        )

    if request_status in RETRY_STATUSES:
        return (
            "PREPARE_RETRY",
            "失敗したRepair Cycleを再試行準備します。",
        )

    if request_status in REPAIR_REQUEST_STATUSES:
        if not _context_matches_request(
            context=context,
            request=request,
        ):
            return (
                "BUILD_CONTEXT",
                "最新Repair Request用Contextを構築します。",
            )

        assert context is not None

        if not _draft_matches_context(
            draft=draft,
            context=context,
        ):
            return (
                "GENERATE_EDIT",
                "Repair ContextからEdit Draftを生成します。",
            )

        assert draft is not None

        draft_status = draft.get(
            "status"
        )

        if draft_status == "INSUFFICIENT_CONTEXT":
            return (
                "STATE_BLOCKED",
                (
                    "安全なRepair Editを生成できません。"
                    " HumanまたはAIレビューが必要です。"
                ),
            )

        if draft_status != "EDIT_READY":
            return (
                "STATE_BLOCKED",
                (
                    "未対応のRepair Edit Draft状態です。"
                    f" status={draft_status}"
                ),
            )

        if not _connection_matches_draft(
            connection=connection,
            draft=draft,
        ):
            return (
                "CONNECT_EDIT",
                "Edit DraftをPatch Check経路へ接続します。",
            )

        return (
            "CONNECT_EDIT",
            (
                "接続記録は存在しますが、"
                "Repair Request状態が更新されていないため"
                "安全な重複接続を実行します。"
            ),
        )

    if request_status in PATCH_CHECK_STATUSES:
        return (
            "GENERATE_PATCH",
            "既存Patch GeneratorとPatch Checkへ接続します。",
        )

    if request_status in PATCH_APPLY_STATUSES:
        return (
            "APPLY_PATCH",
            "Patch Check済みRepair Patchを適用します。",
        )

    if request_status in VERIFY_STATUSES:
        return (
            "VERIFY_REPAIR",
            "適用済みRepair Patchを検証します。",
        )

    if request_status == "VERIFYING":
        return (
            "VERIFY_REPAIR",
            "中断されたRepair Verificationを再実行します。",
        )

    return (
        "STATE_BLOCKED",
        (
            "未対応のRepair Request状態です。"
            f" status={request_status}"
        ),
    )


def _execute_stage(
    *,
    mission_id: int,
    stage: str,
) -> dict[str, Any]:
    handlers: dict[
        str,
        Callable[[], dict[str, Any]],
    ] = {
        "BUILD_CONTEXT": (
            lambda: build_repair_context_safe(
                mission_id
            )
        ),
        "GENERATE_EDIT": (
            lambda: generate_repair_edit_safe(
                mission_id
            )
        ),
        "CONNECT_EDIT": (
            lambda: connect_repair_edit_safe(
                mission_id
            )
        ),
        "GENERATE_PATCH": (
            lambda: (
                connect_repair_request_to_patch_generator_safe(
                    mission_id
                )
            )
        ),
        "APPLY_PATCH": (
            lambda: apply_repair_patch_safe(
                mission_id=mission_id,
                decided_by=(
                    REPAIR_CYCLE_ORCHESTRATOR_VERSION
                ),
                note=(
                    "Repair Cycle Orchestrator "
                    "v0.1 single-stage execution"
                ),
            )
        ),
        "VERIFY_REPAIR": (
            lambda: run_repair_verification_safe(
                mission_id
            )
        ),
        "PREPARE_RETRY": (
            lambda: prepare_repair_retry_safe(
                mission_id=mission_id,
                max_retries=None,
            )
        ),
    }

    handler = handlers.get(stage)

    if handler is None:
        raise MissionRepairCycleOrchestratorError(
            f"実行不能なStageです: {stage}"
        )

    return handler()


def run_repair_cycle_step(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    request_before = _repair_request(
        mission_id
    )

    context_before = _repair_context(
        mission_id
    )

    draft_before = _repair_edit_draft(
        mission_id
    )

    connection_before = (
        _repair_connection(
            mission_id
        )
    )

    stage, reason = _determine_stage(
        mission_id=mission_id,
        request=request_before,
        context=context_before,
        draft=draft_before,
        connection=connection_before,
    )

    signature = _step_signature(
        mission_id=mission_id,
        stage=stage,
        request=request_before,
        context=context_before,
        draft=draft_before,
    )

    if stage == "CYCLE_COMPLETED":
        return {
            "mission": mission,
            "orchestrator_version": (
                REPAIR_CYCLE_ORCHESTRATOR_VERSION
            ),
            "stage": stage,
            "executed": False,
            "duplicate": False,
            "outcome": "COMPLETED",
            "reason": reason,
            "request_status_before": (
                _status(request_before)
            ),
            "request_status_after": (
                _status(request_before)
            ),
            "next_action": None,
        }

    if stage == "STATE_BLOCKED":
        step_record = {
            "step_id": (
                "repair-cycle-step-"
                + signature[:16]
            ),
            "step_signature": signature,
            "created_at": _now(),
            "stage": stage,
            "executed": False,
            "duplicate": False,
            "outcome": "BLOCKED",
            "reason": reason,
            "request_status_before": (
                _status(request_before)
            ),
            "request_status_after": (
                _status(request_before)
            ),
        }

        state_path = _save_cycle_state(
            mission_id=mission_id,
            step_record=step_record,
        )

        add_mission_log(
            mission_id=mission_id,
            level="WARNING",
            event_type=(
                "MISSION_REPAIR_CYCLE_BLOCKED"
            ),
            message=reason,
            metadata={
                "orchestrator_version": (
                    REPAIR_CYCLE_ORCHESTRATOR_VERSION
                ),
                "stage": stage,
                "step_id": step_record[
                    "step_id"
                ],
                "request_status": (
                    _status(request_before)
                ),
                "auto_apply": False,
            },
        )

        return {
            "mission": mission,
            "orchestrator_version": (
                REPAIR_CYCLE_ORCHESTRATOR_VERSION
            ),
            **step_record,
            "state_path": str(state_path),
            "next_action": (
                "HUMAN_OR_AI_REVIEW_REQUIRED"
            ),
        }

    duplicate = _last_step_is_duplicate(
        mission_id=mission_id,
        signature=signature,
    )

    if duplicate:
        return {
            "mission": mission,
            "orchestrator_version": (
                REPAIR_CYCLE_ORCHESTRATOR_VERSION
            ),
            "stage": stage,
            "executed": False,
            "duplicate": True,
            "outcome": "NO_OP",
            "reason": (
                "同一入力状態のStageは"
                "すでに正常実行済みです。"
            ),
            "request_status_before": (
                _status(request_before)
            ),
            "request_status_after": (
                _status(request_before)
            ),
            "next_action": (
                "REFRESH_STATE"
            ),
        }

    result = _execute_stage(
        mission_id=mission_id,
        stage=stage,
    )

    request_after = _repair_request(
        mission_id
    )

    context_after = _repair_context(
        mission_id
    )

    draft_after = _repair_edit_draft(
        mission_id
    )

    connection_after = (
        _repair_connection(
            mission_id
        )
    )

    try:
        next_stage, next_reason = (
            _determine_stage(
                mission_id=mission_id,
                request=request_after,
                context=context_after,
                draft=draft_after,
                connection=connection_after,
            )
        )
    except MissionRepairCycleOrchestratorError:
        next_stage = "STATE_REFRESH_REQUIRED"
        next_reason = (
            "実行後状態を確定できませんでした。"
        )

    completed_at = _now()

    step_record = {
        "step_id": (
            "repair-cycle-step-"
            + _sha256_json(
                {
                    "signature": signature,
                    "completed_at": completed_at,
                }
            )[:16]
        ),
        "step_signature": signature,
        "created_at": completed_at,
        "stage": stage,
        "executed": True,
        "duplicate": False,
        "outcome": "COMPLETED",
        "reason": reason,
        "request_status_before": (
            _status(request_before)
        ),
        "request_status_after": (
            _status(request_after)
        ),
        "next_stage": next_stage,
        "next_reason": next_reason,
    }

    state_path = _save_cycle_state(
        mission_id=mission_id,
        step_record=step_record,
    )

    add_mission_log(
        mission_id=mission_id,
        level="INFO",
        event_type=(
            "MISSION_REPAIR_CYCLE_STEP_COMPLETED"
        ),
        message=(
            f"Repair Cycle Stage "
            f"{stage}を完了しました。"
        ),
        metadata={
            "orchestrator_version": (
                REPAIR_CYCLE_ORCHESTRATOR_VERSION
            ),
            "step_id": step_record[
                "step_id"
            ],
            "stage": stage,
            "next_stage": next_stage,
            "request_status_before": (
                _status(request_before)
            ),
            "request_status_after": (
                _status(request_after)
            ),
            "auto_apply": False,
        },
    )

    return {
        "mission": mission,
        "orchestrator_version": (
            REPAIR_CYCLE_ORCHESTRATOR_VERSION
        ),
        **step_record,
        "result": result,
        "state_path": str(state_path),
        "single_stage_only": True,
        "auto_apply": False,
    }


def run_repair_cycle_step_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return run_repair_cycle_step(
            mission_id
        )
    except (
        MissionRepairCycleOrchestratorError,
        MissionError,
    ):
        raise
