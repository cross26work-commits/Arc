import subprocess

import pytest

from app.missions.implementation_runner import (
    MissionImplementationError,
    _patch_implementation_error,
    _run_git_apply_check,
)


def test_implementation_error_exposes_category():
    error = _patch_implementation_error(
        RuntimeError(
            "patch does not apply"
        ),
        source="IMPLEMENTATION_PATCH_TEST",
    )

    assert error.failure_category == "PATCH"

    assert error.failure_classification[
        "classification_source"
    ] == "IMPLEMENTATION_PATCH_TEST"


def test_plain_implementation_error_has_no_category():
    error = MissionImplementationError(
        "plain failure"
    )

    assert error.failure_category is None
    assert error.failure_classification is None


def test_git_apply_check_failure_is_classified(
    monkeypatch,
    tmp_path,
):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="error: patch does not apply",
        )

    monkeypatch.setattr(
        subprocess,
        "run",
        fake_run,
    )

    with pytest.raises(
        MissionImplementationError
    ) as caught:
        _run_git_apply_check(
            project_root=tmp_path,
            patch_path=(
                tmp_path / "proposed.patch"
            ),
        )

    assert caught.value.failure_category == "PATCH"


def test_git_apply_check_timeout_is_classified(
    monkeypatch,
    tmp_path,
):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="git apply --check",
            timeout=60,
        )

    monkeypatch.setattr(
        subprocess,
        "run",
        fake_run,
    )

    with pytest.raises(
        MissionImplementationError
    ) as caught:
        _run_git_apply_check(
            project_root=tmp_path,
            patch_path=(
                tmp_path / "proposed.patch"
            ),
        )

    assert caught.value.failure_category == "TIMEOUT"
