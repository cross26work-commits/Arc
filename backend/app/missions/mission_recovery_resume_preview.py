from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.missions.mission_recovery import (
    MissionRecoveryError,
    inspect_mission_recovery_safe,
)


class MissionRecoveryResumePreviewError(Exception):
    """Mission Recovery Resume Previewの判定失敗。"""


MISSION_RECOVERY_RESUME_PREVIEW_VERSION = (
    "mission-recovery-resume-preview-v0.1"
)


ACTION_PREVIEW_MAP: dict[
    str,
    dict[str, Any],
] = {
    "APPROVE_MISSION": {
        "resume_handler": "approve_mission",
        "resume_endpoint": (
            "/missions/{mission_id}/approve-and-resume"
        ),
        "http_method": "POST",
        "next_expected_stage": (
            "RUN_IMPLEMENTATION_DRY_RUN"
        ),
        "requires_master_action": True,
        "would_change_database": True,
        "would_change_project_files": False,
        "would_change_git": False,
        "dangerous_action": False,
    },
    "APPLY_PATCH": {
        "resume_handler": (
            "apply_mission_implementation_patch_safe"
        ),
        "resume_endpoint": (
            "/missions/{mission_id}/approve-and-resume"
        ),
        "http_method": "POST",
        "next_expected_stage": (
            "RUN_VERIFICATION"
        ),
        "intermediate_state": "PATCH_APPLIED",
        "requires_master_action": True,
        "would_change_database": True,
        "would_change_project_files": True,
        "would_change_git": True,
        "dangerous_action": True,
    },
    "RUN_VERIFICATION": {
        "resume_handler": (
            "run_mission_verification_safe"
        ),
        "resume_endpoint": (
            "/missions/{mission_id}/cycle"
        ),
        "http_method": "POST",
        "next_expected_stage": (
            "WAIT_COMMIT_APPROVAL"
        ),
        "requires_master_action": False,
        "would_change_database": True,
        "would_change_project_files": False,
        "would_change_git": False,
        "dangerous_action": False,
    },
    "COMMIT_CHANGES": {
        "resume_handler": (
            "commit_mission_changes_safe"
        ),
        "resume_endpoint": (
            "/missions/{mission_id}/approve-and-resume"
        ),
        "http_method": "POST",
        "next_expected_stage": (
            "RUN_REPORTING"
        ),
        "intermediate_state": "COMMITTED",
        "requires_master_action": True,
        "would_change_database": True,
        "would_change_project_files": False,
        "would_change_git": True,
        "dangerous_action": True,
    },
    "RUN_REPORTING": {
        "resume_handler": (
            "run_mission_reporting_safe"
        ),
        "resume_endpoint": (
            "/missions/{mission_id}/cycle"
        ),
        "http_method": "POST",
        "next_expected_stage": (
            "MISSION_COMPLETED"
        ),
        "requires_master_action": False,
        "would_change_database": True,
        "would_change_project_files": False,
        "would_change_git": False,
        "dangerous_action": False,
    },
    "REVIEW_FINAL_REPORT": {
        "resume_handler": None,
        "resume_endpoint": (
            "/missions/{mission_id}"
        ),
        "http_method": "GET",
        "next_expected_stage": (
            "MISSION_COMPLETED"
        ),
        "requires_master_action": False,
        "would_change_database": False,
        "would_change_project_files": False,
        "would_change_git": False,
        "dangerous_action": False,
    },
}


