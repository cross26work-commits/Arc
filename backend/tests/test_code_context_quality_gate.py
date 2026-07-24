from __future__ import annotations

from copy import deepcopy

from app.code_context.quality_gate import (
    evaluate_code_context,
)
from app.main import app


def _valid_context() -> dict:
    return {
        "context_version": (
            "mission-code-context-v0.1"
        ),
        "context_sha256": "a" * 64,
        "mission": {
            "objective": (
                "対象コードへ安全な変更を追加する"
            ),
        },
        "limits": {
            "maximum_total_bytes": 1_000_000,
        },
        "summary": {
            "candidate_file_count": 2,
            "included_file_count": 2,
            "included_total_bytes": 200,
            "analysis_error_count": 0,
            "dependency_error_count": 0,
        },
        "files": [
            {
                "relative_path": "app/a.py",
                "source": {
                    "included": True,
                    "content": "def a():\n    pass\n",
                    "sha256": "b" * 64,
                },
                "static_analysis": {
                    "language": "python",
                    "functions": [
                        {
                            "name": "a",
                        }
                    ],
                },
                "dependency": {
                    "summary": {
                        "affected_count": 0,
                    },
                    "risk": {
                        "level": "low",
                    },
                },
            },
            {
                "relative_path": "app/b.py",
                "source": {
                    "included": True,
                    "content": "def b():\n    pass\n",
                    "sha256": "c" * 64,
                },
                "static_analysis": {
                    "language": "python",
                    "functions": [
                        {
                            "name": "b",
                        }
                    ],
                },
                "dependency": {
                    "summary": {
                        "affected_count": 0,
                    },
                    "risk": {
                        "level": "low",
                    },
                },
            },
        ],
    }


def test_valid_context_is_ready():
    result = evaluate_code_context(
        _valid_context()
    )

    assert result["passed"] is True
    assert (
        result["quality_level"]
        == "READY"
    )
    assert result["score"] == 100
    assert (
        result["next_stage"]
        == "CODE_GENERATION"
    )
    assert result["blocking_reasons"] == []


def test_missing_content_blocks_generation():
    context = _valid_context()

    context["files"][0]["source"][
        "included"
    ] = False
    context["files"][0]["source"][
        "content"
    ] = None
    context["summary"][
        "included_file_count"
    ] = 1

    result = evaluate_code_context(
        context
    )

    assert result["passed"] is False
    assert (
        result["quality_level"]
        == "BLOCKED"
    )
    assert (
        result["next_stage"]
        == "CONTEXT_REBUILD_REQUIRED"
    )

    failed_names = {
        item["name"]
        for item in result["checks"]
        if item["passed"] is False
    }

    assert "included_ratio" in failed_names
    assert "source_content" in failed_names


def test_analysis_error_ratio_blocks():
    context = _valid_context()

    context["summary"][
        "analysis_error_count"
    ] = 1

    result = evaluate_code_context(
        context
    )

    assert result["passed"] is False

    check = next(
        item
        for item in result["checks"]
        if (
            item["name"]
            == "analysis_error_ratio"
        )
    )

    assert check["passed"] is False


def test_warning_does_not_block():
    context = _valid_context()

    del context["files"][0][
        "static_analysis"
    ]

    result = evaluate_code_context(
        context
    )

    assert result["passed"] is True
    assert (
        result["quality_level"]
        == "READY_WITH_WARNINGS"
    )
    assert result["warnings"]


def test_quality_route_registered():
    schema = app.openapi()

    path = (
        "/missions/{mission_id}"
        "/context/quality"
    )

    assert path in schema["paths"]
    assert (
        "get"
        in schema["paths"][path]
    )
