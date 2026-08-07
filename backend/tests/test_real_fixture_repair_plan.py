import json
from pathlib import Path
from unittest.mock import patch

from app.missions.self_repair_planner import (
    run_self_repair_planner,
)


MISSION_ID = 36

FAILURE_PATH = Path(
    r"C:\Users\closs\Arc"
    r"\data\real_fixture_failure.json"
)


def _failure_evidence():
    return json.loads(
        FAILURE_PATH.read_text(
            encoding="utf-8"
        )
    )


def _mission():
    evidence = _failure_evidence()

    planning_result = {
        "selected_files": [
            {
                "path": (
                    "src/calculator.py"
                ),
                "operation": "UPDATE",
                "purpose": (
                    "Repair multiply implementation."
                ),
                "category": "BACKEND",
            }
        ],
        "implementation_plan": {
            "steps": [
                {
                    "step_id": "step-1",
                    "position": 1,
                    "title": (
                        "Repair calculator multiply"
                    ),
                    "description": (
                        "Restore multiplication behavior."
                    ),
                    "target_files": [
                        "src/calculator.py",
                    ],
                }
            ],
        },
        "verification_commands": [
            "python -m pytest -q",
        ],
    }

    implementation_result = {
        "mode": "PATCH_APPLIED",
        "status": "COMPLETED",
        "patch_applied": True,
        "changed_files": [
            "src/calculator.py",
        ],
    }

    verification_results = [
        {
            **item,
            "suspected_files": (
                evidence["suspected_files"]
            ),
        }
        for item in evidence[
            "verification"
        ]["results"]
    ]

    verification_result = {
        **evidence["verification"],
        "results": verification_results,
        "failed_results": verification_results,
        "failure_source": (
            evidence["failure_source"]
        ),
        "failure_category": (
            evidence["failure_category"]
        ),
        "reason_code": (
            evidence["reason_code"]
        ),
        "suspected_files": (
            evidence["suspected_files"]
        ),
        "file_evidence": (
            evidence["file_evidence"]
        ),
        "expected_repair": (
            evidence["expected_repair"]
        ),
    }

    return {
        "id": MISSION_ID,
        "project_id": 1,
        "project_name": "ArcRepairFixture",
        "project_path": (
            r"C:\Users\closs"
            r"\ArcRepairFixture"
        ),
        "title": (
            "Repair real multiply failure"
        ),
        "objective": (
            "Restore multiply implementation "
            "and pass pytest."
        ),
        "status": "RUNNING",
        "progress": 70,
        "tasks": [
            {
                "task_type": "PLANNING",
                "status": "COMPLETED",
                "result": json.dumps(
                    planning_result,
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "APPROVAL",
                "status": "COMPLETED",
                "result": json.dumps(
                    {
                        "decision": "APPROVED",
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "IMPLEMENTATION",
                "status": "READY",
                "result": json.dumps(
                    implementation_result,
                    ensure_ascii=False,
                ),
            },
            {
                "task_type": "VERIFICATION",
                "status": "FAILED",
                "result": json.dumps(
                    verification_result,
                    ensure_ascii=False,
                ),
            },
        ],
    }


def test_real_fixture_failure_creates_repair_plan(
    tmp_path,
):
    mission = _mission()

    with (
        patch(
            "app.missions.self_repair_planner."
            "get_mission",
            return_value=mission,
        ),
        patch(
            "app.missions.self_repair_planner."
            "REPAIR_PLAN_ROOT",
            tmp_path,
        ),
        patch(
            "app.missions.self_repair_planner."
            "add_mission_log",
        ) as log_mock,
    ):
        result = run_self_repair_planner(
            mission_id=MISSION_ID
        )

    plan = result["repair_plan"]

    assert plan["status"] == "PLANNED"
    assert plan["auto_apply"] is False

    assert plan[
        "failure_source"
    ] == "VERIFICATION"

    verification = plan[
        "verification"
    ]

    assert verification[
        "failure_category"
    ] == "TEST"

    assert plan[
        "suspected_files"
    ] == [
        "src/calculator.py",
    ]

    assert (
        plan[
            "verification_failure_signature"
        ]
    )

    assert result["storage"][
        "duplicate"
    ] is False

    latest_path = Path(
        result["storage"]["latest_path"]
    )

    if not latest_path.is_absolute():
        latest_path = (
            Path.cwd().parent
            / latest_path
        )

    assert latest_path.exists()

    event_types = [
        call.kwargs.get("event_type")
        for call in log_mock.call_args_list
    ]

    assert (
        "MISSION_REPAIR_PLAN_CREATED"
        in event_types
    )
