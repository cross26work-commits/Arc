from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.missions.models import (
    MissionPatchEdit,
    MissionPatchGenerateRequest,
)
from app.missions.patch_generator import (
    MissionPatchGeneratorError,
    generate_mission_patch_safe,
)
from app.missions.repair_request_builder import (
    ARC_ROOT,
    REPAIR_PLAN_ROOT,
    _latest_request_path,
    _load_existing_request,
    _write_json_atomic,
)
from app.missions.service import (
    MissionError,
    add_mission_log,
    get_mission,
)


class MissionRepairPatchConnectorError(Exception):
    """Repair RequestのPatch Generator接続失敗時の例外。"""


REPAIR_CONNECTOR_VERSION = (
    "mission-repair-patch-connector-v0.2"
)


def _validate_request(
    repair_request: dict[str, Any],
) -> None:
    if repair_request.get("status") not in {
        "REQUESTED",
        "PATCH_CHECKED",
    }:
        raise MissionRepairPatchConnectorError(
            "Repair RequestがPatch生成可能状態ではありません。"
        )

    if repair_request.get("auto_apply") is not False:
        raise MissionRepairPatchConnectorError(
            "Repair Requestのauto_applyが"
            "安全状態ではありません。"
        )

    if repair_request.get("patch_applied") is True:
        raise MissionRepairPatchConnectorError(
            "既にPatch Apply済みです。"
        )

    edits = repair_request.get("edits")

    if not isinstance(edits, list) or not edits:
        raise MissionRepairPatchConnectorError(
            "Repair Requestにeditsがありません。"
        )


def _build_patch_payload(
    repair_request: dict[str, Any],
) -> MissionPatchGenerateRequest:
    _validate_request(repair_request)

    raw_edits = repair_request["edits"]
    edits: list[MissionPatchEdit] = []

    for index, item in enumerate(
        raw_edits,
        start=1,
    ):
        if not isinstance(item, dict):
            raise MissionRepairPatchConnectorError(
                f"edits[{index}]の形式が不正です。"
            )

        try:
            edit = MissionPatchEdit(
                **item
            )
        except Exception as error:
            raise MissionRepairPatchConnectorError(
                f"edits[{index}]を復元できません: {error}"
            ) from error

        edits.append(edit)

    generated_by = str(
        repair_request.get("generated_by")
        or "repair-runner-v0.2"
    ).strip()

    if not generated_by:
        generated_by = "repair-runner-v0.2"

    request_id = str(
        repair_request.get("request_id")
        or ""
    ).strip()

    note_parts = [
        "Repair Patch Connector v0.2",
    ]

    if request_id:
        note_parts.append(
            f"request_id={request_id}"
        )

    failure_category = repair_request.get(
        "failure_category"
    )

    if failure_category:
        note_parts.append(
            f"failure={failure_category}"
        )

    original_note = repair_request.get("note")

    if isinstance(original_note, str):
        original_note = original_note.strip()

        if original_note:
            note_parts.append(original_note)

    return MissionPatchGenerateRequest(
        edits=edits,
        generated_by=generated_by,
        note=" | ".join(note_parts),
    )


def _relative_to_arc(path: Path) -> str:
    resolved = path.resolve()

    try:
        return (
            resolved
            .relative_to(ARC_ROOT)
            .as_posix()
        )
    except ValueError:
        return resolved.as_posix()


def _result_summary(
    generated: dict[str, Any],
) -> dict[str, Any]:
    generator = generated.get("generator")

    if not isinstance(generator, dict):
        generator = {}

    patch_check = generated.get("patch_check")

    if not isinstance(patch_check, dict):
        patch_check = {}

    implementation = generated.get("implementation")

    if not isinstance(implementation, dict):
        implementation = {}

    patch_text = generator.get("patch_text")

    return {
        "generator_version": (
            generator.get("generator_version")
        ),
        "changed_file_count": (
            generator.get("changed_file_count")
        ),
        "changed_files": (
            generator.get("changed_files", [])
        ),
        "operation_count": (
            generator.get("operation_count")
        ),
        "generator_result_path": (
            generator.get("result_path")
        ),
        "patch_sha256": (
            patch_check.get("patch_sha256")
            or implementation.get(
                "patch",
                {},
            ).get("sha256")
        ),
        "patch_applicable": (
            patch_check.get("patch_applicable")
        ),
        "implementation_mode": (
            implementation.get("mode")
        ),
        "patch_text_present": isinstance(
            patch_text,
            str,
        )
        and bool(patch_text),
    }


