"""Run evidence-based questions through the deployed frontend API.

The runner uses the same /api/auth/login and /api/chat endpoints as the browser,
then deletes every generated session so production chat history is not polluted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "tests" / "frontend_live_eval_cases.json"


def normalize(value: Any) -> str:
    return "".join(unicodedata.normalize("NFKC", str(value or "")).lower().split())


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    token: str = "",
    body: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed: {exc.reason}") from exc


def validate_case(case: dict, response: dict) -> list[str]:
    expected = case.get("expected") or {}
    answer = normalize(response.get("answer"))
    sources = response.get("sources") or []
    titles = [normalize(source.get("document_title") or source.get("filename")) for source in sources]
    errors: list[str] = []

    if not answer:
        errors.append("answer is empty")
    for group in expected.get("answer_groups") or []:
        alternatives = [normalize(term) for term in group]
        if not any(term and term in answer for term in alternatives):
            errors.append(f"answer missing one of: {group}")

    for required in expected.get("citation_titles") or []:
        term = normalize(required)
        if not any(term in title for title in titles):
            errors.append(f"required citation missing: {required}")
    for forbidden in expected.get("forbidden_titles") or []:
        term = normalize(forbidden)
        if any(term in title for title in titles):
            errors.append(f"forbidden citation present: {forbidden}")

    max_sources = expected.get("max_sources")
    if max_sources is not None and len(sources) > int(max_sources):
        errors.append(f"too many citations: expected at most {int(max_sources)}, got {len(sources)}")

    backend_contains = normalize(expected.get("backend_contains"))
    backend = normalize(response.get("retrieval_backend"))
    route_name = normalize((response.get("retrieval_route") or {}).get("name"))
    if backend_contains and backend_contains not in backend and backend_contains not in route_name:
        errors.append(
            f"retrieval backend mismatch: expected {expected['backend_contains']}, "
            f"got backend={response.get('retrieval_backend')} route={route_name or '-'}"
        )
    return errors


def run_case(base_url: str, token: str, case: dict, timeout: float) -> dict:
    started = time.perf_counter()
    response: dict = {}
    session_id = ""
    errors: list[str] = []
    cleanup_error = ""
    try:
        response = request_json(
            base_url,
            "/api/chat",
            method="POST",
            token=token,
            body={
                "question": case["question"],
                "session_id": None,
                "top_k": 8,
                "knowledge_scope": "all",
            },
            timeout=timeout,
        )
        session_id = str(response.get("session_id") or "")
        errors.extend(validate_case(case, response))
    except Exception as exc:
        errors.append(str(exc))
    finally:
        if session_id:
            try:
                request_json(
                    base_url,
                    f"/api/chat/sessions/{session_id}",
                    method="DELETE",
                    token=token,
                    timeout=30.0,
                )
            except Exception as exc:
                cleanup_error = str(exc)
                errors.append(f"session cleanup failed: {cleanup_error}")

    sources = response.get("sources") or []
    titles = list(
        dict.fromkeys(
            str(source.get("document_title") or source.get("filename") or "")
            for source in sources
            if source.get("document_title") or source.get("filename")
        )
    )
    return {
        "id": case["id"],
        "category": case.get("category") or "",
        "question": case["question"],
        "reference_answer": case.get("reference_answer") or "",
        "ok": not errors,
        "errors": errors,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "retrieval_backend": response.get("retrieval_backend") or "",
        "retrieval_route": (response.get("retrieval_route") or {}).get("name") or "",
        "source_count": len(sources),
        "source_titles": titles,
        "answer_preview": str(response.get("answer") or "")[:800],
        "session_deleted": bool(session_id and not cleanup_error),
    }


def print_results(results: list[dict]) -> None:
    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        print(
            f"[{status}] {result['id']} :: {result['elapsed_seconds']:.2f}s "
            f"backend={result['retrieval_backend'] or '-'} route={result['retrieval_route'] or '-'} "
            f"sources={result['source_count']} titles={result['source_titles']}"
        )
        if not result["ok"]:
            for error in result["errors"]:
                print(f"  - {error}")
            print(f"  answer: {result['answer_preview'][:500]}")

    passed = sum(1 for result in results if result["ok"])
    total = len(results)
    elapsed = sum(result["elapsed_seconds"] for result in results)
    print(f"Frontend live eval: {passed}/{total} passed in {elapsed:.1f}s.")

    categories = Counter(result["category"] for result in results)
    category_passes = Counter(result["category"] for result in results if result["ok"])
    for category in categories:
        print(f"  {category}: {category_passes[category]}/{categories[category]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live frontend answer and citation evaluation.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--base-url", default="")
    parser.add_argument("--ids", default="", help="Comma-separated case IDs to run")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    selected_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
    if selected_ids:
        cases = [case for case in cases if case.get("id") in selected_ids]
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("No evaluation cases found.")

    base_url = args.base_url or os.getenv("FRONTEND_BASE_URL") or payload.get("base_url") or "http://127.0.0.1:8081"
    username = os.getenv("DEFAULT_ADMIN_USERNAME") or ""
    password = os.getenv("DEFAULT_ADMIN_PASSWORD") or ""
    if not username or not password:
        raise SystemExit("DEFAULT_ADMIN_USERNAME and DEFAULT_ADMIN_PASSWORD are required.")

    login = request_json(
        base_url,
        "/api/auth/login",
        method="POST",
        body={"username": username, "password": password},
        timeout=30.0,
    )
    token = str(login.get("token") or "")
    if not token:
        raise SystemExit("Login response did not contain a token.")

    results = [run_case(base_url, token, case, args.timeout) for case in cases]
    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    else:
        print_results(results)
    return 1 if any(not result["ok"] for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
