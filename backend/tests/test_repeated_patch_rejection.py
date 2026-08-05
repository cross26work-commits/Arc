from app.missions.code_generation_runner import (
    _mark_generation_step_failed,
)
from app.missions.implementation_step_state import (
    initialize_step_execution,
)
from app.missions.models import (
    ImplementationPlan,
)


def test_repeated_patch_failure_state() -> None:
    plan = ImplementationPlan.model_validate(
        {
            "plan_version":
                "implementation-plan-v0.1",
            "mission_id": 1,
            "project_id": 1,
            "project_name": "Fixture",
            "objective": "Test repeated patch rejection.",
            "success_criteria": [
                "Repeated patch is rejected."
            ],
            "requirement_contract_version":
                "requirement-contract-v0.1",
            "requirement_contract": {
                "contract_version":
                    "requirement-contract-v0.1",
                "objective": "Test.",
                "requirements": ["Test."],
                "success_criteria": ["Pass."],
                "in_scope": ["tests"],
                "out_of_scope": [],
                "constraints": [],
                "ambiguities": [],
                "missing_information": [],
                "risks": [],
                "implementation_possible": True,
                "analysis_summary": "Test.",
            },
            "implementation_possible": True,
            "clarification_required": False,
            "clarification_questions": [],
            "selected_files": [
                {
                    "path": "tests/test_example.py",
                    "operation": "UPDATE",
                    "purpose": "Test",
                    "category": "TEST",
                    "language": "python",
                    "depends_on": [],
                    "affected_files": [],
                    "risk_level": "LOW",
                    "reasons": [],
                }
            ],
            "steps": [
                {
                    "step_id": "step-1",
                    "position": 1,
                    "title": "Test",
                    "description": "Test",
                    "category": "TEST",
                    "file_operations": [
                        {
                            "path":
                                "tests/test_example.py",
                            "operation": "UPDATE",
                            "purpose": "Test",
                            "category": "TEST",
                            "language": "python",
                            "depends_on": [],
                            "affected_files": [],
                            "risk_level": "LOW",
                            "reasons": [],
                        }
                    ],
                    "depends_on_steps": [],
                    "can_run_in_parallel": False,
                    "verification_commands": [],
                    "completion_criteria": [
                        "Pass."
                    ],
                    "risk_level": "LOW",
                }
            ],
            "execution_order": ["step-1"],
            "verification_commands": [],
            "file_execution_order": [
                "tests/test_example.py"
            ],
            "dependency_graph": {
                "graph_version":
                    "dependency-planner-v0.1",
                "node_count": 1,
                "edge_count": 0,
                "nodes": [],
                "edges": [],
            },
            "dependency_cycles": [],
            "parallel_groups": [["step-1"]],
            "overall_risk_level": "LOW",
            "estimated_effort_level": "SMALL",
            "approval_summary": "Test.",
        }
    )

    execution = initialize_step_execution(plan)

    execution.results[
        "step-1"
    ].status = "GENERATING"

    updated = _mark_generation_step_failed(
        execution=execution,
        error=(
            "Generated repair patch matches "
            "the previously failed patch SHA256."
        ),
    )

    step = updated.results["step-1"]

    assert step.status == "FAILED"
    assert "previously failed patch" in (
        step.error or ""
    )
