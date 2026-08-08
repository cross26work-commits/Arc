from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from app.projects.reader import ProjectReadError, read_project_file


class FileAnalysisError(Exception):
    """ファイル静的解析に失敗した場合の例外。"""


TODO_PATTERN = re.compile(
    r"\b(TODO|FIXME|HACK|XXX|BUG)\b[:：]?\s*(.*)",
    re.IGNORECASE,
)

JS_IMPORT_PATTERN = re.compile(
    r"""
    import\s+
    (?:
        [\s\S]*?
        \s+from\s+
    )?
    ["']([^"']+)["']
    """,
    re.VERBOSE,
)

JS_FUNCTION_PATTERNS = [
    re.compile(
        r"\b(?:export\s+)?(?:default\s+)?"
        r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
    ),
    re.compile(
        r"\b(?:export\s+)?(?:const|let|var)\s+"
        r"([A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:async\s*)?\([^)]*\)\s*=>"
    ),
    re.compile(
        r"\b(?:export\s+)?(?:const|let|var)\s+"
        r"([A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:async\s*)?[A-Za-z_$][\w$]*\s*=>"
    ),
]

JS_CLASS_PATTERN = re.compile(
    r"\b(?:export\s+)?(?:default\s+)?class\s+"
    r"([A-Za-z_$][\w$]*)"
)

REACT_COMPONENT_PATTERN = re.compile(
    r"\b(?:function|const)\s+([A-Z][A-Za-z0-9_$]*)\b"
)

FETCH_PATTERN = re.compile(
    r"""
    \bfetch\s*\(\s*
    [`"']([^`"']+)[`"']
    """,
    re.VERBOSE,
)

AXIOS_PATTERN = re.compile(
    r"""
    \baxios\.
    (get|post|put|patch|delete)
    \s*\(\s*
    [`"']([^`"']+)[`"']
    """,
    re.IGNORECASE | re.VERBOSE,
)

API_WRAPPER_PATTERN = re.compile(
    r"""
    \b(apiGet|apiPost|apiPut|apiPatch|apiDelete)
    \s*
    (?:<[^>]+>)?
    \s*\(\s*
    [`"']([^`"']+)[`"']
    """,
    re.IGNORECASE | re.VERBOSE,
)


EXPRESS_ROUTE_PATTERN = re.compile(
    r"""
    \b(?:app|router)\.
    (get|post|put|patch|delete)
    \s*\(\s*
    ["']([^"']+)["']
    """,
    re.IGNORECASE | re.VERBOSE,
)


REACT_HOOK_PATTERN = re.compile(
    r"\b("
    r"useState|useEffect|useMemo|useCallback|useRef|"
    r"useReducer|useContext|useLayoutEffect|useTransition|"
    r"useDeferredValue|useId|useImperativeHandle"
    r")\s*\("
)

SUPABASE_CALL_PATTERN = re.compile(
    r"""
    \bsupabase\.
    (
        auth\.[A-Za-z_$][\w$]* |
        from\s*\([^)]*\)(?:\.[A-Za-z_$][\w$]*)* |
        rpc |
        storage\.[A-Za-z_$][\w$]* |
        channel
    )
    \s*\(
    """,
    re.VERBOSE,
)

GENERIC_SDK_CALL_PATTERN = re.compile(
    r"""
    \b(
        createClient |
        initializeApp |
        getAuth |
        getFirestore |
        PrismaClient
    )
    \s*\(
    """,
    re.VERBOSE,
)

NEXT_ROUTER_PATTERN = re.compile(
    r"\b(useRouter|usePathname|useSearchParams|redirect|notFound)\s*\("
)


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []

    for value in values:
        normalized = value.strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        results.append(normalized)

    return results


def _extract_todos(content: str) -> list[dict[str, Any]]:
    todos: list[dict[str, Any]] = []

    for line_number, line in enumerate(content.splitlines(), start=1):
        match = TODO_PATTERN.search(line)

        if not match:
            continue

        todos.append(
            {
                "type": match.group(1).upper(),
                "line": line_number,
                "message": match.group(2).strip(),
                "preview": line.strip(),
            }
        )

    return todos


