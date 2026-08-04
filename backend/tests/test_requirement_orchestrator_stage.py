from app.missions.mission_orchestrator import (
    AUTOMATIC_EXECUTION_STAGES,
    MISSION_ORCHESTRATOR_VERSION,
    determine_mission_stage,
)


def _task(
    task_type: str,
    status: str,
) -> dict:
    return {
        "task_type": task_type,
        "status": status,
        "result": None,
    }


def _implementation_mission(
    *,
    requirements_status: str,
    analysis_status: str = "PENDING",
) -> dict:
    return {
        "id": 1,
        "mission_type": "IMPLEMENTATION",
        "status": "DRAFT",
        "tasks": [
            _task(
                "REQUIREMENTS",
                requirements_status,
            ),
            _task(
                "ANALYSIS",
                analysis_status,
            ),
            _task(
                "PLANNING",
                "PENDING",
            ),
            _task(
                "APPROVAL",
                "PENDING",
            ),
            _task(
                "IMPLEMENTATION",
                "PENDING",
            ),
            _task(
                "VERIFICATION",
                "PENDING",
            ),
            _task(
                "REPORTING",
                "PENDING",
            ),
        ],
    }


def test_requirements_stage_is_automatic() -> None:
    assert "RUN_REQUIREMENTS" in (
        AUTOMATIC_EXECUTION_STAGES
    )
    assert MISSION_ORCHESTRATOR_VERSION == (
        "mission-orchestrator-v0.3"
    )


def test_ready_requirements_returns_run_stage() -> None:
    decision = determine_mission_stage(
        _implementation_mission(
            requirements_status="READY",
        )
    )

    assert decision["stage"] == (
        "RUN_REQUIREMENTS"
    )
    assert decision["executable"] is True
    assert (
        decision["requires_master_action"]
        is False
    )


def test_running_requirements_returns_run_stage() -> None:
    decision = determine_mission_stage(
        _implementation_mission(
            requirements_status="RUNNING",
        )
    )

    assert decision["stage"] == (
        "RUN_REQUIREMENTS"
    )


def test_completed_requirements_advances_to_analysis() -> None:
    decision = determine_mission_stage(
        _implementation_mission(
            requirements_status="COMPLETED",
            analysis_status="READY",
        )
    )

    assert decision["stage"] == "RUN_ANALYSIS"


def test_failed_requirements_blocks_mission() -> None:
    decision = determine_mission_stage(
        _implementation_mission(
            requirements_status="FAILED",
        )
    )

    assert decision["stage"] == (
        "STATE_BLOCKED"
    )
    assert decision["executable"] is False
    assert (
        decision["requires_master_action"]
        is True
    )
