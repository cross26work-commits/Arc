from pathlib import Path
import subprocess

from app.missions import verification_runner


def test_run_single_command_isolates_standard_fds(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)

        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="verification ok",
            stderr="",
        )

    monkeypatch.setattr(
        verification_runner.subprocess,
        "run",
        fake_run,
    )

    result = verification_runner._run_single_command(
        name="Python check",
        argv=["python", "-c", "print('ok')"],
        cwd=Path(".").resolve(),
        timeout_seconds=30,
        category="SYNTAX",
    )

    assert result["passed"] is True
    assert result["returncode"] == 0
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["stdout"] is subprocess.PIPE
    assert captured["stderr"] is subprocess.PIPE
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert captured["close_fds"] is True
    assert captured["check"] is False
    assert captured["timeout"] == 30
