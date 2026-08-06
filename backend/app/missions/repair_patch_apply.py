from __future__ import annotations

from typing import Any

from app.missions.failure_classifier import (
    classify_patch_failure,
    serialize_failure_classification,
)
from app.missions.implementation_runner import (
    MissionImplementationError,
    apply_mission_implementation_patch_safe,
)
from app.missions.models import (
    MissionPatchApplyRequest,
)
from app.missions.repair_request_builder import (
    REPAIR_PLAN_ROOT,
    _latest_request_path,
    _load_existing_request,
    _write_json_atomic,
)
from app.missions.self_repair_planner import (
    ARC_ROOT,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairPatchApplyError(Exception):
    """Repair Patch Applyの実行失敗時に使用する例外。"""


REPAIR_PATCH_APPLY_VERSION = (
    "mission-repair-patch-apply-v0.3"
)


def _task_by_type(
    mission: dict[str, Any],
    task_type: str,
) -> dict[str, Any]:
    task = next(
        (
            item
            for item in mission.get("tasks", [])
            if item.get("task_type") == task_type
        ),
        None,
    )

    if task is None:
        raise MissionRepairPatchApplyError(
            f"{task_type} Taskが見つかりません。"
        )

    return task


def _validate_repair_request(
    *,
    mission_id: int,
    repair_request: dict[str, Any],
) -> str:
    if repair_request.get("mission_id") != mission_id:
        raise MissionRepairPatchApplyError(
            "Repair RequestのMission IDが一致しません。"
        )

    if repair_request.get("status") == "PATCH_APPLIED":
        raise MissionRepairPatchApplyError(
            "Repair Patchは既に適用済みです。"
        )

    if repair_request.get("status") != "PATCH_CHECKED":
        raise MissionRepairPatchApplyError(
            "Patch Check済みRepair Requestのみ"
            "適用できます。"
        )

    if repair_request.get("patch_generated") is not True:
        raise MissionRepairPatchApplyError(
            "Repair Patchが生成されていません。"
        )

    if repair_request.get("patch_checked") is not True:
        raise MissionRepairPatchApplyError(
            "Repair Patch Checkが完了していません。"
        )

    if repair_request.get("patch_applied") is True:
        raise MissionRepairPatchApplyError(
            "Repair Patchは既に適用済みです。"
        )

    if repair_request.get("auto_apply") is not False:
        raise MissionRepairPatchApplyError(
            "Repair Requestのauto_applyが"
            "安全状態ではありません。"
        )

    patch_result = repair_request.get(
        "patch_result"
    )

    if not isinstance(patch_result, dict):
        raise MissionRepairPatchApplyError(
            "Repair Patch結果が保存されていません。"
        )

    if patch_result.get("patch_applicable") is not True:
        raise MissionRepairPatchApplyError(
            "適用可能と確認されていないPatchです。"
        )

    if (
        patch_result.get("implementation_mode")
        != "PATCH_CHECKED"
    ):
        raise MissionRepairPatchApplyError(
            "Repair Request内のImplementation状態が"
            "PATCH_CHECKEDではありません。"
        )

    patch_sha256 = patch_result.get(
        "patch_sha256"
    )

    if not isinstance(patch_sha256, str):
        raise MissionRepairPatchApplyError(
            "Patch SHA-256が保存されていません。"
        )

    patch_sha256 = patch_sha256.strip()

    if len(patch_sha256) != 64:
        raise MissionRepairPatchApplyError(
            "Patch SHA-256の形式が不正です。"
        )

    try:
        int(patch_sha256, 16)
    except ValueError as error:
        raise MissionRepairPatchApplyError(
            "Patch SHA-256が16進数ではありません。"
        ) from error

    return patch_sha256


def _validate_mission_state(
    mission: dict[str, Any],
) -> None:
    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionRepairPatchApplyError(
            "承認済みMissionのみRepair Patchを"
            "適用できます。"
        )

    approval_task = _task_by_type(
        mission,
        "APPROVAL",
    )
    implementation_task = _task_by_type(
        mission,
        "IMPLEMENTATION",
    )
    verification_task = _task_by_type(
        mission,
        "VERIFICATION",
    )

    if approval_task["status"] != "COMPLETED":
        raise MissionRepairPatchApplyError(
            "APPROVAL Taskが完了していません。"
        )

    if implementation_task["status"] != "RUNNING":
        raise MissionRepairPatchApplyError(
            "IMPLEMENTATION TaskがRUNNINGではありません。"
        )

    if verification_task["status"] not in {
        "PENDING",
        "FAILED",
    }:
        raise MissionRepairPatchApplyError(
            "Verification再実行前の状態ではありません。"
        )


def _relative_to_arc(path) -> str:
    resolved = path.resolve()

    try:
        return (
            resolved
            .relative_to(ARC_ROOT)
            .as_posix()
        )
    except ValueError:
        return resolved.as_posix()


def _build_patch_apply_failure_update(
    *,
    repair_request: dict[str, Any],
    error: BaseException,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
]:
    classification = classify_patch_failure(
        error,
        source="REPAIR_PATCH_APPLY",
    )

    classification_payload = (
        serialize_failure_classification(
            classification
        )
    )

    failed_request = {
        **repair_request,
        "repair_apply_version": (
            REPAIR_PATCH_APPLY_VERSION
        ),
        "status": "PATCH_APPLY_FAILED",
        "patch_applied": False,
        "auto_apply": False,
        "apply_error": str(error),
        "patch_apply_failure_category": (
            classification_payload[
                "failure_category"
            ]
        ),
        "patch_apply_failure_classification": (
            classification_payload
        ),
    }

    return (
        failed_request,
        classification_payload,
    )


def apply_repair_patch(
    *,
    mission_id: int,
    decided_by: str = "arc-repair-runner-v0.3",
    note: str | None = None,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    _validate_mission_state(
        mission
    )

    repair_request = _load_existing_request(
        mission_id
    )

    if repair_request is None:
        raise MissionRepairPatchApplyError(
            "Repair Requestが存在しません。"
        )

    if (
        repair_request.get("status")
        == "PATCH_APPLIED"
        and repair_request.get(
            "patch_applied"
        )
        is True
    ):
        return {
            "mission": mission,
            "repair_request": repair_request,
            "duplicate": True,
        }

    patch_sha256 = _validate_repair_request(
        mission_id=mission_id,
        repair_request=repair_request,
    )

    decided_by = str(
        decided_by
        or "arc-repair-runner-v0.3"
    ).strip()

    if not decided_by:
        decided_by = (
            "arc-repair-runner-v0.3"
        )

    request_id = str(
        repair_request.get("request_id")
        or ""
    ).strip()

    note_parts = [
        "Repair Patch Apply v0.3",
    ]

    if request_id:
        note_parts.append(
            f"request_id={request_id}"
        )

    if note:
        normalized_note = note.strip()

        if normalized_note:
            note_parts.append(
                normalized_note
            )

    payload = MissionPatchApplyRequest(
        confirmation="APPLY_PATCH",
        expected_patch_sha256=patch_sha256,
        decided_by=decided_by,
        note=" | ".join(note_parts),
    )

    try:
        applied = (
            apply_mission_implementation_patch_safe(
                mission_id=mission_id,
                payload=payload,
            )
        )
    except MissionImplementationError as error:
        (
            failed_request,
            classification_payload,
        ) = _build_patch_apply_failure_update(
            repair_request=repair_request,
            error=error,
        )

        _write_json_atomic(
            _latest_request_path(
                mission_id
            ),
            failed_request,
        )

        add_mission_log(
            mission_id=mission_id,
            level="ERROR",
            event_type=(
                "MISSION_REPAIR_PATCH_APPLY_FAILED"
            ),
            message=(
                "Repair Patchの適用に失敗しました。"
                "既存Patch Apply Engineの"
                "安全処理により停止しました。"
            ),
            metadata={
                "repair_apply_version": (
                    REPAIR_PATCH_APPLY_VERSION
                ),
                "request_id": request_id,
                "patch_sha256": patch_sha256,
                "error": str(error),
                "failure_category": (
                    classification_payload[
                        "failure_category"
                    ]
                ),
                "failure_classification": (
                    classification_payload
                ),
                "patch_applied": False,
                "auto_apply": False,
            },
        )

        raise MissionRepairPatchApplyError(
            str(error)
        ) from error

    patch_apply = applied.get(
        "patch_apply"
    )
    implementation = applied.get(
        "implementation"
    )

    if not isinstance(
        patch_apply,
        dict,
    ):
        raise MissionRepairPatchApplyError(
            "Patch Apply結果が不正です。"
        )

    if not isinstance(
        implementation,
        dict,
    ):
        raise MissionRepairPatchApplyError(
            "Implementation結果が不正です。"
        )

    if patch_apply.get("applied") is not True:
        raise MissionRepairPatchApplyError(
            "Patch適用成功状態を確認できません。"
        )

    if patch_apply.get("rolled_back") is True:
        raise MissionRepairPatchApplyError(
            "PatchはRollbackされています。"
        )

    if implementation.get("mode") != "PATCH_APPLIED":
        raise MissionRepairPatchApplyError(
            "ImplementationがPATCH_APPLIEDへ"
            "移行していません。"
        )

    applied_sha256 = patch_apply.get(
        "patch_sha256"
    )

    if applied_sha256 != patch_sha256:
        raise MissionRepairPatchApplyError(
            "適用後Patch SHA-256が"
            "Repair Requestと一致しません。"
        )

    changed_files = patch_apply.get(
        "changed_files"
    )

    if not isinstance(changed_files, list):
        changed_files = []

    updated_request = {
        **repair_request,
        "repair_apply_version": (
            REPAIR_PATCH_APPLY_VERSION
        ),
        "status": "PATCH_APPLIED",
        "patch_generated": True,
        "patch_checked": True,
        "patch_applied": True,
        "auto_apply": False,
        "apply_error": None,
        "apply_result": {
            "patch_apply_version": (
                patch_apply.get(
                    "patch_apply_version"
                )
            ),
            "patch_sha256": applied_sha256,
            "changed_file_count": (
                patch_apply.get(
                    "changed_file_count"
                )
            ),
            "changed_files": changed_files,
            "working_tree_clean": (
                patch_apply.get(
                    "working_tree_clean"
                )
            ),
            "rolled_back": (
                patch_apply.get(
                    "rolled_back"
                )
            ),
            "applied_at": (
                patch_apply.get(
                    "applied_at"
                )
            ),
            "implementation_mode": (
                implementation.get("mode")
            ),
        },
        "next_stage": (
            "Verification Runnerを再実行する"
        ),
    }

    latest_path = _latest_request_path(
        mission_id
    )

    archive_path = (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
        / (
            "patch-request-"
            f"{request_id or 'unknown'}"
            "-applied.json"
        )
    )

    _write_json_atomic(
        archive_path,
        updated_request,
    )
    _write_json_atomic(
        latest_path,
        updated_request,
    )

    add_mission_log(
        mission_id=mission_id,
        level="WARNING",
        event_type=(
            "MISSION_REPAIR_PATCH_APPLIED"
        ),
        message=(
            "確認済みRepair Patchを適用しました。"
            "再Verificationはまだ実行していません。"
        ),
        metadata={
            "repair_apply_version": (
                REPAIR_PATCH_APPLY_VERSION
            ),
            "request_id": request_id,
            "patch_sha256": applied_sha256,
            "changed_file_count": (
                patch_apply.get(
                    "changed_file_count"
                )
            ),
            "changed_files": changed_files,
            "implementation_mode": (
                implementation.get("mode")
            ),
            "patch_applied": True,
            "auto_apply": False,
            "next_stage": (
                "VERIFICATION"
            ),
            "latest_path": (
                _relative_to_arc(
                    latest_path
                )
            ),
        },
    )

    return {
        "mission": applied["mission"],
        "repair_request": updated_request,
        "patch_apply": patch_apply,
        "implementation": implementation,
        "storage": {
            "latest_path": (
                _relative_to_arc(
                    latest_path
                )
            ),
            "archive_path": (
                _relative_to_arc(
                    archive_path
                )
            ),
            "duplicate": False,
        },
    }


def apply_repair_patch_safe(
    *,
    mission_id: int,
    decided_by: str = "arc-repair-runner-v0.3",
    note: str | None = None,
) -> dict[str, Any]:
    try:
        return apply_repair_patch(
            mission_id=mission_id,
            decided_by=decided_by,
            note=note,
        )
    except (
        MissionRepairPatchApplyError,
        MissionError,
    ):
        raise
