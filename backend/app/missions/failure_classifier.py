from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from app.missions.repair_policy import (
    FailureCategory,
)


FAILURE_CLASSIFIER_VERSION = (
    "mission-failure-classifier-v0.1"
)


@dataclass(frozen=True, slots=True)
class FailureClassification:
    category: FailureCategory
    source: str
    reason_code: str
    confidence: float


def _combined_text(
    *values: Any,
) -> str:
    return "\n".join(
        str(value or "")
        for value in values
    ).lower()


def classify_command_failure(
    *,
    command_name: str,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    returncode: int | None = None,
    command_category: str | None = None,
) -> FailureClassification:
    combined = _combined_text(
        command_name,
        command_category,
        stdout,
        stderr,
    )

    command_lower = str(
        command_name or ""
    ).lower()

    category_lower = str(
        command_category or ""
    ).lower()

    if timed_out:
        return FailureClassification(
            category=FailureCategory.TIMEOUT,
            source="COMMAND",
            reason_code="COMMAND_TIMEOUT",
            confidence=1.0,
        )

    if any(
        marker in combined
        for marker in (
            "permission denied",
            "access is denied",
            "operation not permitted",
            "winerror 5",
        )
    ):
        return FailureClassification(
            category=FailureCategory.PERMISSION,
            source="COMMAND",
            reason_code="PERMISSION_DENIED",
            confidence=0.98,
        )

    if any(
        marker in combined
        for marker in (
            "modulenotfounderror",
            "importerror",
            "cannot import",
        )
    ):
        return FailureClassification(
            category=FailureCategory.IMPORT,
            source="COMMAND",
            reason_code="IMPORT_FAILURE",
            confidence=0.98,
        )

    if any(
        marker in combined
        for marker in (
            "no such file or directory",
            "command not found",
            "is not recognized as an internal",
            "executable file not found",
            "enoent",
        )
    ):
        return FailureClassification(
            category=FailureCategory.DEPENDENCY,
            source="COMMAND",
            reason_code="DEPENDENCY_NOT_FOUND",
            confidence=0.95,
        )

    if any(
        marker in combined
        for marker in (
            "jsondecodeerror",
            "invalid json",
            "json parse",
            "unexpected token in json",
        )
    ):
        return FailureClassification(
            category=FailureCategory.JSON,
            source="COMMAND",
            reason_code="JSON_INVALID",
            confidence=0.95,
        )

    if any(
        marker in combined
        for marker in (
            "syntaxerror",
            "syntax error",
            "indentationerror",
            "taberror",
        )
    ):
        return FailureClassification(
            category=FailureCategory.SYNTAX,
            source="COMMAND",
            reason_code="SYNTAX_INVALID",
            confidence=0.98,
        )

    if any(
        marker in combined
        for marker in (
            "patch failed",
            "patch does not apply",
            "malformed patch",
            "corrupt patch",
            "hunk failed",
        )
    ):
        return FailureClassification(
            category=FailureCategory.PATCH,
            source="COMMAND",
            reason_code="PATCH_INVALID",
            confidence=0.96,
        )

    if (
        "eslint" in combined
        or "ruff" in combined
        or "flake8" in combined
        or "pylint" in combined
        or "lint" in command_lower
        or category_lower == "lint"
    ):
        return FailureClassification(
            category=FailureCategory.LINT,
            source="COMMAND",
            reason_code="LINT_FAILURE",
            confidence=0.92,
        )

    if (
        "pytest" in combined
        or "unittest" in combined
        or "test failed" in combined
        or (
            "failed" in combined
            and "test" in combined
        )
        or category_lower == "test"
    ):
        return FailureClassification(
            category=FailureCategory.TEST,
            source="COMMAND",
            reason_code="TEST_FAILURE",
            confidence=0.90,
        )

    if (
        "npm run build" in combined
        or "build failed" in combined
        or "failed to compile" in combined
        or category_lower == "build"
    ):
        return FailureClassification(
            category=FailureCategory.BUILD,
            source="COMMAND",
            reason_code="BUILD_FAILURE",
            confidence=0.92,
        )

    if (
        "git" in command_lower
        or category_lower == "git"
    ):
        return FailureClassification(
            category=FailureCategory.GIT,
            source="COMMAND",
            reason_code="GIT_FAILURE",
            confidence=0.90,
        )

    if any(
        marker in combined
        for marker in (
            "traceback (most recent call last)",
            "runtimeerror",
            "typeerror",
            "valueerror",
            "attributeerror",
            "keyerror",
            "indexerror",
            "zerodivisionerror",
        )
    ):
        return FailureClassification(
            category=FailureCategory.RUNTIME,
            source="COMMAND",
            reason_code="RUNTIME_EXCEPTION",
            confidence=0.85,
        )

    if returncode not in {
        None,
        0,
    }:
        return FailureClassification(
            category=FailureCategory.COMMAND,
            source="COMMAND",
            reason_code="NON_ZERO_EXIT",
            confidence=0.70,
        )

    return FailureClassification(
        category=FailureCategory.UNKNOWN,
        source="COMMAND",
        reason_code="NO_MATCH",
        confidence=0.20,
    )


