from __future__ import annotations

from typing import Any

from app.code_generation.context_validator import (
    CodeGenerationContextValidationError,
    validate_payload_against_context,
)
from app.code_generation.contract import (
    CodeGenerationContractError,
    validate_code_generation_contract,
)
from app.code_generation.patch_converter import (
    CodeGenerationPatchConversionError,
    convert_contract_to_patch_request,
)
from app.missions.patch_generator import (
    MissionPatchGeneratorError,
    generate_mission_patch_safe,
)


PATCH_INTEGRATION_VERSION = (
    "mission-code-generation-patch-integration-v0.1"
)


class CodeGenerationPatchIntegrationError(
    Exception
):
    """Code GenerationからPatch Checkまでの統合エラー。"""


def _require_mapping(
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CodeGenerationPatchIntegrationError(
            f"{label}の形式が不正です。"
        )

    return value


def _require_true(
    payload: dict[str, Any],
    *,
    key: str,
    label: str,
) -> None:
    if payload.get(key) is not True:
        error = payload.get("error")

        if isinstance(error, str) and error.strip():
            raise CodeGenerationPatchIntegrationError(
                f"{label}に失敗しました: "
                f"{error.strip()}"
            )

        raise CodeGenerationPatchIntegrationError(
            f"{label}に失敗しました。"
        )


def run_code_generation_patch_integration(
    *,
    mission_id: int,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(mission_id, int):
        raise CodeGenerationPatchIntegrationError(
            "Mission IDは整数で指定してください。"
        )

    if mission_id <= 0:
        raise CodeGenerationPatchIntegrationError(
            "Mission IDは1以上で指定してください。"
        )

    contract_payload = _require_mapping(
        payload,
        label="Code Generation Contract",
    )

    context_payload = _require_mapping(
        context,
        label="Code Context",
    )

    payload_mission_id = contract_payload.get(
        "mission_id"
    )

    if payload_mission_id != mission_id:
        raise CodeGenerationPatchIntegrationError(
            "指定Mission IDとContract内の"
            "Mission IDが一致しません。 "
            f"argument={mission_id} "
            f"contract={payload_mission_id}"
        )

    contract_result = (
        validate_code_generation_contract(
            contract_payload
        )
    )

    contract_result = _require_mapping(
        contract_result,
        label="Contract Validation結果",
    )

    _require_true(
        contract_result,
        key="valid",
        label="Contract Validation",
    )

    context_result = (
        validate_payload_against_context(
            payload=contract_payload,
            context=context_payload,
        )
    )

    context_result = _require_mapping(
        context_result,
        label="Context Validation結果",
    )

    _require_true(
        context_result,
        key="valid",
        label="Context Validation",
    )

    conversion_result = (
        convert_contract_to_patch_request(
            payload=contract_payload,
            context=context_payload,
        )
    )

    conversion_result = _require_mapping(
        conversion_result,
        label="Patch Request Conversion結果",
    )

    _require_true(
        conversion_result,
        key="converted",
        label="Patch Request Conversion",
    )

    patch_request = conversion_result.get(
        "patch_request"
    )

    if patch_request is None:
        raise CodeGenerationPatchIntegrationError(
            "変換結果にPatch Requestがありません。"
        )

    patch_generation_result = (
        generate_mission_patch_safe(
            mission_id=mission_id,
            payload=patch_request,
        )
    )

    patch_generation_result = _require_mapping(
        patch_generation_result,
        label="Patch Generation結果",
    )

    generator = _require_mapping(
        patch_generation_result.get(
            "generator"
        ),
        label="Patch Generator結果",
    )

    patch_check = _require_mapping(
        patch_generation_result.get(
            "patch_check"
        ),
        label="Patch Check結果",
    )

    implementation = _require_mapping(
        patch_generation_result.get(
            "implementation"
        ),
        label="Implementation結果",
    )

    patch_text = generator.get("patch_text")

    if not isinstance(patch_text, str):
        raise CodeGenerationPatchIntegrationError(
            "生成されたPatch Textが不正です。"
        )

    if not patch_text.strip():
        raise CodeGenerationPatchIntegrationError(
            "生成されたPatchが空です。"
        )

    git_apply_check = _require_mapping(
        patch_check.get(
            "git_apply_check"
        ),
        label="Git Apply Check結果",
    )

    if (
        git_apply_check.get("applicable")
        is not True
    ):
        returncode = git_apply_check.get(
            "returncode"
        )
        stderr = git_apply_check.get(
            "stderr"
        )

        raise CodeGenerationPatchIntegrationError(
            "生成Patchはgit apply --checkに"
            "合格していません。 "
            f"returncode={returncode} "
            f"stderr={stderr!r}"
        )

    if patch_check.get("applied") is not False:
        raise CodeGenerationPatchIntegrationError(
            "Patch Check段階でPatchが"
            "適用済みになっています。"
        )

    if implementation.get("mode") != (
        "PATCH_CHECKED"
    ):
        raise CodeGenerationPatchIntegrationError(
            "ImplementationがPATCH_CHECKEDに"
            "遷移していません。"
        )

    changed_files = generator.get(
        "changed_files"
    )

    if not isinstance(changed_files, list):
        raise CodeGenerationPatchIntegrationError(
            "変更対象ファイル一覧が不正です。"
        )

    return {
        "integrated": True,
        "integration_version": (
            PATCH_INTEGRATION_VERSION
        ),
        "mission_id": mission_id,
        "contract_sha256": (
            contract_result.get(
                "contract_sha256"
            )
        ),
        "context_sha256": (
            contract_payload.get(
                "context_sha256"
            )
        ),
        "patch_request_sha256": (
            conversion_result.get(
                "patch_request_sha256"
            )
        ),
        "edit_count": (
            conversion_result.get(
                "edit_count"
            )
        ),
        "changed_file_count": (
            generator.get(
                "changed_file_count"
            )
        ),
        "changed_files": changed_files,
        "patch_text": patch_text,
        "patch_sha256": patch_check.get(
            "patch_sha256"
        ),
        "patch_applicable": (
            git_apply_check.get(
                "applicable"
            )
        ),
        "patch_applied": (
            patch_check.get(
                "applied"
            )
        ),
        "contract_validation": (
            contract_result
        ),
        "context_validation": (
            context_result
        ),
        "conversion": {
            key: value
            for key, value
            in conversion_result.items()
            if key != "patch_request"
        },
        "generator": generator,
        "patch_check": patch_check,
        "implementation": implementation,
        "mission": (
            patch_generation_result.get(
                "mission"
            )
        ),
        "next_stage": (
            "WAIT_PATCH_APPLY_APPROVAL"
        ),
    }


def run_code_generation_patch_integration_safe(
    *,
    mission_id: int,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    try:
        return (
            run_code_generation_patch_integration(
                mission_id=mission_id,
                payload=payload,
                context=context,
            )
        )
    except CodeGenerationPatchIntegrationError:
        raise
    except (
        CodeGenerationContractError,
        CodeGenerationContextValidationError,
        CodeGenerationPatchConversionError,
        MissionPatchGeneratorError,
    ) as error:
        raise CodeGenerationPatchIntegrationError(
            str(error)
        ) from error
    except Exception as error:
        raise CodeGenerationPatchIntegrationError(
            "Code Generation Patch Integrationで"
            "予期しないエラーが発生しました: "
            f"{error}"
        ) from error
