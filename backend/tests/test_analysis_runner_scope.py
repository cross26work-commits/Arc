from __future__ import annotations

from typing import Any

from app.missions import analysis_runner


COMPREHENSIVE_OBJECTIVE = (
    "Profit Radar\u306e\u73fe\u5728\u306e\u5b9f\u88c5\u72b6\u614b"
    "\u3092\u65e2\u5b58\u30b3\u30fc\u30c9\u304b\u3089"
    "\u7dcf\u5408\u5206\u6790\u3059\u308b\u3002"
    "\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u5168\u4f53"
    "\u306b\u3064\u3044\u3066\u3001"
    "\u30d0\u30c3\u30af\u30a8\u30f3\u30c9\u30fb"
    "\u30d5\u30ed\u30f3\u30c8\u30a8\u30f3\u30c9\u30fb"
    "API\u30fb\u8a8d\u8a3c\u30fbGmail\u9023\u643a\u30fb"
    "DB\u306e\u63a5\u7d9a\u72b6\u614b\u3092"
    "\u8abf\u67fb\u3059\u308b\u3002"
    "\u4eca\u65e5\u306e\u53ce\u76ca\u3092\u5b9f\u6570\u3067"
    "\u56de\u7b54\u3067\u304d\u308b\u72b6\u614b\u307e\u3067"
    "\u306e\u6b8b\u8ab2\u984c\u3092\u78ba\u8a8d\u3059\u308b\u3002"
    "\u30c6\u30b9\u30c8\u69cb\u6210\u3001"
    "\u30bb\u30ad\u30e5\u30ea\u30c6\u30a3\u3001"
    "\u30c7\u30fc\u30bf\u6574\u5408\u6027\u3001"
    "\u672a\u5b8c\u6210\u30fb\u4eee\u5b9f\u88c5\u30fb"
    "\u6f5c\u5728\u7684\u30d0\u30b0\u3092"
    "\u78ba\u8a8d\u3059\u308b\u3002"
)


def test_comprehensive_analysis_tokens_cover_required_domains() -> None:
    tokens = analysis_runner._tokenize_objective(
        COMPREHENSIVE_OBJECTIVE,
    )

    token_set = set(tokens)

    assert "backend" in token_set
    assert "frontend" in token_set
    assert "auth" in token_set
    assert "gmail" in token_set
    assert "test" in token_set
    assert "security" in token_set

    assert token_set.intersection(
        {"db", "database", "supabase"},
    )
    assert token_set.intersection(
        {"profit", "revenue", "results"},
    )


