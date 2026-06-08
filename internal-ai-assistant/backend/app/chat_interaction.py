import json
import re
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .grounding import build_context_highlight, citation_match_reason, filter_relevant_contexts
from .models import ChatMessage, ChatSession, Document, DocumentChunk, User
from .retrieval import accessible_document_ids, user_group_ids
from .routers.deps import parse_json_list

SUMMARY_INTENT_PATTERNS = (
    "我能访问",
    "可访问",
    "有哪些文档",
    "有什么文档",
    "文档重点",
    "总结文档",
    "知识库有哪些",
    "知识库文档",
    "全部文档",
)
FOLLOWUP_PATTERNS = (
    "继续",
    "展开",
    "详细",
    "具体",
    "上面",
    "刚才",
    "这个",
    "这份",
    "这篇",
    "该文档",
    "来源",
    "引用",
    "再说",
    "进一步",
)
CHIT_PATTERNS = (
    "制度",
    "规则",
    "流程",
    "审批",
    "申请",
    "报销",
    "权限",
    "文档",
    "知识库",
    "附件",
    "数据",
    "合同",
    "政策",
    "规定",
    "年假",
    "请假",
    "加班",
    "调休",
    "薪资",
    "工资",
    "绩效",
    "考勤",
    "入职",
    "离职",
    "转正",
    "采购",
    "预算",
)
# 摘要模式默认纳入每份可读文档的全部已解析片段；总上下文预算由 chat_api.model_contexts_for_answer 统一控制。
MAX_FOLLOWUP_CONTEXTS = 6


def is_accessible_summary_request(question: str) -> bool:
    text = (question or "").strip().lower()
    if not text:
        return False
    if any(pattern in text for pattern in SUMMARY_INTENT_PATTERNS):
        return True
    return bool(re.search(r"(总结|概括|梳理).{0,8}(文档|资料|知识库)", text))


def is_followup_request(question: str) -> bool:
    text = (question or "").strip().lower()
    if not text:
        return False
    return any(pattern in text for pattern in FOLLOWUP_PATTERNS)


def is_standalone_editing_request(question: str, has_history: bool = False) -> bool:
    """Requests like '整理成表格' need source text, not knowledge retrieval, when no context exists."""
    if has_history:
        return False
    text = (question or "").strip().lower()
    if not text:
        return False
    if any(anchor in text for anchor in ("知识库", "文档", "资料", "附件", "公司", "制度", "流程", "数据")):
        return False
    return bool(re.search(r"(整理|改写|润色|翻译|总结|概括|提炼|生成|制作|转成|转换).{0,8}(表格|清单|摘要|要点|格式|英文|中文)?", text))


def is_conversation_only_request(question: str) -> bool:
    text = (question or "").strip().lower()
    if not text:
        return True
    if any(pattern in text for pattern in CHIT_PATTERNS):
        return False
    if is_accessible_summary_request(text) or is_followup_request(text):
        return False
    normalized = re.sub(r"[，,。.!！?？\s]+", "", text)
    conversation_only_phrases = {
        "你好", "您好", "嗨", "哈喽", "在吗", "在不在", "有人吗",
        "谢谢", "多谢", "辛苦了", "感谢", "早上好", "上午好", "中午好", "下午好", "晚上好",
        "hello", "hi", "hey", "thanks", "thankyou", "goodmorning", "goodafternoon", "goodevening",
    }
    if normalized in conversation_only_phrases:
        return True
    assistant_identity_patterns = (
        r"你是谁",
        r"你是(什么|谁)",
        r"你能(做|干)什么",
        r"你可以(做|干|帮|解答).{0,12}(什么|哪些|啥|问题)",
        r"你能帮我.{0,8}(什么|哪些|啥|问题)",
        r"你能解答.{0,8}(什么|哪些|啥|问题)",
        r"你有什么(功能|能力|用处)",
        r"介绍一下你自己",
        r"怎么使用你",
        r"你会什么",
        r"who are you",
        r"what can you do",
        r"how can i use you",
    )
    return any(re.search(pattern, text) for pattern in assistant_identity_patterns)


def is_explicit_knowledge_request(question: str) -> bool:
    """规则层只命中明确需要知识库/附件/公司资料的问题，避免把普通闲聊误判为检索。"""
    text = (question or "").strip().lower()
    if not text or is_conversation_only_request(text):
        return False
    if is_accessible_summary_request(text) or is_followup_request(text):
        return True
    return any(pattern in text for pattern in CHIT_PATTERNS)


def is_knowledge_intent(question: str) -> bool:
    text = (question or "").strip().lower()
    if not text:
        return False
    if is_conversation_only_request(text):
        return False
    if is_explicit_knowledge_request(text):
        return True
    if re.search(r"(怎么|如何|为什么|是否|能否|可以|应该|多少|哪些|什么|哪几个|哪种|怎样|how|what|why|when|where|which|who)", text):
        return True
    if len(re.sub(r"\s+", "", text)) >= 12:
        return True
    return False


def _source_to_context(source: dict) -> dict:
    score = source.get("score") or source.get("confidence") or 0.35
    try:
        score = max(float(score), 0.62)
    except (TypeError, ValueError):
        score = 0.62
    return {
        "document_id": source.get("document_id") or "",
        "document_title": source.get("document_title") or source.get("title") or source.get("filename") or "未知文档",
        "filename": source.get("filename") or source.get("file_name") or "",
        "chunk_id": source.get("chunk_id") or None,
        "page_number": source.get("page_number") or source.get("page"),
        "chunk_index": source.get("chunk_index"),
        "source_type": source.get("source_type") or "document",
        "content": source.get("content") or source.get("snippet") or source.get("excerpt") or source.get("matched_snippet") or "",
        "score": score,
    }


