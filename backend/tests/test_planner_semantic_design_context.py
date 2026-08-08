from app.missions.planner_runner import (
    _build_workstreams,
)


def test_workstream_preserves_read_only_semantic_context() -> None:
    selected_files = [
        {
            "path": "backend/app/api/auth.py",
            "category": "BACKEND",
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
    ]

    context_candidates = [
        {
            "path": (
                "frontend/src/services/auth/"
                "authService.ts"
            ),
            "category": "FRONTEND",
            "sdk_calls": [
                {
                    "sdk": "supabase",
                    "operation": (
                        "auth.signInWithPassword"
                    ),
                },
                {
                    "sdk": "supabase",
                    "operation": "auth.signUp",
                },
                {
                    "sdk": "supabase",
                    "operation": "auth.signOut",
                },
            ],
            "warnings": [],
        }
    ]

    workstreams = _build_workstreams(
        selected_files,
        context_candidates=context_candidates,
    )

    assert len(workstreams) == 1

    stream = workstreams[0]

    # Read-only context must inform the plan.
    assert "authService.ts" in stream["purpose"]
    assert "supabase" in stream["purpose"].lower()

    # But it must NOT become a mutation target.
    assert stream["files"] == [
        "backend/app/api/auth.py"
    ]


def test_workstream_preserves_read_only_api_call_context() -> None:
    selected_files = [
        {
            "path": "backend/app/api/auth.py",
            "category": "BACKEND",
            "warnings": [
                {
                    "level": "medium",
                    "code": "STUB_ROUTE_HANDLER",
                    "message": (
                        "Stub route handlers detected"
                    ),
                }
            ],
        }
    ]

    context_candidates = [
        {
            "path": (
                "frontend/src/services/auth/"
                "meService.ts"
            ),
            "category": "FRONTEND",
            "api_calls": [
                {
                    "client": "apiGet",
                    "method": "GET",
                    "url": "/auth/me",
                    "line": 9,
                }
            ],
            "sdk_calls": [],
            "warnings": [],
        }
    ]

    workstreams = _build_workstreams(
        selected_files,
        context_candidates=context_candidates,
    )

    purpose = workstreams[0]["purpose"]

    assert "meService.ts" in purpose
    assert "GET" in purpose
    assert "/auth/me" in purpose

    assert workstreams[0]["files"] == [
        "backend/app/api/auth.py"
    ]


def test_workstream_turns_semantic_evidence_into_design_guidance() -> None:
    selected_files = [
        {
            "path": "backend/app/api/auth.py",
            "category": "BACKEND",
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
    ]

    context_candidates = [
        {
            "path": (
                "frontend/src/services/auth/"
                "authService.ts"
            ),
            "category": "FRONTEND",
            "api_calls": [],
            "sdk_calls": [
                {
                    "sdk": "supabase",
                    "operation": (
                        "auth.signInWithPassword"
                    ),
                },
                {
                    "sdk": "supabase",
                    "operation": "auth.signUp",
                },
                {
                    "sdk": "supabase",
                    "operation": "auth.signOut",
                },
            ],
            "warnings": [],
        },
        {
            "path": (
                "frontend/src/services/auth/"
                "meService.ts"
            ),
            "category": "FRONTEND",
            "api_calls": [
                {
                    "client": "apiGet",
                    "method": "GET",
                    "url": "/auth/me",
                    "line": 9,
                }
            ],
            "sdk_calls": [],
            "warnings": [],
        },
    ]

    workstreams = _build_workstreams(
        selected_files,
        context_candidates=context_candidates,
    )

    purpose = workstreams[0]["purpose"].lower()

    assert "verify route callers" in purpose
    assert "avoid duplicate" in purpose
    assert "preserve referenced api endpoints" in purpose

    # Evidence must still be visible.
    assert "supabase" in purpose
    assert "/auth/me" in purpose

    # Read-only context must not become mutation scope.
    assert workstreams[0]["files"] == [
        "backend/app/api/auth.py"
    ]
