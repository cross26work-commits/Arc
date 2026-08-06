from app.missions.code_generation_runner import (
    _mark_generation_step_failed,
)
from app.missions.failure_classifier import (
    classify_code_generation_failure,
    serialize_failure_classification,
)
from app.missions.models import (
    ImplementationStepExecution,
    ImplementationStepResult,
)


def _execution():
    return ImplementationStepExecution(
        current_step_id="step-1",
        remaining_step_ids=["step-1"],
        results={
            "step-1": ImplementationStepResult(
                step_id="step-1",
                status="GENERATING",
                attempt_count=1,
                metadata={
                    "existing_key": "preserved",
                },
            ),
        },
    )


def test_generation_failure_is_saved_to_metadata():
    classification = (
        classify_code_generation_failure(
            "Ollama connection failed"
        )
    )
    payload = serialize_failure_classification(
        classification
    )

    execution = _mark_generation_step_failed(
        execution=_execution(),
        error="Ollama connection failed",
        failure_classification=payload,
    )

    result = execution.results["step-1"]

    assert result.status == "FAILED"
    assert result.error == (
        "Ollama connection failed"
    )
    assert result.metadata[
        "failure_category"
    ] == "LLM"
    assert result.metadata[
        "failure_classification"
    ]["classification_source"] == (
        "CODE_GENERATION"
    )


def test_generation_failure_without_classification():
    execution = _mark_generation_step_failed(
        execution=_execution(),
        error="plain failure",
    )

    result = execution.results["step-1"]

    assert result.status == "FAILED"
    assert result.error == "plain failure"