def recent_source_contexts(db: Session, session_id: str | None, user: User, limit: int = MAX_FOLLOWUP_CONTEXTS) -> list[dict]:
    if not session_id:
        return []
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        return []
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc())
        .limit(4)
    ).scalars().all()
    contexts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for message in rows:
        for source in parse_json_list(getattr(message, "sources_json", "[]")):
            context = _source_to_context(source)
            key = (context.get("document_id") or "", context.get("chunk_id") or str(context.get("chunk_index") or ""))
            if key in seen:
                continue
            seen.add(key)
            contexts.append(context)
            if len(contexts) >= limit:
                return contexts
    return contexts


def enrich_contexts_with_recent_sources(db: Session, question: str, user: User, session_id: str | None, contexts: list[dict], limit: int) -> tuple[list[dict], bool]:
    if not is_followup_request(question):
        return contexts, False
    recent = recent_source_contexts(db, session_id, user, limit=limit)
    if not recent:
        return contexts, False
    filtered_recent = filter_relevant_contexts(recent, question, min_score=0.0) or recent
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for context in [*filtered_recent, *contexts]:
        key = (context.get("document_id") or "", context.get("chunk_id") or str(context.get("chunk_index") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(context)
        if len(merged) >= max(limit, MAX_FOLLOWUP_CONTEXTS):
            break
    return merged, True


def _chunk_context(doc: Document, chunk: DocumentChunk, score: float = 0.72) -> dict:
    context = {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": chunk.id,
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "source_type": str(doc.source_type or "document"),
        "content": chunk.content,
        "score": score,
        "match_terms": [],
    }
    context["match_reason"] = citation_match_reason(context, [])
    context["highlight_html"], context["highlight_ranges"] = build_context_highlight(context, [])
    context["matched_snippet"] = chunk.content[:500]
    return context


def accessible_document_summary_contexts(db: Session, user: User, per_doc_chunks: int | None = None, max_docs: int | None = None) -> tuple[list[dict], dict]:
    group_ids = user_group_ids(user)
    doc_ids = accessible_document_ids(db, user, group_ids)
    if not doc_ids:
        return [], {"document_count": 0, "documents": [], "source_contexts": []}

    query = (
        select(Document)
        .where(Document.id.in_(doc_ids))
        .order_by(Document.created_at.desc())
    )
    if max_docs:
        query = query.limit(max_docs)
    docs = db.execute(query).scalars().all()

    chunk_counts = dict(
        db.execute(
            select(DocumentChunk.document_id, func.count(DocumentChunk.id))
            .where(DocumentChunk.document_id.in_([doc.id for doc in docs]))
            .group_by(DocumentChunk.document_id)
        ).all()
    ) if docs else {}

    contexts: list[dict] = []
    source_contexts: list[dict] = []
    documents: list[dict] = []
    requested_chunk_limit = int(per_doc_chunks or 0)
    for doc in docs:
        total_chunks = int(chunk_counts.get(doc.id, 0) or 0)
        chunk_query = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        if requested_chunk_limit > 0:
            chunk_query = chunk_query.limit(requested_chunk_limit)
        chunks = db.execute(chunk_query).scalars().all()
        documents.append({
            "id": doc.id,
            "title": doc.title,
            "filename": doc.filename,
            "source_type": doc.source_type,
            "chunks_used": len(chunks),
            "total_chunks": total_chunks,
        })

        combined_parts: list[str] = []
        for chunk in chunks:
            context = _chunk_context(doc, chunk)
            contexts.append(context)
            combined_parts.append(context["content"] or "")

        source_contexts.append({
            "document_id": doc.id,
            "document_title": doc.title,
            "filename": doc.filename,
            "chunk_id": None,
            "page_number": None,
            "chunk_index": None,
            "source_type": str(doc.source_type or "document"),
            "content": "\n\n".join(combined_parts) or f"文档《{doc.title or doc.filename}》当前可读，但暂未解析出可用于摘要的文本片段。",
            "score": 0.72 if chunks else 0.35,
            "match_terms": [],
            "match_reason": f"可读文档总览；已纳入片段 {len(chunks)}/{total_chunks}",
            "matched_snippet": "\n\n".join(combined_parts)[:500],
            "location": f"document | chunks {len(chunks)}/{total_chunks}",
            "section_title": "可读文档总览",
            "summary_source": True,
            "chunks_used": len(chunks),
            "total_chunks": total_chunks,
        })
    return contexts, {"document_count": len(docs), "documents": documents, "source_contexts": source_contexts}


def build_interaction_suggestions(question: str, contexts: Iterable[dict], summary_mode: bool = False) -> list[str]:
    docs = []
    seen = set()
    for context in contexts:
        title = context.get("document_title") or context.get("filename")
        if title and title not in seen:
            seen.add(title)
            docs.append(title)
    if summary_mode and docs:
        first = docs[0]
        return [
            f"继续展开《{first}》的关键信息",
            "按字段/流程/风险点重新整理",
            "列出我可以继续追问的问题",
        ]
    if docs:
        first = docs[0]
        return [
            f"围绕《{first}》继续追问",
            "把刚才回答整理成表格",
            "指出依据不足或需要补充的资料",
        ]
    return ["上传或授权更多文档", "换一个更具体的问题", "让我总结我能访问的文档"]


def append_interaction_footer(answer: str, suggestions: list[str]) -> str:
    if not suggestions:
        return answer
    footer = "\n\n你可以继续问：\n" + "\n".join(f"- {item}" for item in suggestions[:3])
    return (answer or "") + footer
