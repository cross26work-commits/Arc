import subprocess

import pytest

from app.missions.failure_classifier import (
    classify_patch_failure,
)
from app.missions.repair_patch_apply import (
    _build_patch_apply_failure_update,
)
from app.missions.repair_policy import (
    FailureCategory,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "error: patch does not apply",
            FailureCategory.PATCH,
        ),
        (
            "hunk failed at line 20",
            FailureCategory.PATCH,
        ),
        (
            "fatal: not a git repository",
            FailureCategory.GIT,
        ),
        (
            "Permission denied",
            FailureCategory.PERMISSION,
        ),
        (
            "JSONDecodeError in patch request",
            FailureCategory.JSON,
        ),
        (
            "Unexpected internal condition",
            FailureCategory.RUNTIME,
        ),
    ],
)
def test_classify_patch_failure(
    message,
    expected,
):
    result = classify_patch_failure(
        message,
        source="PATCH_TEST",
    )

    assert result.category == expected
    assert result.source == "PATCH_TEST"


def test_patch_apply_failure_preserves_root_category():
    failed_request, classification = (
        _build_patch_apply_failure_update(
            repair_request={
                "mission_id": 36,
                "request_id": "request-1",
                "failure_category": "TEST",
                "status": "PATCH_CHECKED",
                "patch_applied": False,
            },
            error=RuntimeError(
                "patch does not apply"
            ),
        )
    )

    assert failed_request[
        "failure_category"
    ] == "TEST"

    assert failed_request[
        "patch_apply_failure_category"
    ] == "PATCH"

    assert failed_request[
        "patch_apply_failure_classification"
    ]["reason_code"] == (
        "PATCH_CONTENT_FAILURE"
    )

    assert failed_request[
        "status"
    ] == "PATCH_APPLY_FAILED"

    assert classification[
        "classification_source"
    ] == "REPAIR_PATCH_APPLY"


def test_patch_apply_git_failure():
    failed_request, _ = (
        _build_patch_apply_failure_update(
            repair_request={
                "failure_category": "BUILD",
            },
            error=RuntimeError(
                "fatal: not a git repository"
            ),
        )
    )

    assert failed_request[
        "failure_category"
    ] == "BUILD"

    assert failed_request[
        "patch_apply_failure_category"
    ] == "GIT"


def test_patch_timeout_exception_has_priority():
    result = classify_patch_failure(
        subprocess.TimeoutExpired(
            cmd="git apply --check",
            timeout=60,
        ),
        source="PATCH_TEST",
    )

    assert result.category == (
        FailureCategory.TIMEOUT
    )
    assert result.reason_code == "PATCH_TIMEOUT"