def test_comprehensive_analysis_does_not_drop_audit_terms(
    monkeypatch,
) -> None:
    seen_queries: list[str] = []

    mission: dict[str, Any] = {
        "id": 999,
        "project_id": 1,
        "objective": COMPREHENSIVE_OBJECTIVE,
        "tasks": [
            {
                "id": 1001,
                "task_type": "ANALYSIS",
                "status": "RUNNING",
            }
        ],
    }

    monkeypatch.setattr(
        analysis_runner,
        "get_mission",
        lambda mission_id: mission,
    )

    monkeypatch.setattr(
        analysis_runner,
        "_get_project",
        lambda project_id: {
            "id": project_id,
            "name": "Test Project",
            "path": "C:/fake-project",
        },
    )

    def fake_search_project(
        *,
        project_id: int,
        query: str,
        max_results: int,
    ) -> dict[str, Any]:
        seen_queries.append(query)
        return {"results": []}

    monkeypatch.setattr(
        analysis_runner,
        "search_project",
        fake_search_project,
    )

    monkeypatch.setattr(
        analysis_runner,
        "_rank_candidate_files",
        lambda search_results, max_candidates=12: [
            {
                "path": "backend/app/main.py",
                "score": 1,
                "reasons": ["test"],
            }
        ],
    )

    monkeypatch.setattr(
        analysis_runner,
        "_analyze_candidates",
        lambda **kwargs: [
            {
                "path": "backend/app/main.py",
                "score": 1,
                "matched_query_count": 1,
                "reasons": ["test"],
                "role": "entrypoint",
                "language": "python",
                "metrics": {},
                "routes": [],
                "api_calls": [],
                "sdk_calls": [],
                "warnings": [],
                "dependency": {
                    "direct_dependencies": [],
                    "direct_dependents": [],
                    "affected_count": 0,
                    "risk": None,
                    "error": None,
                },
            }
        ],
    )

    monkeypatch.setattr(
        analysis_runner,
        "update_mission_task",
        lambda **kwargs: mission,
    )

    monkeypatch.setattr(
        analysis_runner,
        "add_mission_log",
        lambda **kwargs: None,
    )

    seen_candidate_limits: list[int] = []

    def capture_rank_candidate_files(
        search_results,
        max_candidates=12,
    ):
        seen_candidate_limits.append(max_candidates)
        return [
            {
                "path": "backend/app/main.py",
                "score": 1,
                "reasons": ["test"],
            }
        ]

    monkeypatch.setattr(
        analysis_runner,
        "_rank_candidate_files",
        capture_rank_candidate_files,
    )

    analysis_runner._run_mission_analysis_impl(999)

    assert {
        "dashboard",
        "health",
        "service",
        "test",
        "error",
    }.issubset(set(seen_queries))

    assert seen_candidate_limits
    assert seen_candidate_limits[0] > 12


def test_focused_analysis_stays_focused() -> None:
    objective = (
        "\u30ed\u30b0\u30a4\u30f3\u8a8d\u8a3c"
        "\u3060\u3051\u3092\u8abf\u67fb\u3059\u308b\u3002"
    )

    tokens = analysis_runner._tokenize_objective(
        objective,
    )

    token_set = set(tokens)

    assert "auth" in token_set
    assert "login" in token_set
    assert "session" in token_set

    assert "dashboard" not in token_set
    assert "health" not in token_set
    assert "test" not in token_set



def test_analysis_ranking_prefers_runtime_code_over_docs() -> None:
    search_results = []

    for query in [
        "api",
        "auth",
        "gmail",
        "settings",
        "config",
    ]:
        search_results.append(
            {
                "path": "docs/API_DESIGN.md",
                "query": query,
                "symbol_name": None,
            }
        )

    for query in [
        "auth",
        "api",
    ]:
        search_results.append(
            {
                "path": "backend/app/api/auth.py",
                "query": query,
                "symbol_name": None,
            }
        )

    ranked = analysis_runner._rank_candidate_files(
        search_results,
        max_candidates=2,
    )

    paths = [
        item["path"]
        for item in ranked
    ]

    assert paths[0] == "backend/app/api/auth.py"


def test_analysis_ranking_penalizes_lockfiles() -> None:
    search_results = []

    for query in [
        "api",
        "auth",
        "config",
        "git",
        "main",
    ]:
        search_results.append(
            {
                "path": "frontend/package-lock.json",
                "query": query,
                "symbol_name": None,
            }
        )

    for query in [
        "results",
        "revenue",
    ]:
        search_results.append(
            {
                "path": "backend/app/api/results.py",
                "query": query,
                "symbol_name": None,
            }
        )

    ranked = analysis_runner._rank_candidate_files(
        search_results,
        max_candidates=2,
    )

    paths = [
        item["path"]
        for item in ranked
    ]

    assert paths[0] == "backend/app/api/results.py"


def test_analysis_ranking_keeps_service_layer_competitive() -> None:
    search_results = []

    for query in [
        "api",
        "database",
        "config",
        "main",
    ]:
        search_results.append(
            {
                "path": "docs/APP_MIGRATION_MAP.md",
                "query": query,
                "symbol_name": None,
            }
        )

    for query in [
        "revenue",
        "service",
    ]:
        search_results.append(
            {
                "path": "backend/app/services/revenue_service.py",
                "query": query,
                "symbol_name": None,
            }
        )

    ranked = analysis_runner._rank_candidate_files(
        search_results,
        max_candidates=2,
    )

    paths = [
        item["path"]
        for item in ranked
    ]

    assert paths[0] == (
        "backend/app/services/revenue_service.py"
    )