def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _build_preconditions(
    *,
    recovery: dict[str, Any],
    action: str,
) -> list[dict[str, Any]]:
    preconditions = [
        {
            "name": "RECOVERY_STATE_CONSISTENT",
            "satisfied": (
                recovery.get(
                    "state_consistent"
                )
                is True
            ),
        },
        {
            "name": "RECOVERY_ERROR_FREE",
            "satisfied": (
                recovery.get(
                    "error_count"
                )
                == 0
            ),
        },
        {
            "name": "RECOVERABLE",
            "satisfied": (
                recovery.get(
                    "recoverable"
                )
                is True
            ),
        },
        {
            "name": "SAFE_TO_RESUME",
            "satisfied": (
                recovery.get(
                    "safe_to_resume"
                )
                is True
            ),
        },
    ]

    if action == "APPLY_PATCH":
        patch = recovery.get("patch")
        backup = recovery.get("backup")
        backup_files = recovery.get(
            "backup_files"
        )
        git = recovery.get("git")

        if not isinstance(patch, dict):
            patch = {}

        if not isinstance(backup, dict):
            backup = {}

        if not isinstance(
            backup_files,
            dict,
        ):
            backup_files = {}

        if not isinstance(git, dict):
            git = {}

        preconditions.extend(
            [
                {
                    "name": "PATCH_VALID",
                    "satisfied": (
                        patch.get("valid")
                        is True
                    ),
                },
                {
                    "name": "PATCH_NOT_APPLIED",
                    "satisfied": (
                        patch.get("applied")
                        is not True
                    ),
                },
                {
                    "name": "BACKUP_VALID",
                    "satisfied": (
                        backup.get("valid")
                        is True
                    ),
                },
                {
                    "name": "BACKUP_FILES_VALID",
                    "satisfied": (
                        backup_files.get(
                            "valid"
                        )
                        is True
                    ),
                },
                {
                    "name": "GIT_STATE_VALID",
                    "satisfied": (
                        git.get("valid")
                        is True
                    ),
                },
                {
                    "name": "WORKING_TREE_CLEAN",
                    "satisfied": (
                        git.get(
                            "working_tree_clean"
                        )
                        is True
                    ),
                },
            ]
        )

    if action == "COMMIT_CHANGES":
        verification = recovery.get(
            "verification"
        )

        if not isinstance(
            verification,
            dict,
        ):
            verification = {}

        preconditions.append(
            {
                "name": "VERIFICATION_PASSED",
                "satisfied": (
                    verification.get("passed")
                    is True
                ),
            }
        )

    return preconditions


