from app.missions.repair_policy import (
    REPAIR_POLICY_VERSION,
)
from app.missions.self_repair_planner import (
    _build_repair_plan,
    _normalize_category,
)


def _mission():
    return {
        "id": 36,
        "project_id": 1,
        "project_name": "Arc",
        "title": "Repair Policy integration",
        "objective": "Test policy integration",
    }


def _verification(category: str):
    return {
        "verification_version": "test-v1",
        "failure_category": category,
        "requested_command_count": 1,
        "executed_command_count": 1,
    }


def _failure(category: str):
    return {
        "name": "test-command",
        "command": ["python", "-m", "pytest"],
        "category": "TEST",
        "failure_category": category,
        "returncode": 1,
        "timed_out": False,
        "stdout": "",
        "stderr": "test failure",
        "suspected_files": [
            "backend/app/example.py",
        ],
    }


def test_planner_normalizer_uses_shared_policy():
    assert _normalize_category("syntax") == "SYNTAX"
    assert (
        _normalize_category("unsupported-value")
        == "UNKNOWN"
    )


def test_build_repair_plan_includes_policy():
    plan = _build_repair_plan(
        mission=_mission(),
        verification=_verification("BUILD"),
        failures=[_failure("BUILD")],
    )

    assert plan["verification"][
        "failure_category"
    ] == "BUILD"

    assert plan["repair_policy"] == {
        "policy_version": REPAIR_POLICY_VERSION,
        "failure_category": "BUILD",
        "repair_action": "REGENERATE_CODE",
        "resume_stage": "RUN_CODE_GENERATION",
        "max_retries": 2,
        "requires_approval": False,
    }


def test_unknown_failure_creates_safe_stop_policy():
    plan = _build_repair_plan(
        mission=_mission(),
        verification=_verification("INVALID"),
        failures=[_failure("INVALID")],
    )

    assert plan["verification"][
        "failure_category"
    ] == "UNKNOWN"

    assert plan["repair_policy"][
        "repair_action"
    ] == "STOP_AND_INSPECT"

    assert plan["repair_policy"][
        "resume_stage"
    ] == "STOPPED"

    assert plan["repair_policy"][
        "requires_approval"
    ] is True