def _capture_search_budgets(
    monkeypatch,
    objective: str,
) -> list[int]:
    seen_limits: list[int] = []

    mission: dict[str, Any] = {
        "id": 999,
        "project_id": 1,
        "objective": objective,
        "tasks": [
            {
                "id": 1001,
                "task_type": "ANALYSIS",
                "status": "RUNNING",
            }
        ],
    }

    monkeypatch.setattr(
        analysis_runner,
        "get_mission",
        lambda mission_id: mission,
    )

    monkeypatch.setattr(
        analysis_runner,
        "_get_project",
        lambda project_id: {
            "id": project_id,
            "name": "Test Project",
            "path": "C:/fake-project",
        },
    )

    def fake_search_project(
        *,
        project_id: int,
        query: str,
        max_results: int,
    ) -> dict[str, Any]:
        seen_limits.append(max_results)
        return {"results": []}

    monkeypatch.setattr(
        analysis_runner,
        "search_project",
        fake_search_project,
    )

    monkeypatch.setattr(
        analysis_runner,
        "_rank_candidate_files",
        lambda search_results, max_candidates=12: [
            {
                "path": "backend/app/main.py",
                "score": 1,
                "reasons": ["test"],
            }
        ],
    )

    monkeypatch.setattr(
        analysis_runner,
        "_analyze_candidates",
        lambda **kwargs: [
            {
                "path": "backend/app/main.py",
                "score": 1,
                "matched_query_count": 1,
                "reasons": ["test"],
                "role": "entrypoint",
                "language": "python",
                "metrics": {},
                "routes": [],
                "api_calls": [],
                "sdk_calls": [],
                "warnings": [],
                "dependency": {
                    "direct_dependencies": [],
                    "direct_dependents": [],
                    "affected_count": 0,
                    "risk": None,
                    "error": None,
                },
            }
        ],
    )

    monkeypatch.setattr(
        analysis_runner,
        "update_mission_task",
        lambda **kwargs: mission,
    )

    monkeypatch.setattr(
        analysis_runner,
        "add_mission_log",
        lambda **kwargs: None,
    )

    analysis_runner._run_mission_analysis_impl(999)

    return seen_limits


def test_comprehensive_analysis_uses_deep_search_budget(
    monkeypatch,
) -> None:
    limits = _capture_search_budgets(
        monkeypatch,
        COMPREHENSIVE_OBJECTIVE,
    )

    assert limits
    assert all(
        limit > 25
        for limit in limits
    )


def test_focused_analysis_keeps_bounded_search_budget(
    monkeypatch,
) -> None:
    objective = (
        "\u30ed\u30b0\u30a4\u30f3\u8a8d\u8a3c"
        "\u3060\u3051\u3092\u8abf\u67fb\u3059\u308b\u3002"
    )

    limits = _capture_search_budgets(
        monkeypatch,
        objective,
    )

    assert limits
    assert set(limits) == {25}