def _build_warnings(
    *,
    line_count: int,
    size_bytes: int,
    truncated: bool,
    todos: list[dict[str, Any]],
    parse_error: str | None,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    if truncated:
        warnings.append(
            {
                "level": "high",
                "code": "FILE_TRUNCATED",
                "message": "ファイルが読取上限を超えたため、解析対象が省略されています。",
            }
        )

    if line_count >= 1000:
        warnings.append(
            {
                "level": "medium",
                "code": "VERY_LARGE_FILE",
                "message": "1000行以上の巨大ファイルです。責務分割を検討してください。",
            }
        )
    elif line_count >= 500:
        warnings.append(
            {
                "level": "low",
                "code": "LARGE_FILE",
                "message": "500行以上のファイルです。保守性を確認してください。",
            }
        )

    if size_bytes >= 500_000:
        warnings.append(
            {
                "level": "medium",
                "code": "LARGE_FILE_SIZE",
                "message": "ファイルサイズが500KB以上あります。",
            }
        )

    if len(todos) >= 10:
        warnings.append(
            {
                "level": "medium",
                "code": "MANY_TODOS",
                "message": "TODO・FIXME等が10件以上あります。",
            }
        )
    elif todos:
        warnings.append(
            {
                "level": "info",
                "code": "HAS_TODOS",
                "message": f"TODO・FIXME等が{len(todos)}件あります。",
            }
        )

    if parse_error:
        warnings.append(
            {
                "level": "medium",
                "code": "PARSE_ERROR",
                "message": parse_error,
            }
        )

    return warnings


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parent = _decorator_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr

    if isinstance(node, ast.Call):
        return _decorator_name(node.func)

    return ""


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    return None


def _analyze_python(content: str) -> dict[str, Any]:
    imports: list[str] = []
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    calls: list[str] = []
    parse_error: str | None = None

    try:
        tree = ast.parse(content)
    except SyntaxError as error:
        return {
            "imports": [],
            "functions": [],
            "classes": [],
            "routes": [],
            "components": [],
            "calls": [],
            "parse_error": (
                f"Python構文解析に失敗しました。"
                f" line={error.lineno}, message={error.msg}"
            ),
        }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(alias.name for alias in node.names)
            imports.append(f"{module}: {names}" if module else names)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "decorators": [
                        _decorator_name(decorator)
                        for decorator in node.decorator_list
                        if _decorator_name(decorator)
                    ],
                }
            )

            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue

                decorator_path = _decorator_name(decorator.func)
                method = decorator_path.rsplit(".", 1)[-1].upper()

                if method not in {
                    "GET",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                    "HEAD",
                    "WEBSOCKET",
                }:
                    continue

                route_path = (
                    _literal_string(decorator.args[0])
                    if decorator.args
                    else None
                )

                routes.append(
                    {
                        "framework": "fastapi",
                        "method": method,
                        "path": route_path or "",
                        "handler": node.name,
                        "line": node.lineno,
                        "decorator": decorator_path,
                    }
                )

        elif isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "bases": [
                        ast.unparse(base)
                        for base in node.bases
                        if hasattr(ast, "unparse")
                    ],
                }
            )

        elif isinstance(node, ast.Call):
            try:
                call_name = ast.unparse(node.func)
            except Exception:
                call_name = ""

            if call_name:
                calls.append(call_name)

    return {
        "imports": _unique_strings(imports),
        "functions": functions,
        "classes": classes,
        "routes": routes,
        "components": [],
        "calls": _unique_strings(calls),
        "parse_error": parse_error,
    }


def _line_number_for_match(content: str, start_index: int) -> int:
    return content.count("\n", 0, start_index) + 1


def _extract_fetch_method(
    content: str,
    match_end: int,
) -> str:
    following = content[match_end:match_end + 700]

    method_match = re.search(
        r"""
        \bmethod\s*:\s*
        ["'](GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)["']
        """,
        following,
        re.IGNORECASE | re.VERBOSE,
    )

    if method_match:
        return method_match.group(1).upper()

    return "GET"