def connect_repair_request_to_patch_generator(
    mission_id: int,
) -> dict[str, Any]:
    mission = get_mission(mission_id)

    if mission["status"] not in {
        "APPROVED",
        "RUNNING",
    }:
        raise MissionRepairPatchConnectorError(
            "承認済みMissionのみRepair Patchを"
            "生成できます。"
        )

    repair_request = _load_existing_request(
        mission_id
    )

    if repair_request is None:
        raise MissionRepairPatchConnectorError(
            "Repair Requestが存在しません。"
            "先にrepair-requestを生成してください。"
        )

    stored_mission_id = repair_request.get(
        "mission_id"
    )

    if stored_mission_id != mission_id:
        raise MissionRepairPatchConnectorError(
            "Repair RequestのMission IDが一致しません。"
        )

    if (
        repair_request.get("status")
        == "PATCH_CHECKED"
        and repair_request.get(
            "patch_generated"
        )
        is True
        and repair_request.get(
            "patch_checked"
        )
        is True
    ):
        return {
            "mission": mission,
            "repair_request": repair_request,
            "duplicate": True,
        }

    payload = _build_patch_payload(
        repair_request
    )

    try:
        generated = generate_mission_patch_safe(
            mission_id=mission_id,
            payload=payload,
        )
    except MissionPatchGeneratorError as error:
        failed_request = {
            **repair_request,
            "connector_version": (
                REPAIR_CONNECTOR_VERSION
            ),
            "status": "PATCH_GENERATION_FAILED",
            "patch_generated": False,
            "patch_checked": False,
            "patch_applied": False,
            "auto_apply": False,
            "connector_error": str(error),
        }

        _write_json_atomic(
            _latest_request_path(mission_id),
            failed_request,
        )

        add_mission_log(
            mission_id=mission_id,
            level="ERROR",
            event_type=(
                "MISSION_REPAIR_PATCH_GENERATION_FAILED"
            ),
            message=(
                "Repair RequestからのPatch生成または"
                "Patch Checkに失敗しました。"
            ),
            metadata={
                "connector_version": (
                    REPAIR_CONNECTOR_VERSION
                ),
                "request_id": (
                    repair_request.get(
                        "request_id"
                    )
                ),
                "error": str(error),
                "patch_generated": False,
                "patch_checked": False,
                "patch_applied": False,
                "auto_apply": False,
            },
        )

        raise MissionRepairPatchConnectorError(
            str(error)
        ) from error

    summary = _result_summary(
        generated
    )

    if summary["patch_applicable"] is not True:
        raise MissionRepairPatchConnectorError(
            "Patch Check成功状態を確認できません。"
        )

    if summary["implementation_mode"] != "PATCH_CHECKED":
        raise MissionRepairPatchConnectorError(
            "ImplementationがPATCH_CHECKEDへ"
            "移行していません。"
        )

    updated_request = {
        **repair_request,
        "connector_version": (
            REPAIR_CONNECTOR_VERSION
        ),
        "status": "PATCH_CHECKED",
        "patch_generated": True,
        "patch_checked": True,
        "patch_applied": False,
        "auto_apply": False,
        "patch_result": summary,
        "connector_error": None,
    }

    latest_path = _latest_request_path(
        mission_id
    )

    request_id = str(
        updated_request.get("request_id")
        or "unknown"
    )

    archive_path = (
        REPAIR_PLAN_ROOT
        / f"mission-{mission_id}"
        / (
            "patch-request-"
            f"{request_id}-checked.json"
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
        level="INFO",
        event_type=(
            "MISSION_REPAIR_PATCH_CHECKED"
        ),
        message=(
            "Repair RequestからUnified Diffを生成し、"
            "Patch Checkに成功しました。"
            "Patch Applyは実行していません。"
        ),
        metadata={
            "connector_version": (
                REPAIR_CONNECTOR_VERSION
            ),
            "request_id": (
                updated_request.get(
                    "request_id"
                )
            ),
            "changed_file_count": (
                summary["changed_file_count"]
            ),
            "changed_files": (
                summary["changed_files"]
            ),
            "operation_count": (
                summary["operation_count"]
            ),
            "patch_sha256": (
                summary["patch_sha256"]
            ),
            "implementation_mode": (
                summary[
                    "implementation_mode"
                ]
            ),
            "patch_generated": True,
            "patch_checked": True,
            "patch_applied": False,
            "auto_apply": False,
            "latest_path": (
                _relative_to_arc(
                    latest_path
                )
            ),
        },
    )

    return {
        "mission": generated["mission"],
        "repair_request": updated_request,
        "generator": generated["generator"],
        "patch_check": generated["patch_check"],
        "implementation": generated[
            "implementation"
        ],
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


def connect_repair_request_to_patch_generator_safe(
    mission_id: int,
) -> dict[str, Any]:
    try:
        return (
            connect_repair_request_to_patch_generator(
                mission_id
            )
        )
    except (
        MissionRepairPatchConnectorError,
        MissionError,
    ):
        raise
