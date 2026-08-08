from app.missions.analysis_reporting_runner import (
    _build_human_summary,
    _extract_recommendations,
)


def _planning_with_stub_warning() -> dict:
    return {
        "selected_files": [
            {
                "path": "backend/app/api/auth.py",
                "warnings": [
                    {
                        "level": "medium",
                        "code": "STUB_ROUTE_HANDLER",
                        "message": (
                            "Stub route handlers detected: "
                            "login_stub, register_stub, logout_stub"
                        ),
                    }
                ],
            }
        ],
        "workstreams": [
            {
                "title": "Backend?API",
            }
        ],
        "execution_order": [
            "Backend?API",
        ],
    }


def test_reporting_recommendations_surface_semantic_finding() -> None:
    recommendations = _extract_recommendations(
        {},
        _planning_with_stub_warning(),
    )

    text = str(recommendations)

    assert "backend/app/api/auth.py" in text
    assert "STUB_ROUTE_HANDLER" in text
    assert "login_stub" in text


def test_human_summary_surfaces_concrete_next_mission() -> None:
    planning = _planning_with_stub_warning()

    recommendations = _extract_recommendations(
        {},
        planning,
    )

    summary = _build_human_summary(
        mission={
            "title": "Profit Radar analysis",
            "objective": "Analyze Profit Radar",
            "project_name": "Profit Radar",
        },
        analysis={
            "candidates": [],
        },
        planning=planning,
        recommendations=recommendations,
        risks=[],
    )

    assert "backend/app/api/auth.py" in summary
    assert "STUB_ROUTE_HANDLER" in summary
    assert "login_stub" in summary