def test_analyze_candidates_flags_stub_route_handlers(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        analysis_runner,
        "analyze_project_file",
        lambda **kwargs: {
            "role": "auth API routes",
            "language": "python",
            "metrics": {
                "line_count": 35,
                "warning_count": 0,
            },
            "routes": [
                {
                    "framework": "fastapi",
                    "method": "GET",
                    "path": "/me",
                    "handler": "current_user",
                    "line": 9,
                },
                {
                    "framework": "fastapi",
                    "method": "POST",
                    "path": "/login",
                    "handler": "login_stub",
                    "line": 23,
                },
                {
                    "framework": "fastapi",
                    "method": "POST",
                    "path": "/register",
                    "handler": "register_stub",
                    "line": 28,
                },
                {
                    "framework": "fastapi",
                    "method": "POST",
                    "path": "/logout",
                    "handler": "logout_stub",
                    "line": 33,
                },
            ],
            "api_calls": [],
            "sdk_calls": [],
            "warnings": [],
        },
    )

    monkeypatch.setattr(
        analysis_runner,
        "analyze_dependency_tree",
        lambda **kwargs: {
            "direct_dependencies": [],
            "direct_dependents": [],
            "summary": {
                "affected_count": 0,
            },
            "risk": None,
        },
    )

    analyzed = analysis_runner._analyze_candidates(
        project_path="C:/fake-project",
        candidates=[
            {
                "path": "backend/app/api/auth.py",
                "score": 37,
                "matched_query_count": 3,
                "reasons": ["test"],
            }
        ],
    )

    assert len(analyzed) == 1

    warnings = analyzed[0]["warnings"]

    stub_warnings = [
        warning
        for warning in warnings
        if warning.get("code")
        == "STUB_ROUTE_HANDLER"
    ]

    assert len(stub_warnings) == 1

    warning = stub_warnings[0]

    assert warning["level"] in {
        "medium",
        "high",
    }

    assert "login_stub" in warning["message"]
    assert "register_stub" in warning["message"]
    assert "logout_stub" in warning["message"]


def test_analyze_candidates_does_not_flag_normal_routes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        analysis_runner,
        "analyze_project_file",
        lambda **kwargs: {
            "role": "results API routes",
            "language": "python",
            "metrics": {
                "line_count": 78,
                "warning_count": 0,
            },
            "routes": [
                {
                    "framework": "fastapi",
                    "method": "GET",
                    "path": "/summary",
                    "handler": "results_summary",
                    "line": 16,
                },
                {
                    "framework": "fastapi",
                    "method": "GET",
                    "path": "/insights",
                    "handler": "results_insights",
                    "line": 48,
                },
            ],
            "api_calls": [],
            "sdk_calls": [],
            "warnings": [],
        },
    )

    monkeypatch.setattr(
        analysis_runner,
        "analyze_dependency_tree",
        lambda **kwargs: {
            "direct_dependencies": [],
            "direct_dependents": [],
            "summary": {
                "affected_count": 0,
            },
            "risk": None,
        },
    )

    analyzed = analysis_runner._analyze_candidates(
        project_path="C:/fake-project",
        candidates=[
            {
                "path": "backend/app/api/results.py",
                "score": 34,
                "matched_query_count": 3,
                "reasons": ["test"],
            }
        ],
    )

    assert not any(
        warning.get("code")
        == "STUB_ROUTE_HANDLER"
        for warning in analyzed[0]["warnings"]
    )



def test_focused_analysis_prioritizes_explicit_auth_targets() -> None:
    objective = (
        "Resolve the production-readiness issue in authentication. "
        "Inspect the actual frontend and backend flow before changing code. "
        "The backend file backend/app/api/auth.py currently exposes "
        "login_stub, register_stub, and logout_stub, while the frontend "
        "uses Supabase authentication."
    )

    tokens = analysis_runner._tokenize_objective(
        objective
    )

    focused = tokens[
        :analysis_runner.FOCUSED_SEARCH_TERM_LIMIT
    ]

    assert "auth" in focused
    assert "login_stub" in focused
    assert "register_stub" in focused
    assert "logout_stub" in focused
    assert "supabase" in focused

    assert any(
        token.startswith("backend/app/api/auth")
        for token in focused
    )


def test_focused_analysis_does_not_spend_budget_on_common_words() -> None:
    objective = (
        "Resolve the production-readiness issue in authentication. "
        "Inspect the actual frontend and backend flow before changing code."
    )

    tokens = analysis_runner._tokenize_objective(
        objective
    )

    focused = tokens[
        :analysis_runner.FOCUSED_SEARCH_TERM_LIMIT
    ]

    for word in (
        "the",
        "and",
        "actual",
        "before",
    ):
        assert word not in focused
