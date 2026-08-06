from app.missions.verification_runner import (
    _classify_failure,
)


def test_verification_classifier_uses_shared_patch_category():
    assert (
        _classify_failure(
            command_name="git apply",
            stdout="",
            stderr="patch does not apply",
            timed_out=False,
            returncode=1,
        )
        == "PATCH"
    )


def test_verification_classifier_keeps_test_category():
    assert (
        _classify_failure(
            command_name="pytest",
            stdout="1 failed",
            stderr="",
            timed_out=False,
            returncode=1,
        )
        == "TEST"
    )


def test_verification_classifier_keeps_timeout_category():
    assert (
        _classify_failure(
            command_name="pytest",
            stdout="",
            stderr="",
            timed_out=True,
            returncode=None,
        )
        == "TIMEOUT"
    )
