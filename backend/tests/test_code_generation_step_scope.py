import json

from app.missions.code_generation_prompt_builder import (
    _filter_context_for_targets,
)
from app.missions.code_generation_runner import (
    _build_ollama_response_schema,
)


def _context() -> dict:
    return {
        "mission_id": 8,
        "context_sha256": "a" * 64,
        "files": [
            {
                "relative_path":
                    "src/calculator.py",
                "source": {
                    "included": True,
                    "content": (
                        "def add():\n"
                        "    pass\n"
                    ),
                    "sha256": "b" * 64,
                },
            },
            {
                "relative_path":
                    "tests/test_calculator.py",
                "source": {
                    "included": True,
                    "content": (
                        "def test_add():\n"
                        "    pass\n"
                    ),
                    "sha256": "c" * 64,
                },
            },
        ],
    }


def test_filters_context_to_target_file() -> None:
    result = _filter_context_for_targets(
        context=_context(),
        target_files=["src/calculator.py"],
    )

    assert [
        item["relative_path"]
        for item in result["files"]
    ] == ["src/calculator.py"]


def test_filtered_context_preserves_source() -> None:
    result = _filter_context_for_targets(
        context=_context(),
        target_files=["src/calculator.py"],
    )

    assert result["files"][0][
        "source"
    ]["content"] == (
        "def add():\n"
        "    pass\n"
    )


def test_filtered_context_excludes_other_files() -> None:
    result = _filter_context_for_targets(
        context=_context(),
        target_files=["src/calculator.py"],
    )

    serialized = json.dumps(
        result,
        ensure_ascii=False,
    )

    assert "src/calculator.py" in serialized
    assert (
        "tests/test_calculator.py"
        not in serialized
    )


def test_schema_restricts_edit_paths() -> None:
    schema = _build_ollama_response_schema(
        mission_id=8,
        context_sha256="a" * 64,
        target_files=["src/calculator.py"],
    )

    variants = schema[
        "$defs"
    ]["CodeGenerationEdit"]["oneOf"]

    for variant in variants:
        assert variant[
            "properties"
        ]["path"]["enum"] == [
            "src/calculator.py"
        ]


def test_schema_remains_compatible_without_scope() -> None:
    schema = _build_ollama_response_schema(
        mission_id=8,
        context_sha256="a" * 64,
    )

    variants = schema[
        "$defs"
    ]["CodeGenerationEdit"]["oneOf"]

    for variant in variants:
        assert "enum" not in variant[
            "properties"
        ]["path"]
