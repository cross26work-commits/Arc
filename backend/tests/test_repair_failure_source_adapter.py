import json

from app.missions.self_repair_planner import (
    FAILURE_SOURCE_IMPLEMENTATION_PATCH,
    FAILURE_SOURCE_VERIFICATION,
    _resolve_repair_failure_source,
)


def _task(
    *,
    task_type,
    status,
    result=None,
):
    return {
        "id": 1,
        "task_type": task_type,
        "status": status,
        "result": (
            json.dumps(result)
            if result is not None
            else None
        ),
    }


def test_patch_failure_has_priority_over_verification():
    implementation_task = _task(
        task_type="IMPLEMENTATION",
        status="RUNNING",
        result={
            "mode": "PATCH_CHECKED",
            "last_patch_failure": {
                "stage": "PATCH_APPLY",
                "failed_at": (
                    "2026-08-06T00:00:00+00:00"
                ),
                "error": (
                    "patch does not apply"
                ),
                "failure_category": "PATCH",
                "failure_classification": {
                    "failure_category": "PATCH",
                    "classification_source": (
                        "IMPLEMENTATION_PATCH_APPLY"
                    ),
                    "reason_code": (
                        "PATCH_CONTENT_FAILURE"
                    ),
                    "confidence": 0.94,
                },
            },
        },
    )

    verification_task = _task(
        task_type="VERIFICATION",
        status="PENDING",
        result={
            "passed": False,
            "failure_category": "UNKNOWN",
            "results": [],
        },
    )

    payload = _resolve_repair_failure_source(
        mission={"id": 36},
        implementation_task=(
            implementation_task
        ),
        verification_task=(
            verification_task
        ),
    )

    assert payload["failure_source"] == (
        FAILURE_SOURCE_IMPLEMENTATION_PATCH
    )

    assert payload[
        "failure_category"
    ] == "PATCH"

    assert payload["results"][0][
        "name"
    ] == "PATCH_APPLY"

    assert payload["results"][0][
        "stderr"
    ] == "patch does not apply"


def test_verification_is_used_without_patch_failure():
    implementation_task = _task(
        task_type="IMPLEMENTATION",
        status="RUNNING",
        result={
            "mode": "CODE_GENERATED",
        },
    )

    verification_task = _task(
        task_type="VERIFICATION",
        status="FAILED",
        result={
            "passed": False,
            "failure_category": "TEST",
            "results": [
                {
                    "passed": False,
                    "name": "pytest",
                    "failure_category": "TEST",
                }
            ],
        },
    )

    payload = _resolve_repair_failure_source(
        mission={"id": 36},
        implementation_task=(
            implementation_task
        ),
        verification_task=(
            verification_task
        ),
    )

    assert payload["failure_source"] == (
        FAILURE_SOURCE_VERIFICATION
    )

    assert payload[
        "failure_category"
    ] == "TEST"


def test_patch_failure_extracts_step_files():
    implementation_task = _task(
        task_type="IMPLEMENTATION",
        status="RUNNING",
        result={
            "last_patch_failure": {
                "stage": "PATCH_CHECK",
                "error": "hunk failed",
                "failure_category": "PATCH",
                "failure_classification": {},
            },
            "step_execution": {
                "current_step_id": "step-2",
                "results": {
                    "step-2": {
                        "metadata": {
                            "target_files": [
                                "src/calculator.py",
                            ],
                            "changed_files": [
                                "tests/test_calculator.py",
                            ],
                        },
                    },
                },
            },
        },
    )

    verification_task = _task(
        task_type="VERIFICATION",
        status="PENDING",
        result={
            "passed": False,
            "failure_category": "UNKNOWN",
            "results": [],
        },
    )

    payload = _resolve_repair_failure_source(
        mission={"id": 36},
        implementation_task=(
            implementation_task
        ),
        verification_task=(
            verification_task
        ),
    )

    suspected = payload[
        "results"
    ][0]["suspected_files"]

    assert "src/calculator.py" in suspected
    assert (
        "tests/test_calculator.py"
        in suspected
    )
