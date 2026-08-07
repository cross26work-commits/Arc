import json

import pytest

from app.missions.repair_request_builder import (
    FAILURE_SOURCE_IMPLEMENTATION_PATCH,
    FAILURE_SOURCE_VERIFICATION,
    MissionRepairRequestError,
    _repair_failure_source,
    _validate_repair_failure_source,
)


def _task(
    *,
    status,
    result,
):
    return {
        "id": 1,
        "status": status,
        "result": json.dumps(result),
    }


def test_repair_plan_defaults_to_verification():
    assert (
        _repair_failure_source({})
        == FAILURE_SOURCE_VERIFICATION
    )


def test_patch_failure_source_is_supported():
    assert (
        _repair_failure_source(
            {
                "failure_source": (
                    "IMPLEMENTATION_PATCH"
                )
            }
        )
        == FAILURE_SOURCE_IMPLEMENTATION_PATCH
    )


def test_verification_source_requires_failed_result():
    result = _validate_repair_failure_source(
        failure_source=(
            FAILURE_SOURCE_VERIFICATION
        ),
        implementation_task=_task(
            status="RUNNING",
            result={},
        ),
        verification_task=_task(
            status="FAILED",
            result={
                "passed": False,
                "failure_category": "TEST",
            },
        ),
    )

    assert result["failure_source"] == (
        FAILURE_SOURCE_VERIFICATION
    )

    assert result["failure_payload"][
        "failure_category"
    ] == "TEST"


def test_patch_source_accepts_pending_verification():
    result = _validate_repair_failure_source(
        failure_source=(
            FAILURE_SOURCE_IMPLEMENTATION_PATCH
        ),
        implementation_task=_task(
            status="RUNNING",
            result={
                "last_patch_failure": {
                    "stage": "PATCH_APPLY",
                    "failure_category": "PATCH",
                    "error": (
                        "patch does not apply"
                    ),
                },
            },
        ),
        verification_task=_task(
            status="PENDING",
            result={
                "passed": None,
            },
        ),
    )

    assert result["failure_source"] == (
        FAILURE_SOURCE_IMPLEMENTATION_PATCH
    )

    assert result["failure_payload"][
        "failure_category"
    ] == "PATCH"


def test_patch_source_requires_last_patch_failure():
    with pytest.raises(
        MissionRepairRequestError
    ):
        _validate_repair_failure_source(
            failure_source=(
                FAILURE_SOURCE_IMPLEMENTATION_PATCH
            ),
            implementation_task=_task(
                status="RUNNING",
                result={
                    "mode": "PATCH_CHECKED",
                },
            ),
            verification_task=_task(
                status="PENDING",
                result={
                    "passed": None,
                },
            ),
        )
