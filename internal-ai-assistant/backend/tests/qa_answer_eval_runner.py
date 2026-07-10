"""Data-driven retrieval, answer, and citation evaluation runner.

Run from internal-ai-assistant/backend:
    python tests/qa_answer_eval_runner.py
    python tests/qa_answer_eval_runner.py --real-db --pipeline
    python tests/qa_answer_eval_runner.py --real-db --pipeline --llm

Deterministic local answers remain the default for stable regression checks.
--llm exercises the configured production answer model after retrieval.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANSWER_CASES_PATH = ROOT / "tests" / "retrieval_answer_eval_cases.json"
DEFAULT_REAL_CASES_PATH = ROOT / "tests" / "retrieval_answer_eval_real_cases.json"
REAL_DB_PATH = ROOT / "data" / "app.db"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from qa_retrieval_eval_runner import (  # noqa: E402
    DATABASE_URL_WAS_CONFIGURED,
    DB_PATH,
    cleanup_storage,
    doc_ids,
    expected_groups,
    explain_context,
    load_cases,
    load_real_database,
    normalize_text,
    reset_storage,
    resolve_user,
    validate_case,
    build_fixture,
)

NO_CONTEXT_ANSWER = "未在知识库中找到依据：当前没有检索到你有权限访问且与问题相关的资料。"
INSUFFICIENT_EVIDENCE_ANSWER = "未在知识库中找到充分依据：虽然检索到了一些候选片段，但没有达到可用于回答的证据门槛。"


def seed_graph_fixture(database, payload: dict[str, Any]) -> None:
    graph = ((payload.get("fixture") or {}).get("graph") or {}) if isinstance(payload, dict) else {}
    entities_spec = graph.get("entities") or []
    relations_spec = graph.get("relations") or []
    if not entities_spec and not relations_spec:
        return

    from app.graph_store import create_relation, get_or_create_entity

    db = database.SessionLocal()
    try:
        entities: dict[str, Any] = {}
        for item in entities_spec:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            entity = get_or_create_entity(
                db,
                name,
                str(item.get("type") or item.get("entity_type") or "entity"),
                float(item.get("confidence") or 0.0),
                str(item.get("description") or ""),
            )
            if entity is not None:
                entities[name] = entity
        db.flush()

        for item in relations_spec:
            source = entities.get(str(item.get("source") or ""))
            target = entities.get(str(item.get("target") or ""))
            if source is None or target is None:
                raise AssertionError(f"graph relation references unknown entity: {item}")
            relation = create_relation(
                db,
                source,
                target,
                str(item.get("type") or item.get("relation_type") or "related_to"),
                str(item.get("document_id") or ""),
                str(item.get("chunk_id") or "") or None,
                item.get("page_number"),
                str(item.get("evidence") or item.get("evidence_text") or ""),
                float(item.get("confidence") or 0.0),
                str(item.get("status") or "auto"),
                str(item.get("description") or ""),
            )
            if relation is None:
                raise AssertionError(f"failed to create graph relation: {item}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def prepare_database(payload: dict[str, Any], *, real_db: bool):
    if real_db:
        return load_real_database()
    database, models = build_fixture(payload)
    seed_graph_fixture(database, payload)
    return database, models


def compose_answer(question: str, contexts: list[dict], meta: dict[str, Any], db, *, use_llm: bool = False) -> tuple[str, str, list[dict]]:
    if not contexts:
        return NO_CONTEXT_ANSWER, "no_context", []
    from app.routers.chat_api import model_contexts_for_answer

    answer_contexts = model_contexts_for_answer(contexts, summary_mode=False)
    if not answer_contexts:
        return INSUFFICIENT_EVIDENCE_ANSWER, "insufficient_evidence", []
    route_name = ((meta.get("retrieval_route") or {}).get("name") or "").strip()
    if route_name == "table":
        from app.table_query import build_table_answer

        return build_table_answer(question, answer_contexts), "table_local", answer_contexts
    if use_llm:
        from app.ai_client import chat_answer
        from app.settings_service import get_model_config

        config = get_model_config(db)
        answer = chat_answer(
            question,
            answer_contexts,
            api_key=config.get("api_key") or None,
            base_url=config.get("base_url") or None,
            model=config.get("model") or None,
        )
        composer = "extractive_fallback" if answer.startswith("## 本地兜底整理") else "llm_grounded"
        return answer, composer, answer_contexts

    from app.ai_client import extractive_fallback_answer

    return extractive_fallback_answer(question, answer_contexts, "answer_eval_local"), "extractive_local", answer_contexts


def _nested_get(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in str(path or "").split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def validate_meta_expectations(case: dict[str, Any], meta: dict[str, Any], backend: str) -> list[str]:
    expected = case.get("meta_expected") or {}
    errors: list[str] = []
    if not expected:
        return errors
    comparable = dict(meta or {})
    comparable["backend"] = backend
    for path, value in expected.items():
        actual = _nested_get(comparable, path)
        if actual != value:
            errors.append(f"meta {path} expected {value!r}, got {actual!r}")
    return errors


def validate_answer(case: dict[str, Any], answer: str, composer: str) -> list[str]:
    expected = case.get("answer_expected") or {}
    errors: list[str] = []
    if not expected:
        return errors

    expected_composer = expected.get("composer")
    if expected_composer and composer != expected_composer:
        errors.append(f"answer composer expected {expected_composer}, got {composer}")

    normalized_answer = normalize_text(answer)
    for terms in expected_groups(expected.get("must_match_terms")):
        if not all(normalize_text(term) in normalized_answer for term in terms):
            errors.append(f"answer must match all terms {terms}")

    for term in expected.get("must_include_terms") or []:
        if normalize_text(term) not in normalized_answer:
            errors.append(f"answer must include term {term!r}")

    for term in expected.get("must_not_include_terms") or []:
        if normalize_text(term) in normalized_answer:
            errors.append(f"answer must not include term {term!r}")

    min_length = expected.get("min_length")
    if min_length is not None and len(answer.strip()) < int(min_length):
        errors.append(f"answer length expected >= {min_length}, got {len(answer.strip())}")

    max_length = expected.get("max_length")
    if max_length is not None and len(answer.strip()) > int(max_length):
        errors.append(f"answer length expected <= {max_length}, got {len(answer.strip())}")

    return errors


def validate_citations(case: dict[str, Any], citations: list[dict], answer_contexts: list[dict], composer: str) -> list[str]:
    expected = case.get("citation_expected") or {}
    errors: list[str] = []
    if composer in {"no_context", "insufficient_evidence"}:
        if citations:
            errors.append(f"ungrounded answer must not include citations, got {len(citations)}")
        return errors
    if not citations:
        return ["grounded answer must include at least one citation"]

    allowed_contexts = {
        (str(context.get("document_id") or ""), str(context.get("chunk_id") or ""))
        for context in answer_contexts
    }
    content_by_document: dict[str, list[str]] = {}
    for context in answer_contexts:
        document_id = str(context.get("document_id") or "")
        content_by_document.setdefault(document_id, []).append(normalize_text(context.get("content") or ""))

    for citation in citations:
        document_id = str(citation.get("document_id") or "")
        chunk_id = str(citation.get("chunk_id") or "")
        if (document_id, chunk_id) not in allowed_contexts:
            errors.append(f"citation {document_id}:{chunk_id} is not part of answer contexts")
        snippet = normalize_text(citation.get("snippet") or citation.get("content") or "")
        if not snippet:
            errors.append(f"citation {document_id}:{chunk_id} has no snippet")
        elif not any(snippet in content for content in content_by_document.get(document_id, [])):
            errors.append(f"citation snippet for {document_id}:{chunk_id} is not present in source evidence")
        if document_id and (not citation.get("view_url") or not citation.get("content_url")):
            errors.append(f"citation {document_id}:{chunk_id} is missing source URLs")

    citation_ids = [str(item.get("document_id") or "") for item in citations]
    citation_titles = [str(item.get("document_title") or item.get("title") or "") for item in citations]
    min_count = int(expected.get("min_count") or 0)
    if min_count and len(citations) < min_count:
        errors.append(f"citations expected >= {min_count}, got {len(citations)}")
    max_count = expected.get("max_count")
    if max_count is not None and len(citations) > int(max_count):
        errors.append(f"citations expected <= {max_count}, got {len(citations)}")
    for document_id in expected.get("must_include_docs") or []:
        if str(document_id) not in citation_ids:
            errors.append(f"citations must include doc {document_id}")
    for document_id in expected.get("must_not_include_docs") or []:
        if str(document_id) in citation_ids:
            errors.append(f"citations must not include doc {document_id}")
    for terms in expected_groups(expected.get("must_match_titles")):
        if not any(all(normalize_text(term) in normalize_text(title) for term in terms) for title in citation_titles):
            errors.append(f"citations must match title terms {terms}")
    for terms in expected_groups(expected.get("must_not_match_titles")):
        if any(all(normalize_text(term) in normalize_text(title) for term in terms) for title in citation_titles):
            errors.append(f"citations must not match title terms {terms}")
    return errors


def run_answer_eval(payload: dict[str, Any], *, real_db: bool = False, skip_retrieval_validation: bool = False, pipeline: bool = False, use_llm: bool = False) -> tuple[int, list[dict[str, Any]]]:
    database, models = prepare_database(payload, real_db=real_db)
    if pipeline:
        from app.rag.pipeline import retrieve_contexts
    else:
        from app.retrieval import adaptive_retrieve_contexts as retrieve_contexts
    from app.grounding import serialize_sources

    defaults = payload.get("defaults") or {}
    results: list[dict[str, Any]] = []
    failures = 0

    db = database.SessionLocal()
    try:
        for case in payload.get("cases") or []:
            user = resolve_user(db, models, case, defaults, real_db=real_db)
            top_k = int(case.get("top_k") or defaults.get("top_k") or 8)
            contexts, backend, note, candidate_count, meta = retrieve_contexts(db, str(case["question"]), user, top_k=top_k, knowledge_scope=str(case.get("knowledge_scope") or defaults.get("knowledge_scope") or "all"))
            retrieval_errors = [] if skip_retrieval_validation else validate_case(case, contexts, backend, meta, pipeline=pipeline)
            meta_errors = validate_meta_expectations(case, meta, backend)
            answer, composer, answer_contexts = compose_answer(str(case["question"]), contexts, meta, db, use_llm=use_llm)
            citations = serialize_sources(answer_contexts)
            answer_errors = validate_answer(case, answer, composer)
            citation_errors = validate_citations(case, citations, answer_contexts, composer)
            errors = [*retrieval_errors, *meta_errors, *answer_errors, *citation_errors]
            failed = bool(errors)
            failures += 1 if failed else 0
            results.append(
                {
                    "id": case.get("id"),
                    "ok": not failed,
                    "question": case.get("question"),
                    "category": case.get("category"),
                    "user": getattr(user, "username", ""),
                    "backend": backend,
                    "note": note,
                    "candidate_count": candidate_count,
                    "ranked_doc_ids": doc_ids(contexts),
                    "answer_composer": composer,
                    "answer": answer,
                    "answer_context_count": len(answer_contexts),
                    "citation_count": len(citations),
                    "citations": citations,
                    "retrieval_errors": retrieval_errors,
                    "meta_errors": meta_errors,
                    "answer_errors": answer_errors,
                    "citation_errors": citation_errors,
                    "errors": errors,
                    "meta": meta,
                    "top_contexts": [explain_context(context, index) for index, context in enumerate(contexts[:5])],
                }
            )
    finally:
        db.close()
    return failures, results


def print_summary(results: list[dict[str, Any]], failures: int, *, explain: bool = False) -> None:
    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        print(
            f"[{status}] {result['id']} :: backend={result['backend']} "
            f"answer={result['answer_composer']} citations={result['citation_count']} ranked={result['ranked_doc_ids'][:5]}"
        )
        for error in result.get("errors") or []:
            print(f"  - {error}")
        if explain:
            print(f"  question: {result['question']}")
            print(f"  note: {result['note']}")
            print(f"  answer: {result['answer']}")
            for context in result["top_contexts"]:
                print(f"  Top {context['rank']}: {context['title']} [{context['channel']}]")
                if context["snippet"]:
                    print(f"    snippet: {context['snippet']}")
    total = len(results)
    print(f"Answer eval: {total - failures}/{total} passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic retrieval + answer evaluation cases.")
    parser.add_argument("--cases", default=None, help="Path to answer eval JSON. Defaults to tests/retrieval_answer_eval_cases.json.")
    parser.add_argument("--real-db", action="store_true", help="Run against configured DATABASE_URL, falling back to backend/data/app.db")
    parser.add_argument("--pipeline", action="store_true", help="Exercise the production RAG pipeline")
    parser.add_argument("--llm", action="store_true", help="Compose grounded answers with the configured production model")
    parser.add_argument("--json", action="store_true", help="Print full JSON results")
    parser.add_argument("--explain", action="store_true", help="Print top-context and answer details")
    parser.add_argument("--keep-db", action="store_true", help="Keep isolated SQLite DB and uploaded fixture files for debugging")
    parser.add_argument("--skip-retrieval-validation", action="store_true", help="Only validate answer_expected fields")
    args = parser.parse_args()

    cases_path = Path(args.cases) if args.cases else (DEFAULT_REAL_CASES_PATH if args.real_db else DEFAULT_ANSWER_CASES_PATH)
    if args.real_db:
        if not DATABASE_URL_WAS_CONFIGURED:
            os.environ["DATABASE_URL"] = f"sqlite:///{REAL_DB_PATH.as_posix()}"
    else:
        os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
        os.environ["VECTOR_BACKEND"] = "local"
        os.environ["EMBEDDING_PROVIDER"] = "local"
        reset_storage()

    payload = load_cases(cases_path)
    failures, results = run_answer_eval(
        payload,
        real_db=args.real_db,
        skip_retrieval_validation=args.skip_retrieval_validation,
        pipeline=args.pipeline,
        use_llm=args.llm,
    )

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
