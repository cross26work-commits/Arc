from app.missions.repair_context_builder import (
    FAILURE_SOURCE_IMPLEMENTATION_PATCH,
    FAILURE_SOURCE_VERIFICATION,
    _failure_source_context,
    _verification_context,
)


def test_failure_context_defaults_to_verification():
    context = _failure_source_context(
        {
            "failure_category": "TEST",
        }
    )

    assert context[
        "failure_source"
    ] == FAILURE_SOURCE_VERIFICATION

    assert context[
        "failure_category"
    ] == "TEST"


def test_patch_failure_becomes_failed_result():
    request = {
        "failure_source": (
            FAILURE_SOURCE_IMPLEMENTATION_PATCH
        ),
        "failure_source_version": (
            "implementation-patch-failure-v0.1"
        ),
        "failure_signature": "patch-signature",
        "failure_category": "PATCH",
        "failure_payload": {
            "stage": "PATCH_APPLY",
            "error": "patch does not apply",
            "failed_at": (
                "2026-08-06T00:00:00+00:00"
            ),
            "failure_category": "PATCH",
            "failure_classification": {
                "reason_code": (
                    "PATCH_CONTENT_FAILURE"
                ),
            },
        },
    }

    verification = _verification_context(
        request
    )

    assert verification["passed"] is False
    assert verification[
        "failure_category"
    ] == "PATCH"

    assert verification[
        "failure_source"
    ] == (
        FAILURE_SOURCE_IMPLEMENTATION_PATCH
    )

    assert len(
        verification["failed_results"]
    ) == 1

    failed = verification[
        "failed_results"
    ][0]

    assert failed["name"] == "PATCH_APPLY"
    assert (
        failed["stderr"]
        == "patch does not apply"
    )

    assert failed[
        "failure_source"
    ] == (
        FAILURE_SOURCE_IMPLEMENTATION_PATCH
    )


def test_verification_failure_remains_compatible():
    request = {
        "failure_source": "VERIFICATION",
        "failure_category": "TEST",
        "verification_result": {
            "passed": False,
            "failure_category": "TEST",
            "requested_command_count": 2,
            "executed_command_count": 2,
            "failed_results": [
                {
                    "name": "pytest",
                    "failure_category": "TEST",
                }
            ],
        },
    }

    verification = _verification_context(
        request
    )

    assert verification["passed"] is False
    assert verification[
        "failure_category"
    ] == "TEST"

    assert verification[
        "failed_results"
    ][0]["name"] == "pytest"