def preview_mission_recovery_resume(
    *,
    mission_id: int,
) -> dict[str, Any]:
    recovery = inspect_mission_recovery_safe(
        mission_id=mission_id
    )

    action = str(
        recovery.get("required_action")
        or ""
    ).strip().upper()

    current_stage = str(
        recovery.get("current_stage")
        or ""
    ).strip().upper()

    action_preview = ACTION_PREVIEW_MAP.get(
        action
    )

    blockers: list[str] = []

    if action_preview is None:
        blockers.append(
            f"UNSUPPORTED_RECOVERY_ACTION:{action}"
        )

        action_preview = {
            "resume_handler": None,
            "resume_endpoint": None,
            "http_method": None,
            "next_expected_stage": None,
            "requires_master_action": (
                recovery.get(
                    "requires_master_action"
                )
                is True
            ),
            "would_change_database": False,
            "would_change_project_files": False,
            "would_change_git": False,
            "dangerous_action": False,
        }

    preconditions = _build_preconditions(
        recovery=recovery,
        action=action,
    )

    failed_preconditions = [
        item["name"]
        for item in preconditions
        if item.get("satisfied") is not True
    ]

    blockers.extend(
        f"PRECONDITION_FAILED:{name}"
        for name in failed_preconditions
    )

    if (
        recovery.get("state_consistent")
        is not True
    ):
        blockers.append(
            "RECOVERY_STATE_INCONSISTENT"
        )

    if (
        recovery.get("safe_to_resume")
        is not True
    ):
        blockers.append(
            "RECOVERY_NOT_SAFE_TO_RESUME"
        )

    if recovery.get("error_count") != 0:
        blockers.append(
            "RECOVERY_ERRORS_PRESENT"
        )

    blockers = list(
        dict.fromkeys(blockers)
    )

    preview_valid = not blockers

    expected_patch_sha256 = None

    patch = recovery.get("patch")
    implementation = recovery.get(
        "implementation"
    )

    patch_hash_candidates: list[Any] = []

    if isinstance(patch, dict):
        patch_hash_candidates.extend(
            [
                patch.get("sha256"),
                patch.get("patch_sha256"),
                patch.get(
                    "expected_patch_sha256"
                ),
                patch.get(
                    "expected_sha256"
                ),
                patch.get(
                    "actual_sha256"
                ),
            ]
        )

        patch_metadata = patch.get(
            "metadata"
        )

        if isinstance(
            patch_metadata,
            dict,
        ):
            patch_hash_candidates.extend(
                [
                    patch_metadata.get(
                        "sha256"
                    ),
                    patch_metadata.get(
                        "patch_sha256"
                    ),
                    patch_metadata.get(
                        "expected_sha256"
                    ),
                    patch_metadata.get(
                        "actual_sha256"
                    ),
                ]
            )

        patch_check = patch.get(
            "patch_check"
        )

        if isinstance(
            patch_check,
            dict,
        ):
            patch_hash_candidates.extend(
                [
                    patch_check.get(
                        "patch_sha256"
                    ),
                    patch_check.get(
                        "sha256"
                    ),
                ]
            )

    if isinstance(
        implementation,
        dict,
    ):
        implementation_patch = (
            implementation.get("patch")
        )

        if isinstance(
            implementation_patch,
            dict,
        ):
            patch_hash_candidates.extend(
                [
                    implementation_patch.get(
                        "sha256"
                    ),
                    implementation_patch.get(
                        "patch_sha256"
                    ),
                ]
            )

    for candidate in patch_hash_candidates:
        if (
            isinstance(candidate, str)
            and len(candidate) == 64
        ):
            expected_patch_sha256 = (
                candidate
            )
            break

    if (
        action == "APPLY_PATCH"
        and expected_patch_sha256 is None
    ):
        blockers.append(
            "EXPECTED_PATCH_SHA256_MISSING"
        )

        preview_valid = False

    return {
        "preview_version": (
            MISSION_RECOVERY_RESUME_PREVIEW_VERSION
        ),
        "previewed_at": _now(),
        "mission_id": mission_id,
        "current_stage": current_stage,
        "required_action": action,
        "resume_handler": (
            action_preview.get(
                "resume_handler"
            )
        ),
        "resume_endpoint": (
            action_preview.get(
                "resume_endpoint"
            )
        ),
        "http_method": (
            action_preview.get(
                "http_method"
            )
        ),
        "next_expected_stage": (
            action_preview.get(
                "next_expected_stage"
            )
        ),
        "intermediate_state": (
            action_preview.get(
                "intermediate_state"
            )
        ),
        "requires_master_action": (
            action_preview.get(
                "requires_master_action"
            )
            is True
        ),
        "dangerous_action": (
            action_preview.get(
                "dangerous_action"
            )
            is True
        ),
        "execution_allowed": False,
        "preview_valid": preview_valid,
        "expected_patch_sha256": (
            expected_patch_sha256
        ),
        "preconditions": preconditions,
        "failed_preconditions": (
            failed_preconditions
        ),
        "blockers": blockers,
        "effects_if_executed": {
            "would_change_database": (
                action_preview.get(
                    "would_change_database"
                )
                is True
            ),
            "would_change_project_files": (
                action_preview.get(
                    "would_change_project_files"
                )
                is True
            ),
            "would_change_git": (
                action_preview.get(
                    "would_change_git"
                )
                is True
            ),
        },
        "recovery_summary": {
            "recoverable": (
                recovery.get("recoverable")
                is True
            ),
            "safe_to_resume": (
                recovery.get(
                    "safe_to_resume"
                )
                is True
            ),
            "state_consistent": (
                recovery.get(
                    "state_consistent"
                )
                is True
            ),
            "error_count": recovery.get(
                "error_count"
            ),
            "errors": recovery.get(
                "errors",
                [],
            ),
        },
        "safety": {
            "preview_only": True,
            "read_only": True,
            "execution_performed": False,
            "mission_changed": False,
            "database_changed": False,
            "project_files_changed": False,
            "git_changed": False,
            "patch_apply_executed": False,
            "verification_executed": False,
            "commit_executed": False,
            "reporting_executed": False,
            "automatic_recovery": False,
            "automatic_master_approval": False,
        },
    }


def preview_mission_recovery_resume_safe(
    *,
    mission_id: int,
) -> dict[str, Any]:
    try:
        return preview_mission_recovery_resume(
            mission_id=mission_id
        )
    except MissionRecoveryError:
        raise
    except MissionRecoveryResumePreviewError:
        raise
    except Exception as error:
        raise MissionRecoveryResumePreviewError(
            "Mission Recovery Resume Previewに"
            "失敗しました。"
            f" detail={error}"
        ) from error