def classify_patch_failure(
    error: BaseException | str,
    *,
    source: str = "PATCH",
) -> FailureClassification:
    if isinstance(
        error,
        (
            TimeoutError,
            subprocess.TimeoutExpired,
        ),
    ):
        return FailureClassification(
            category=FailureCategory.TIMEOUT,
            source=source,
            reason_code="PATCH_TIMEOUT",
            confidence=1.0,
        )

    if isinstance(error, PermissionError):
        return FailureClassification(
            category=FailureCategory.PERMISSION,
            source=source,
            reason_code="PATCH_PERMISSION_DENIED",
            confidence=1.0,
        )

    if isinstance(error, FileNotFoundError):
        return FailureClassification(
            category=FailureCategory.DEPENDENCY,
            source=source,
            reason_code="PATCH_DEPENDENCY_NOT_FOUND",
            confidence=1.0,
        )

    if isinstance(error, BaseException):
        error_name = type(error).__name__
        message = str(error)

        cause = error.__cause__
        cause_parts: list[str] = []

        while cause is not None:
            cause_parts.append(
                f"{type(cause).__name__}: {cause}"
            )
            cause = cause.__cause__

        combined = _combined_text(
            error_name,
            message,
            *cause_parts,
        )
    else:
        combined = _combined_text(error)

    if any(
        marker in combined
        for marker in (
            "permission denied",
            "access is denied",
            "operation not permitted",
            "winerror 5",
        )
    ):
        return FailureClassification(
            category=FailureCategory.PERMISSION,
            source=source,
            reason_code="PATCH_PERMISSION_DENIED",
            confidence=0.98,
        )

    if any(
        marker in combined
        for marker in (
            "jsondecodeerror",
            "invalid json",
            "json object",
            "json???????",
        )
    ):
        return FailureClassification(
            category=FailureCategory.JSON,
            source=source,
            reason_code="PATCH_JSON_INVALID",
            confidence=0.95,
        )

    if any(
        marker in combined
        for marker in (
            "not a git repository",
            "index.lock",
            "git repository",
            "rollback",
            "restore failed",
            "checkout failed",
            "reset failed",
            "fatal:",
        )
    ):
        return FailureClassification(
            category=FailureCategory.GIT,
            source=source,
            reason_code="PATCH_GIT_FAILURE",
            confidence=0.93,
        )

    if any(
        marker in combined
        for marker in (
            "patch does not apply",
            "patch failed",
            "git apply --check",
            "hunk failed",
            "malformed patch",
            "corrupt patch",
            "unidiff",
            "unified diff",
            "patch text",
            "patch check",
            "patch apply",
            "patch sha-256",
            "patch sha256",
            "planner?backup???",
            "?????",
            "??????",
            "patch_applied",
            "patch_checked",
        )
    ):
        return FailureClassification(
            category=FailureCategory.PATCH,
            source=source,
            reason_code="PATCH_CONTENT_FAILURE",
            confidence=0.94,
        )

    classification = classify_exception(
        (
            error
            if isinstance(error, BaseException)
            else RuntimeError(str(error))
        ),
        source=source,
    )

    if (
        classification.category
        == FailureCategory.UNKNOWN
    ):
        return FailureClassification(
            category=FailureCategory.RUNTIME,
            source=source,
            reason_code="PATCH_RUNTIME_FAILURE",
            confidence=0.65,
        )

    return classification