def _analyze_javascript(content: str) -> dict[str, Any]:
    imports = _unique_strings(
        [
            match.group(1)
            for match in JS_IMPORT_PATTERN.finditer(content)
        ]
    )

    function_names: list[tuple[str, int, bool]] = []

    for pattern in JS_FUNCTION_PATTERNS:
        for match in pattern.finditer(content):
            matched_text = match.group(0)
            is_async = bool(
                re.search(r"\basync\b", matched_text)
            )

            function_names.append(
                (
                    match.group(1),
                    _line_number_for_match(
                        content,
                        match.start(),
                    ),
                    is_async,
                )
            )

    seen_functions: set[str] = set()
    functions: list[dict[str, Any]] = []

    for name, line, is_async in function_names:
        if name in seen_functions:
            continue

        seen_functions.add(name)

        functions.append(
            {
                "name": name,
                "line": line,
                "end_line": None,
                "async": is_async,
                "decorators": [],
            }
        )

    classes = [
        {
            "name": match.group(1),
            "line": _line_number_for_match(
                content,
                match.start(),
            ),
            "end_line": None,
            "bases": [],
        }
        for match in JS_CLASS_PATTERN.finditer(content)
    ]

    component_names: list[str] = []

    for match in REACT_COMPONENT_PATTERN.finditer(content):
        name = match.group(1)

        if not name:
            continue

        if name.isupper():
            continue

        component_names.append(name)

    component_names = _unique_strings(component_names)

    components = [
        {
            "name": name,
            "type": "react-component",
        }
        for name in component_names
    ]

    routes: list[dict[str, Any]] = []

    for match in EXPRESS_ROUTE_PATTERN.finditer(content):
        routes.append(
            {
                "framework": "express",
                "method": match.group(1).upper(),
                "path": match.group(2),
                "handler": "",
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
                "decorator": "",
            }
        )

    api_calls: list[dict[str, Any]] = []

    for match in FETCH_PATTERN.finditer(content):
        api_calls.append(
            {
                "client": "fetch",
                "method": _extract_fetch_method(
                    content,
                    match.end(),
                ),
                "url": match.group(1),
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
            }
        )

    for match in AXIOS_PATTERN.finditer(content):
        api_calls.append(
            {
                "client": "axios",
                "method": match.group(1).upper(),
                "url": match.group(2),
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
            }
        )

    for match in API_WRAPPER_PATTERN.finditer(content):
        client = match.group(1)

        method = client[3:].upper()

        api_calls.append(
            {
                "client": client,
                "method": method,
                "url": match.group(2),
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
            }
        )

    sdk_calls: list[dict[str, Any]] = []

    for match in SUPABASE_CALL_PATTERN.finditer(content):
        operation = re.sub(
            r"\s+",
            "",
            match.group(1),
        )

        sdk_calls.append(
            {
                "sdk": "supabase",
                "operation": operation,
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
            }
        )

    for match in GENERIC_SDK_CALL_PATTERN.finditer(content):
        sdk_calls.append(
            {
                "sdk": "external-sdk",
                "operation": match.group(1),
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
            }
        )

    hooks: list[dict[str, Any]] = []

    for match in REACT_HOOK_PATTERN.finditer(content):
        hooks.append(
            {
                "name": match.group(1),
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
            }
        )

    next_features: list[dict[str, Any]] = []

    for match in NEXT_ROUTER_PATTERN.finditer(content):
        next_features.append(
            {
                "name": match.group(1),
                "line": _line_number_for_match(
                    content,
                    match.start(),
                ),
            }
        )

    return {
        "imports": imports,
        "functions": functions,
        "classes": classes,
        "routes": routes,
        "components": components,
        "calls": [],
        "api_calls": api_calls,
        "sdk_calls": sdk_calls,
        "hooks": hooks,
        "next_features": next_features,
        "parse_error": None,
    }


