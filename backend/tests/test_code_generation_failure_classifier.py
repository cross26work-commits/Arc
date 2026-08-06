import pytest

from app.missions.failure_classifier import (
    classify_code_generation_failure,
)
from app.missions.repair_policy import (
    FailureCategory,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Ollama response timed out",
            FailureCategory.TIMEOUT,
        ),
        (
            (
                "LLM応答からContract JSONを"
                "抽出できませんでした"
            ),
            FailureCategory.JSON,
        ),
        (
            (
                "LLM生成Contractの"
                "Patch Integrationに失敗しました"
            ),
            FailureCategory.PATCH,
        ),
        (
            "Ollama connection failed",
            FailureCategory.LLM,
        ),
        (
            "Generation pipeline failed",
            FailureCategory.LLM,
        ),
        (
            "Unexpected internal failure",
            FailureCategory.RUNTIME,
        ),
    ],
)
def test_classify_code_generation_failure(
    message,
    expected,
):
    result = classify_code_generation_failure(
        message
    )

    assert result.category == expected
    assert result.source == "CODE_GENERATION"
    assert result.reason_code
