import json
from types import SimpleNamespace

from app.missions.code_generation_prompt_builder import (
    _filter_context_for_targets,
    _reference_files_for_step,
)


def _operation(path: str, category: str):
    return SimpleNamespace(
        path=path,
        operation="UPDATE",
        purpose="test",
        category=category,
        language="python",
        depends_on=[],
        affected_files=[],
        risk_level="UNKNOWN",
        reasons=[],
    )


def _plan():
    source = _operation(
        "src/calculator.py",
        "BACKEND",
    )

    tests = _operation(
        "tests/test_calculator.py",
        "TEST",
    )

    step1 = SimpleNamespace(
        step_id="step-1",
        file_operations=[source],
        depends_on_steps=[],
    )

    step2 = SimpleNamespace(
        step_id="step-2",
        file_operations=[tests],
        depends_on_steps=["step-1"],
    )

    return SimpleNamespace(
        steps=[step1, step2],
    )


def test_reference_files_include_dependency_step():
    plan = _plan()

    result = _reference_files_for_step(
        plan=plan,
        step=plan.steps[1],
        target_files=[
            "tests/test_calculator.py"
        ],
    )

    assert result == [
        "src/calculator.py"
    ]


def test_context_contains_reference_files():
    context = {
        "files": [
            {
                "relative_path": "src/calculator.py",
                "source": {
                    "content": "def multiply(left, right):\n    return left * right\n"
                },
            },
            {
                "relative_path": "tests/test_calculator.py",
                "source": {
                    "content": "from src.calculator import add\n"
                },
            },
            {
                "relative_path": "README.md",
                "source": {
                    "content": "README"
                },
            },
        ]
    }

    result = _filter_context_for_targets(
        context=context,
        target_files=[
            "tests/test_calculator.py"
        ],
        reference_files=[
            "src/calculator.py"
        ],
    )

    access = {
        item["relative_path"]: item["scope_access"]
        for item in result["files"]
    }

    assert access == {
        "src/calculator.py": "READ_ONLY",
        "tests/test_calculator.py": "EDIT",
    }


def test_reference_source_is_kept():
    context = {
        "files": [
            {
                "relative_path": "src/calculator.py",
                "source": {
                    "content": "def multiply(left, right):\n    return left * right\n"
                },
            },
            {
                "relative_path": "tests/test_calculator.py",
                "source": {
                    "content": ""
                },
            },
        ]
    }

    result = _filter_context_for_targets(
        context=context,
        target_files=[
            "tests/test_calculator.py"
        ],
        reference_files=[
            "src/calculator.py"
        ],
    )

    serialized = json.dumps(
        result,
        ensure_ascii=False,
    )

    assert "def multiply" in serialized
    assert "README.md" not in serialized


def test_scope_metadata():
    result = _filter_context_for_targets(
        context={
            "files": []
        },
        target_files=[
            "tests/test_calculator.py"
        ],
        reference_files=[
            "src/calculator.py"
        ],
    )

    assert result["scope"]["reference_files"] == [
        "src/calculator.py"
    ]

    assert (
        result["scope"]["reference_files_read_only"]
        is True
    )