def classify_code_generation_failure(
    error: BaseException | str,
) -> FailureClassification:
    if isinstance(error, BaseException):
        error_name = type(error).__name__
        message = str(error)

        cause = error.__cause__
        cause_parts: list[str] = []

        while cause is not None:
            cause_parts.append(
                f"{type(cause).__name__}: {cause}"
            )
            cause = cause.__cause__

        combined = _combined_text(
            error_name,
            message,
            *cause_parts,
        )
    else:
        combined = _combined_text(error)

    if any(
        marker in combined
        for marker in (
            "timeout",
            "timed out",
            "ollamatimeouterror",
        )
    ):
        return FailureClassification(
            category=FailureCategory.TIMEOUT,
            source="CODE_GENERATION",
            reason_code="CODE_GENERATION_TIMEOUT",
            confidence=0.98,
        )

    if any(
        marker in combined
        for marker in (
            "jsondecodeerror",
            "contract json",
            "json object",
            "invalid json",
            "json???????",
            "json object???????",
            "json???",
        )
    ):
        return FailureClassification(
            category=FailureCategory.JSON,
            source="CODE_GENERATION",
            reason_code="CODE_GENERATION_JSON_INVALID",
            confidence=0.96,
        )

    if any(
        marker in combined
        for marker in (
            "patch integration",
            "patch check",
            "patch does not apply",
            "patch integration??",
            "patch integration?????",
            "hunk",
            "malformed patch",
        )
    ):
        return FailureClassification(
            category=FailureCategory.PATCH,
            source="CODE_GENERATION",
            reason_code="CODE_GENERATION_PATCH_FAILURE",
            confidence=0.95,
        )

    if any(
        marker in combined
        for marker in (
            "ollama",
            "llm",
            "model response",
            "model output",
            "generation pipeline",
            "codegenerationllmadaptererror",
            "codegenerationllmpipelineerror",
        )
    ):
        return FailureClassification(
            category=FailureCategory.LLM,
            source="CODE_GENERATION",
            reason_code="CODE_GENERATION_LLM_FAILURE",
            confidence=0.94,
        )

    classification = classify_exception(
        (
            error
            if isinstance(error, BaseException)
            else RuntimeError(str(error))
        ),
        source="CODE_GENERATION",
    )

    if (
        classification.category
        == FailureCategory.UNKNOWN
    ):
        return FailureClassification(
            category=FailureCategory.RUNTIME,
            source="CODE_GENERATION",
            reason_code="CODE_GENERATION_RUNTIME_FAILURE",
            confidence=0.65,
        )

    return classification


def classify_exception(
    error: BaseException,
    *,
    source: str = "EXCEPTION",
) -> FailureClassification:
    exception_name = type(error).__name__
    text = _combined_text(
        exception_name,
        str(error),
    )

    if isinstance(error, TimeoutError):
        category = FailureCategory.TIMEOUT
        reason_code = "EXCEPTION_TIMEOUT"
    elif isinstance(error, PermissionError):
        category = FailureCategory.PERMISSION
        reason_code = "EXCEPTION_PERMISSION"
    elif isinstance(error, FileNotFoundError):
        category = FailureCategory.DEPENDENCY
        reason_code = "EXCEPTION_FILE_NOT_FOUND"
    elif (
        isinstance(error, SyntaxError)
        or "syntaxerror" in text
    ):
        category = FailureCategory.SYNTAX
        reason_code = "EXCEPTION_SYNTAX"
    elif (
        "jsondecodeerror" in text
        or "invalid json" in text
    ):
        category = FailureCategory.JSON
        reason_code = "EXCEPTION_JSON"
    elif (
        "modulenotfounderror" in text
        or "importerror" in text
    ):
        category = FailureCategory.IMPORT
        reason_code = "EXCEPTION_IMPORT"
    elif any(
        marker in text
        for marker in (
            "ollama",
            "llm",
            "model response",
            "model output",
            "generation pipeline",
        )
    ):
        category = FailureCategory.LLM
        reason_code = "EXCEPTION_LLM"
    elif any(
        marker in text
        for marker in (
            "patch",
            "hunk",
            "diff",
        )
    ):
        category = FailureCategory.PATCH
        reason_code = "EXCEPTION_PATCH"
    elif isinstance(
        error,
        (
            RuntimeError,
            TypeError,
            ValueError,
            AttributeError,
            KeyError,
            IndexError,
        ),
    ):
        category = FailureCategory.RUNTIME
        reason_code = "EXCEPTION_RUNTIME"
    else:
        category = FailureCategory.UNKNOWN
        reason_code = "EXCEPTION_UNKNOWN"

    return FailureClassification(
        category=category,
        source=source,
        reason_code=reason_code,
        confidence=(
            0.95
            if category
            != FailureCategory.UNKNOWN
            else 0.30
        ),
    )


def serialize_failure_classification(
    classification: FailureClassification,
) -> dict[str, Any]:
    return {
        "classifier_version": (
            FAILURE_CLASSIFIER_VERSION
        ),
        "failure_category": (
            classification.category.value
        ),
        "classification_source": (
            classification.source
        ),
        "reason_code": (
            classification.reason_code
        ),
        "confidence": (
            classification.confidence
        ),
    }
