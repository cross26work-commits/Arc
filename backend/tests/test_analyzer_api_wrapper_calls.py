from pathlib import Path

import pytest

from app.analyzer.service import analyze_project_file


def test_analyze_project_file_detects_api_get_wrapper_call(
    tmp_path: Path,
) -> None:
    relative_path = (
        "frontend/src/services/auth/meService.ts"
    )

    target = tmp_path / relative_path

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        '''
export type AuthMeResponse = {
  user_id: string;
};

export function getAuthMe() {
  return apiGet<AuthMeResponse>("/auth/me");
}
'''.strip(),
        encoding="utf-8",
    )

    result = analyze_project_file(
        project_path=str(tmp_path),
        relative_path=relative_path,
    )

    assert {
        "client": "apiGet",
        "method": "GET",
        "url": "/auth/me",
        "line": 6,
    } in result["api_calls"]


@pytest.mark.parametrize(
    ("client", "method", "url"),
    [
        ("apiGet", "GET", "/items"),
        ("apiPost", "POST", "/items"),
        ("apiPut", "PUT", "/items/1"),
        ("apiPatch", "PATCH", "/items/1"),
        ("apiDelete", "DELETE", "/items/1"),
    ],
)
def test_analyze_project_file_detects_api_wrapper_methods(
    tmp_path: Path,
    client: str,
    method: str,
    url: str,
) -> None:
    relative_path = "frontend/src/services/example.ts"

    target = tmp_path / relative_path

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_text(
        f'''
export function callApi() {{
  return {client}<unknown>("{url}");
}}
'''.strip(),
        encoding="utf-8",
    )

    result = analyze_project_file(
        project_path=str(tmp_path),
        relative_path=relative_path,
    )

    assert any(
        call.get("client") == client
        and call.get("method") == method
        and call.get("url") == url
        for call in result["api_calls"]
    )
