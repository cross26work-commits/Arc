import json

import pytest

from app.missions.failure_classifier import (
    FAILURE_CLASSIFIER_VERSION,
    classify_command_failure,
    classify_exception,
    serialize_failure_classification,
)
from app.missions.repair_policy import (
    FailureCategory,
    get_repair_policy,
)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "command_name": "pytest",
                "stderr": "2 tests failed",
                "returncode": 1,
            },
            FailureCategory.TEST,
        ),
        (
            {
                "command_name": "npm run build",
                "stderr": "Failed to compile",
                "returncode": 1,
            },
            FailureCategory.BUILD,
        ),
        (
            {
                "command_name": "python",
                "stderr": "SyntaxError: invalid syntax",
                "returncode": 1,
            },
            FailureCategory.SYNTAX,
        ),
        (
            {
                "command_name": "python",
                "stderr": (
                    "ModuleNotFoundError: No module "
                    "named 'example'"
                ),
                "returncode": 1,
            },
            FailureCategory.IMPORT,
        ),
        (
            {
                "command_name": "git apply",
                "stderr": "patch does not apply",
                "returncode": 1,
            },
            FailureCategory.PATCH,
        ),
        (
            {
                "command_name": "python",
                "stderr": "JSONDecodeError",
                "returncode": 1,
            },
            FailureCategory.JSON,
        ),
        (
            {
                "command_name": "python",
                "stderr": (
                    "Traceback (most recent call last)"
                ),
                "returncode": 1,
            },
            FailureCategory.RUNTIME,
        ),
        (
            {
                "command_name": "command",
                "returncode": 1,
            },
            FailureCategory.COMMAND,
        ),
        (
            {
                "command_name": "command",
                "timed_out": True,
                "returncode": None,
            },
            FailureCategory.TIMEOUT,
        ),
    ],
)
def test_classify_command_failure(
    kwargs,
    expected,
):
    result = classify_command_failure(
        **kwargs
    )

    assert result.category == expected


def test_classify_llm_exception():
    result = classify_exception(
        RuntimeError(
            "Ollama model response was invalid"
        ),
        source="CODE_GENERATION",
    )

    assert result.category == FailureCategory.LLM
    assert result.source == "CODE_GENERATION"


def test_classify_json_exception():
    result = classify_exception(
        json.JSONDecodeError(
            "invalid",
            "{}",
            0,
        )
    )

    assert result.category == FailureCategory.JSON


def test_serialization():
    result = classify_command_failure(
        command_name="git status",
        stderr="fatal: not a git repository",
        returncode=128,
    )

    payload = serialize_failure_classification(
        result
    )

    assert payload[
        "classifier_version"
    ] == FAILURE_CLASSIFIER_VERSION

    assert payload[
        "failure_category"
    ] == "GIT"

    assert payload["reason_code"]


def test_all_new_categories_have_repair_policy():
    for category in (
        FailureCategory.PATCH,
        FailureCategory.LLM,
        FailureCategory.JSON,
        FailureCategory.RUNTIME,
    ):
        rule = get_repair_policy(category)

        assert rule.category == category
        assert rule.max_retries >= 1
