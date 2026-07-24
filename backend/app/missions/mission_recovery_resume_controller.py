from __future__ import annotations

from typing import Any

from app.missions.mission_approval_resume_runner import (
    MissionApprovalResumeError,
    approve_and_resume_mission_safe,
    preview_mission_approval_resume_safe,
)
from app.missions.mission_recovery import (
    MissionRecoveryError,
)
from app.missions.mission_recovery_resume_preview import (
    MissionRecoveryResumePreviewError,
    preview_mission_recovery_resume_safe,
)
from app.missions.models import (
    MissionApprovalResumeRequest,
    MissionRecoveryResumeRequest,
)
from app.missions.service import (
    MissionError,
)


class MissionRecoveryResumeControllerError(
    Exception
):
    """Mission Recovery再開制御の失敗。"""


MISSION_RECOVERY_RESUME_CONTROLLER_VERSION = (
    "mission-recovery-resume-controller-v0.1"
)


def _normalize_required(
    value: str,
    *,
    field_name: str,
) -> str:
    normalized = value.strip().upper()

    if not normalized:
        raise MissionRecoveryResumeControllerError(
            f"{field_name}が空です。"
        )

    return normalized


def _normalize_optional(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip()

    return normalized or None


def _validate_recovery_preview(
    *,
    preview: dict[str, Any],
) -> None:
    if preview.get("preview_valid") is not True:
        raise MissionRecoveryResumeControllerError(
            "Recovery Previewが有効ではありません。"
        )

    blockers = preview.get("blockers")

    if not isinstance(blockers, list):
        raise MissionRecoveryResumeControllerError(
            "Recovery PreviewのBlocker情報が"
            "不正です。"
        )

    if blockers:
        raise MissionRecoveryResumeControllerError(
            "Recovery再開を妨げるBlockerが"
            "存在します: "
            + ", ".join(
                str(item)
                for item in blockers
            )
        )

    # Recovery Resume Previewは、
    # Recovery Inspectorの判定を集約して
    # preview_valid / blockersを返す。
    #
    # safe_to_resume / recoverableはPreviewの
    # バージョンによってトップレベルに
    # 含まれない場合があるため、
    # 明示的にFalseの場合だけ拒否する。
    safe_to_resume = preview.get(
        "safe_to_resume"
    )

    if safe_to_resume is False:
        raise MissionRecoveryResumeControllerError(
            "Recovery Inspectorが"
            "安全な再開を許可していません。"
        )

    recoverable = preview.get(
        "recoverable"
    )

    if recoverable is False:
        raise MissionRecoveryResumeControllerError(
            "MissionはRecovery可能ではありません。"
        )


def _build_approval_request(
    *,
    payload: MissionRecoveryResumeRequest,
    action: str,
) -> MissionApprovalResumeRequest:
    return MissionApprovalResumeRequest(
        action=action,
        reason=_normalize_optional(
            payload.reason
        ),
        decided_by=payload.decided_by,
        expected_patch_sha256=(
            _normalize_optional(
                payload.expected_patch_sha256
            )
        ),
        commit_message=_normalize_optional(
            payload.commit_message
        ),
        note=_normalize_optional(
            payload.note
        ),
        continue_cycle=payload.continue_cycle,
        max_steps=payload.max_steps,
    )


def resume_mission_recovery(
    *,
    mission_id: int,
    payload: MissionRecoveryResumeRequest,
) -> dict[str, Any]:
    """
    Recovery PreviewとApproval Previewを再検証し、
    明示承認された操作だけを既存Runnerへ委譲する。
    """

    if payload.approved is not True:
        raise MissionRecoveryResumeControllerError(
            "Recovery再開にはapproved=trueの"
            "明示承認が必要です。"
        )

    recovery_preview = (
        preview_mission_recovery_resume_safe(
            mission_id=mission_id
        )
    )

    _validate_recovery_preview(
        preview=recovery_preview
    )

    requested_action = _normalize_required(
        payload.action,
        field_name="action",
    )

    required_action = _normalize_required(
        str(
            recovery_preview.get(
                "required_action"
            )
            or ""
        ),
        field_name="required_action",
    )

    if requested_action != required_action:
        raise MissionRecoveryResumeControllerError(
            "指定ActionがRecoveryで要求されている"
            "Actionと一致しません。"
            f" requested={requested_action}"
            f" required={required_action}"
        )

    expected_stage = _normalize_required(
        payload.expected_current_stage,
        field_name="expected_current_stage",
    )

    current_stage = _normalize_required(
        str(
            recovery_preview.get(
                "current_stage"
            )
            or ""
        ),
        field_name="current_stage",
    )

    if expected_stage != current_stage:
        raise MissionRecoveryResumeControllerError(
            "確認済みStageと現在Stageが"
            "一致しません。"
            f" expected={expected_stage}"
            f" current={current_stage}"
        )

    if requested_action == "APPLY_PATCH":
        stored_hash = _normalize_optional(
            recovery_preview.get(
                "expected_patch_sha256"
            )
        )

        supplied_hash = _normalize_optional(
            payload.expected_patch_sha256
        )

        if stored_hash is None:
            raise MissionRecoveryResumeControllerError(
                "Recovery PreviewにPatch Hashが"
                "存在しません。"
            )

        if supplied_hash is None:
            raise MissionRecoveryResumeControllerError(
                "APPLY_PATCHには"
                "expected_patch_sha256が必要です。"
            )

        if supplied_hash != stored_hash:
            raise MissionRecoveryResumeControllerError(
                "指定Patch HashがRecovery Previewの"
                "Hashと一致しません。"
            )

    approval_request = _build_approval_request(
        payload=payload,
        action=requested_action,
    )

    approval_preview = (
        preview_mission_approval_resume_safe(
            mission_id=mission_id,
            payload=approval_request,
        )
    )

    if approval_preview.get("valid") is not True:
        raise MissionRecoveryResumeControllerError(
            "Approval Resume Previewが"
            "有効ではありません。"
        )

    approval_stage = _normalize_required(
        str(
            approval_preview.get("stage")
            or ""
        ),
        field_name="approval_stage",
    )

    if approval_stage != current_stage:
        raise MissionRecoveryResumeControllerError(
            "Recovery PreviewとApproval Previewの"
            "Stageが一致しません。"
        )

    approval_action = _normalize_required(
        str(
            approval_preview.get("action")
            or ""
        ),
        field_name="approval_action",
    )

    if approval_action != requested_action:
        raise MissionRecoveryResumeControllerError(
            "Recovery ActionとApproval Actionが"
            "一致しません。"
        )

    # 実行直前の最終Stage・Hash検証は、
    # approve_and_resume_mission_safe() 内でも
    # 再実行される。
    execution_result = (
        approve_and_resume_mission_safe(
            mission_id=mission_id,
            payload=approval_request,
        )
    )

    return {
        "controller_version": (
            MISSION_RECOVERY_RESUME_CONTROLLER_VERSION
        ),
        "mission_id": mission_id,
        "approved": True,
        "action": requested_action,
        "confirmed_stage": current_stage,
        "expected_patch_sha256": (
            approval_preview.get(
                "expected_patch_sha256"
            )
        ),
        "recovery_preview_version": (
            recovery_preview.get(
                "preview_version"
            )
        ),
        "approval_preview_version": (
            approval_preview.get(
                "preview_version"
            )
        ),
        "delegated_to": (
            "approve_and_resume_mission_safe"
        ),
        "execution_result": execution_result,
        "safety": {
            "explicit_approval_required": True,
            "recovery_preview_rechecked": True,
            "stage_rechecked": True,
            "action_rechecked": True,
            "patch_hash_rechecked": (
                requested_action
                == "APPLY_PATCH"
            ),
            "approval_preview_rechecked": True,
            "controller_direct_patch_apply": False,
            "controller_direct_commit": False,
            "controller_direct_database_write": False,
            "existing_runner_delegation_only": True,
        },
    }


def resume_mission_recovery_safe(
    *,
    mission_id: int,
    payload: MissionRecoveryResumeRequest,
) -> dict[str, Any]:
    try:
        return resume_mission_recovery(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionRecoveryResumeControllerError:
        raise
    except (
        MissionRecoveryError,
        MissionRecoveryResumePreviewError,
        MissionApprovalResumeError,
        MissionError,
    ) as error:
        raise MissionRecoveryResumeControllerError(
            str(error)
        ) from error