def _infer_role(
    relative_path: str,
    language: str,
    routes: list[dict[str, Any]],
    components: list[dict[str, Any]],
    classes: list[dict[str, Any]],
) -> str:
    normalized_path = relative_path.replace("\\", "/")
    path = normalized_path.lower()
    file_name = Path(normalized_path).name.lower()
    stem = Path(normalized_path).stem.replace("_", " ").replace("-", " ")

    if file_name == "page.tsx":
        route_path = normalized_path.split("/app/", 1)[-1]
        route_path = route_path.rsplit("/page.tsx", 1)[0]
        route_path = re.sub(r"/\([^/]+\)", "", route_path)
        route_path = route_path or "/"

        return f"Next.js画面ルート {route_path}"

    if file_name == "layout.tsx":
        return "Next.jsレイアウト定義"

    if file_name == "loading.tsx":
        return "Next.jsローディング画面"

    if file_name == "error.tsx":
        return "Next.jsエラー画面"

    if file_name == "not-found.tsx":
        return "Next.js Not Found画面"

    if file_name == "route.ts":
        return "Next.js Route Handler"

    if file_name == "middleware.ts":
        return "Next.js Middleware"

    if path.endswith("/lib/api.ts") or path.endswith("/api.ts"):
        return "HTTP API Client"

    if "/services/" in path or path.endswith("service.ts") or path.endswith("service.py"):
        return f"{stem}に関するビジネスロジック"

    if "supabase/client" in path:
        return "Supabase Client初期化"

    if routes:
        return f"{stem}に関するAPIルート定義"

    if "/providers/" in path:
        return f"{stem}に関するReact Provider"

    if "/hooks/" in path:
        return f"{stem}に関するReact Hook"

    if components:
        return f"{stem}に関するReact UIコンポーネント"

    if "/models" in path or path.endswith("models.py"):
        return f"{stem}に関するデータモデル定義"

    if "/repositories" in path or "repository" in path:
        return f"{stem}に関するデータアクセス処理"

    if "/api/" in path or "/router" in path:
        return f"{stem}に関するAPI処理"

    if "/components/" in path:
        return f"{stem}に関するUIコンポーネント"

    if "/lib/" in path:
        return f"{stem}に関する共通ライブラリ"

    if classes:
        return f"{stem}に関するクラス定義"

    return f"{stem}に関する{language}ソースファイル"


def _dependency_candidates(
    imports: list[str],
    relative_path: str,
) -> list[str]:
    dependencies: list[str] = []

    for item in imports:
        module = item.split(":", 1)[0].strip()

        if not module:
            continue

        if module.startswith("."):
            dependencies.append(module)
            continue

        if module.startswith(("app.", "src.", "@/")):
            dependencies.append(module)

    current_parent = Path(relative_path).parent.as_posix()

    return _unique_strings(
        [
            *dependencies,
            f"current_directory:{current_parent}",
        ]
    )


def analyze_project_file(
    *,
    project_path: str,
    relative_path: str,
) -> dict[str, Any]:
    try:
        file_data = read_project_file(
            project_path=project_path,
            relative_path=relative_path,
        )
    except ProjectReadError as error:
        raise FileAnalysisError(str(error)) from error

    content = file_data["content"]
    language = file_data["language"]

    if language == "python":
        details = _analyze_python(content)
    elif language in {
        "typescript",
        "typescript-react",
        "javascript",
        "javascript-react",
    }:
        details = _analyze_javascript(content)
    else:
        details = {
            "imports": [],
            "functions": [],
            "classes": [],
            "routes": [],
            "components": [],
            "calls": [],
            "api_calls": [],
            "sdk_calls": [],
            "hooks": [],
            "next_features": [],
            "parse_error": None,
        }

    todos = _extract_todos(content)

    warnings = _build_warnings(
        line_count=file_data["line_count"],
        size_bytes=file_data["size_bytes"],
        truncated=file_data["truncated"],
        todos=todos,
        parse_error=details.get("parse_error"),
    )

    imports = details.get("imports", [])
    routes = details.get("routes", [])
    components = details.get("components", [])
    classes = details.get("classes", [])

    role = _infer_role(
        relative_path=file_data["relative_path"],
        language=language,
        routes=routes,
        components=components,
        classes=classes,
    )

    metrics = {
        "line_count": file_data["line_count"],
        "size_bytes": file_data["size_bytes"],
        "function_count": len(details.get("functions", [])),
        "class_count": len(classes),
        "import_count": len(imports),
        "route_count": len(routes),
        "component_count": len(components),
        "hook_count": len(details.get("hooks", [])),
        "sdk_call_count": len(details.get("sdk_calls", [])),
        "api_call_count": len(details.get("api_calls", [])),
        "todo_count": len(todos),
        "warning_count": len(warnings),
    }

    return {
        "relative_path": file_data["relative_path"],
        "language": language,
        "summary": role,
        "role": role,
        "metrics": metrics,
        "imports": imports,
        "functions": details.get("functions", []),
        "classes": classes,
        "routes": routes,
        "components": components,
        "api_calls": details.get("api_calls", []),
        "sdk_calls": details.get("sdk_calls", []),
        "hooks": details.get("hooks", []),
        "next_features": details.get("next_features", []),
        "calls": details.get("calls", [])[:200],
        "dependencies": _dependency_candidates(
            imports=imports,
            relative_path=file_data["relative_path"],
        ),
        "todos": todos,
        "warnings": warnings,
        "truncated": file_data["truncated"],
        "analysis_engine": "arc-static-analyzer-v0.2",
    }
