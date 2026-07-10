"""Data-driven retrieval evaluation runner.

Run from internal-ai-assistant/backend:
    python tests/qa_retrieval_eval_runner.py

Optional fixture mode:
    python tests/qa_retrieval_eval_runner.py --cases tests/retrieval_eval_cases.json --keep-db

Real knowledge-base mode:
    python tests/qa_retrieval_eval_runner.py --real-db --cases tests/retrieval_eval_real_cases.json
    python tests/qa_retrieval_eval_runner.py --real-db --pipeline --cases tests/retrieval_eval_real_cases.json --explain

The runner uses app.retrieval.adaptive_retrieve_contexts by default. With
--pipeline it exercises the production app.rag.pipeline.retrieve_contexts entry.
Fixture mode builds an isolated SQLite database. Real mode respects an existing
DATABASE_URL and otherwise falls back to backend/data/app.db.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "qa_retrieval_eval.sqlite3"
REAL_DB_PATH = DATA_DIR / "app.db"
DEFAULT_CASES_PATH = ROOT / "tests" / "retrieval_eval_cases.json"
DEFAULT_REAL_CASES_PATH = ROOT / "tests" / "retrieval_eval_real_cases.json"

# Must be set before importing app.* modules.
DATABASE_URL_WAS_CONFIGURED = bool(os.environ.get("DATABASE_URL"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")
os.environ.setdefault("VECTOR_BACKEND", "local")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("DEFAULT_ADMIN_USERNAME", "eval_admin")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "eval_admin_password")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_retrieval_eval_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def cleanup_storage() -> None:
    try:
        database = importlib.import_module("app.database")
        database.engine.dispose()
    except Exception:
        pass
    for path in [DB_PATH, Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm")]:
        if path.exists():
            try:
                path.unlink()
            except PermissionError:
                # Windows may keep SQLite handles briefly after SQLAlchemy closes sessions.
                pass
    if UPLOAD_DIR.exists():
        for path in UPLOAD_DIR.glob("qa_retrieval_eval_*"):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)


def load_cases(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: Any) -> str:
    # PDF/PPT extraction often yields CJK compatibility ideographs and arbitrary
    # line breaks inside words, e.g. “⼊职 联系”. Normalize before matching so
    # evaluation checks evidence semantics instead of OCR/layout artifacts.
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", text)


def context_title_text(context: dict) -> str:
    return " ".join(str(context.get(key) or "") for key in ("document_title", "filename", "document_id"))


def context_full_text(context: dict) -> str:
    return " ".join(
        str(context.get(key) or "")
        for key in (
            "document_title",
            "filename",
            "document_id",
            "content",
            "location",
            "section_title",
            "anchor",
            "sheet_name",
            "row_number",
        )
    )


def doc_ids(contexts: list[dict]) -> list[str]:
    return [str(context.get("document_id") or "") for context in contexts]


def joined_context_text(contexts: list[dict]) -> str:
    return "\n".join(context_full_text(context) for context in contexts)


def any_context_matches(contexts: list[dict], needles: list[str], *, scope: str = "full") -> bool:
    if not needles:
        return True
    haystacks = [context_title_text(context) if scope == "title" else context_full_text(context) for context in contexts]
    normalized_haystacks = [normalize_text(item) for item in haystacks]
    return any(all(normalize_text(needle) in haystack for needle in needles) for haystack in normalized_haystacks)


def matching_context_indices(contexts: list[dict], needles: list[str], *, scope: str = "full") -> list[int]:
    if not needles:
        return []
    matched: list[int] = []
    for index, context in enumerate(contexts):
        haystack = context_title_text(context) if scope == "title" else context_full_text(context)
        normalized = normalize_text(haystack)
        if all(normalize_text(needle) in normalized for needle in needles):
            matched.append(index)
    return matched


def expected_groups(value: Any) -> list[list[str]]:
    """Normalize expected match values.

    Supported forms:
      ["电子劳动合同", "微助手"]        -> two independent one-term groups
      [["电子", "合同"], ["微助手"]] -> each group is AND terms, groups are OR/listed
    """
    if not value:
        return []
    groups: list[list[str]] = []
    for item in value:
        if isinstance(item, list):
            terms = [str(term) for term in item if str(term).strip()]
        else:
            terms = [str(item)] if str(item).strip() else []
        if terms:
            groups.append(terms)
    return groups


def add_fixture_doc(db, models, app_main, admin, group_by_id: dict[str, Any], doc_spec: dict[str, Any]) -> None:
    doc_id = str(doc_spec["id"])
    title = str(doc_spec.get("title") or doc_id)
    filename = str(doc_spec.get("filename") or f"{doc_id}.txt")
    source_type = str(doc_spec.get("source_type") or Path(filename).suffix.lstrip(".") or "txt")
    chunks = [str(chunk) for chunk in doc_spec.get("chunks") or []]
    content = "\n\n".join(chunks) or title
    file_path = UPLOAD_DIR / f"qa_retrieval_eval_{filename}"
    file_path.write_text(content, encoding="utf-8")

    doc = models.Document(
        id=doc_id,
        title=title,
        filename=filename,
        storage_path=str(file_path),
        source_type=source_type,
        knowledge_scope=str(doc_spec.get("knowledge_scope") or "production"),
        document_kind=str(doc_spec.get("document_kind") or "general"),
        created_by=admin.id,
    )
    for group_id in doc_spec.get("groups") or []:
        group = group_by_id.get(str(group_id))
        if group:
            doc.groups.append(group)
    db.add(doc)
    db.flush()

    for index, chunk_text in enumerate(chunks or [content]):
        db.add(models.DocumentChunk(
            id=f"{doc_id}-chunk-{index}",
            document_id=doc.id,
            page_number=1,
            chunk_index=index,
            content=chunk_text,
            embedding_json=json.dumps(app_main.embed_texts([chunk_text])[0]),
        ))

    for row_spec in doc_spec.get("table_rows") or []:
        row_json = row_spec.get("row_json") or {}
        row_text = " | ".join(f"{key}={value}" for key, value in row_json.items())
        db.add(models.DocumentTableRow(
            id=str(row_spec.get("id") or f"{doc_id}-row-{row_spec.get('row_number', 0)}"),
            document_id=doc.id,
            sheet_name=str(row_spec.get("sheet_name") or ""),
            row_number=row_spec.get("row_number"),
            row_key=str(row_spec.get("row_key") or ""),
            row_json=json.dumps(row_json, ensure_ascii=False),
            row_text=row_text,
            is_header=bool(row_spec.get("is_header")),
            source_chunk_index=row_spec.get("source_chunk_index"),
        ))


def build_fixture(payload: dict[str, Any]):
    app_main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    security = importlib.import_module("app.security")

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    app_main.ensure_runtime_schema()

    fixture = payload.get("fixture") or {}
    db = database.SessionLocal()
    try:
        admin_spec = fixture.get("admin") or {"id": "eval-admin", "username": "eval_admin", "password": "eval_admin_password"}
        admin = models.User(
            id=str(admin_spec.get("id") or "eval-admin"),
            username=str(admin_spec.get("username") or "eval_admin"),
            password_hash=security.hash_password(str(admin_spec.get("password") or "eval_admin_password")),
            is_admin=True,
            is_active=True,
        )
        db.add(admin)

        group_by_id: dict[str, Any] = {}
        for group_spec in fixture.get("groups") or []:
            group = models.Group(id=str(group_spec["id"]), name=str(group_spec.get("name") or group_spec["id"]))
            group_by_id[group.id] = group
            db.add(group)
        db.flush()

        for user_spec in fixture.get("users") or []:
            user = models.User(
                id=str(user_spec["id"]),
                username=str(user_spec.get("username") or user_spec["id"]),
                password_hash=security.hash_password(str(user_spec.get("password") or "eval_user_password")),
                is_admin=bool(user_spec.get("is_admin")),
                is_active=True,
            )
            for group_id in user_spec.get("groups") or []:
                group = group_by_id.get(str(group_id))
                if group:
                    user.groups.append(group)
            db.add(user)
        db.flush()

        for doc_spec in fixture.get("documents") or []:
            add_fixture_doc(db, models, app_main, admin, group_by_id, doc_spec)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return database, models


def load_real_database():
    app_main = importlib.import_module("app.main")
    app_main.ensure_runtime_schema()
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    return database, models


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_case(case: dict[str, Any], contexts: list[dict], backend: str, meta: dict[str, Any], *, pipeline: bool = False) -> list[str]:
    errors: list[str] = []
    expected = case.get("expected") or {}
    ranked_ids = doc_ids(contexts)
    text = joined_context_text(contexts)
    normalized_text = normalize_text(text)

    if expected.get("backend"):
        require(backend == expected["backend"], f"backend expected {expected['backend']}, got {backend}", errors)

    top_doc = expected.get("top_doc")
    if top_doc:
        require(bool(ranked_ids) and ranked_ids[0] == top_doc, f"top_doc expected {top_doc}, got {ranked_ids[:5]}", errors)

    for doc_id in expected.get("must_include_docs") or []:
        require(str(doc_id) in ranked_ids, f"must include doc {doc_id}, got {ranked_ids}", errors)

    for doc_id in expected.get("must_not_include_docs") or []:
        require(str(doc_id) not in ranked_ids, f"must not include doc {doc_id}, got {ranked_ids}", errors)

    top_n = int(expected.get("top_n") or 0)
    top_contexts = contexts[:top_n] if top_n > 0 else contexts
    if top_n > 0:
        top_ids = ranked_ids[:top_n]
        for doc_id in expected.get("top_n_must_include_docs") or []:
            require(str(doc_id) in top_ids, f"top {top_n} must include doc {doc_id}, got {top_ids}", errors)

    for terms in expected_groups(expected.get("must_match_titles")):
        require(any_context_matches(contexts, terms, scope="title"), f"must match title terms {terms}, got {[context_title_text(c) for c in contexts[:5]]}", errors)

    for terms in expected_groups(expected.get("must_not_match_titles")):
        require(not any_context_matches(contexts, terms, scope="title"), f"must not match title terms {terms}, got {[context_title_text(c) for c in contexts[:5]]}", errors)

    for terms in expected_groups(expected.get("top_n_must_match_titles")):
        require(any_context_matches(top_contexts, terms, scope="title"), f"top {top_n or len(contexts)} must match title terms {terms}, got {[context_title_text(c) for c in top_contexts[:5]]}", errors)

    for terms in expected_groups(expected.get("top_n_must_not_match_titles")):
        require(not any_context_matches(top_contexts, terms, scope="title"), f"top {top_n or len(contexts)} must not match title terms {terms}, got {[context_title_text(c) for c in top_contexts[:5]]}", errors)

    for terms in expected_groups(expected.get("must_match_contexts")):
        require(any_context_matches(contexts, terms, scope="full"), f"must match context terms {terms}", errors)

    for terms in expected_groups(expected.get("must_not_match_contexts")):
        require(not any_context_matches(contexts, terms, scope="full"), f"must not match context terms {terms}", errors)

    for term in expected.get("must_include_terms") or []:
        require(normalize_text(term) in normalized_text, f"must include term {term!r} in retrieved context text", errors)

    for term in expected.get("must_not_include_terms") or []:
        require(normalize_text(term) not in normalized_text, f"must not include term {term!r} in retrieved context text", errors)

    if "max_contexts" in expected:
        max_contexts = int(expected.get("max_contexts") or 0)
        require(len(contexts) <= max_contexts, f"expected at most {max_contexts} contexts, got {len(contexts)}", errors)

    if "max_top_score" in expected and contexts:
        max_top_score = float(expected.get("max_top_score") or 0)
        top_score = max(float(context.get("rerank_score") or context.get("score") or 0) for context in contexts[:1])
        require(top_score <= max_top_score, f"expected top score <= {max_top_score}, got {top_score}", errors)

    if not pipeline:
        profile_expected = expected.get("query_profile") or {}
        profile = meta.get("query_profile") or {}
        for key, value in profile_expected.items():
            require(profile.get(key) == value, f"query_profile.{key} expected {value!r}, got {profile.get(key)!r}; profile={profile}", errors)

        positive_required = expected.get("must_have_positive_signals") or []
        if positive_required:
            signals: list[str] = []
            for context in contexts:
                ranking = context.get("intent_ranking") or {}
                signals.extend(str(item) for item in ranking.get("positive_signals") or [])
            for signal in positive_required:
                require(str(signal) in signals, f"positive signal {signal!r} missing; got {signals}", errors)

    return errors


def resolve_user(db, models, case: dict[str, Any], defaults: dict[str, Any], *, real_db: bool):
    username = case.get("username") or defaults.get("username")
    user_id = case.get("user_id") or defaults.get("user_id")
    if username:
        user = db.query(models.User).filter(models.User.username == str(username), models.User.is_active == True).first()  # noqa: E712
        if user:
            return user
        raise AssertionError(f"case {case.get('id')}: username {username!r} not found")
    if user_id:
        user = db.get(models.User, str(user_id))
        if user:
            return user
        raise AssertionError(f"case {case.get('id')}: user {user_id!r} not found")
    if real_db:
        user = db.query(models.User).filter(models.User.is_active == True, models.User.is_admin == False).order_by(models.User.created_at.asc()).first()  # noqa: E712
        if user:
            return user
        user = db.query(models.User).filter(models.User.is_active == True).order_by(models.User.created_at.asc()).first()  # noqa: E712
        if user:
            return user
        raise AssertionError("real-db mode: no active user found; create a user or set defaults.username/defaults.user_id")
    user = db.get(models.User, "eval-user")
    if not user:
        raise AssertionError(f"case {case.get('id')}: user eval-user not found")
    return user


def explain_context(context: dict, index: int) -> dict[str, Any]:
    ranking = context.get("intent_ranking") or {}
    return {
        "rank": index + 1,
        "document_id": context.get("document_id"),
        "title": context.get("document_title") or context.get("filename"),
        "filename": context.get("filename"),
        "channel": context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"),
        "score": context.get("score"),
        "rerank_score": context.get("rerank_score"),
        "llm_rerank_score": context.get("llm_rerank_score"),
        "positive_signals": ranking.get("positive_signals") or [],
        "negative_signals": ranking.get("negative_signals") or [],
        "location": context.get("location") or context.get("section_title") or context.get("sheet_name") or "",
        "snippet": " ".join(str(context.get("content") or "").split())[:220],
    }


def run_eval(payload: dict[str, Any], *, real_db: bool = False, pipeline: bool = False) -> tuple[int, list[dict[str, Any]]]:
    if real_db:
        database, models = load_real_database()
    else:
        database, models = build_fixture(payload)
    retrieval = importlib.import_module("app.rag.pipeline" if pipeline else "app.retrieval")
    retrieve_contexts = getattr(retrieval, "retrieve_contexts" if pipeline else "adaptive_retrieve_contexts")
    defaults = payload.get("defaults") or {}
    results: list[dict[str, Any]] = []
    failures = 0

    db = database.SessionLocal()
    try:
        for case in payload.get("cases") or []:
            user = resolve_user(db, models, case, defaults, real_db=real_db)
            top_k = int(case.get("top_k") or defaults.get("top_k") or 8)
            contexts, backend, note, candidate_count, meta = retrieve_contexts(db, str(case["question"]), user, top_k=top_k, knowledge_scope=str(case.get("knowledge_scope") or defaults.get("knowledge_scope") or "all"))
            errors = validate_case(case, contexts, backend, meta, pipeline=pipeline)
            failed = bool(errors)
            failures += 1 if failed else 0
            result = {
                "id": case.get("id"),
                "ok": not failed,
                "question": case.get("question"),
                "user": getattr(user, "username", ""),
                "backend": backend,
                "note": note,
                "candidate_count": candidate_count,
                "ranked_doc_ids": doc_ids(contexts),
                "query_profile": meta.get("query_profile"),
                "meta": meta,
                "errors": errors,
                "top_contexts": [explain_context(context, index) for index, context in enumerate(contexts[:5])],
            }
            results.append(result)
    finally:
        db.close()
    return failures, results


def print_summary(results: list[dict[str, Any]], failures: int, *, explain: bool = False) -> None:
    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"[{status}] {result['id']} :: user={result.get('user') or '-'} backend={result['backend']} ranked={result['ranked_doc_ids'][:5]}")
        if result["errors"]:
            for error in result["errors"]:
                print(f"  - {error}")
        if explain:
            print(f"  question: {result['question']}")
            print(f"  note: {result['note']}")
            print(f"  query_profile: {result.get('query_profile')}")
            for context in result["top_contexts"]:
                print(f"  Top {context['rank']}: {context['title']} [{context['channel']}]")
                print(f"    score={context['score']} rerank={context['rerank_score']} llm={context['llm_rerank_score']} location={context['location']}")
                if context["positive_signals"]:
                    print(f"    + {', '.join(map(str, context['positive_signals']))}")
                if context["negative_signals"]:
                    print(f"    - {', '.join(map(str, context['negative_signals']))}")
                if context["snippet"]:
                    print(f"    snippet: {context['snippet']}")
    total = len(results)
    print(f"Retrieval eval: {total - failures}/{total} passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval evaluation cases.")
    parser.add_argument("--cases", default=None, help="Path to retrieval eval JSON. Defaults to fixture or real template by mode.")
    parser.add_argument("--real-db", action="store_true", help="Run against configured DATABASE_URL, falling back to backend/data/app.db")
    parser.add_argument("--pipeline", action="store_true", help="Exercise the production RAG pipeline instead of legacy retrieval directly")
    parser.add_argument("--json", action="store_true", help="Print full JSON results")
    parser.add_argument("--explain", action="store_true", help="Print top-context explanation details")
    parser.add_argument("--keep-db", action="store_true", help="Keep isolated SQLite DB and uploaded fixture files for debugging")
    args = parser.parse_args()

    cases_path = Path(args.cases) if args.cases else (DEFAULT_REAL_CASES_PATH if args.real_db else DEFAULT_CASES_PATH)
    if args.real_db:
        if not DATABASE_URL_WAS_CONFIGURED:
            os.environ["DATABASE_URL"] = f"sqlite:///{REAL_DB_PATH.as_posix()}"
    else:
        os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
        os.environ["VECTOR_BACKEND"] = "local"
        os.environ["EMBEDDING_PROVIDER"] = "local"
        reset_storage()

    payload = load_cases(cases_path)
    failures, results = run_eval(payload, real_db=args.real_db, pipeline=args.pipeline)

    if args.json:
        print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False, indent=2))
    else:
        print_summary(results, failures, explain=args.explain)

    if not args.real_db and not args.keep_db:
        cleanup_storage()

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
