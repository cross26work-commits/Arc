from __future__ import annotations

from typing import Any

from app.missions.router import list_missions_endpoint


def test_mission_list_response_includes_mission_type(
    isolated_arc_environment: dict[str, Any],
) -> None:
    summaries = list_missions_endpoint(
        project_id=1,
        limit=50,
    )

    assert summaries

    mission = next(
        item
        for item in summaries
        if item.id == 1
    )

    assert mission.project_id == 1
    assert mission.mission_type == "IMPLEMENTATION"
    assert mission.status == "CANCELLED"
