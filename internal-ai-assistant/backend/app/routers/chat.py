from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChatMessage, ChatSession, User
from .deps import parse_json_list, require_user

router = APIRouter()


MESSAGE_ORDER = (ChatMessage.created_at.asc(), case((ChatMessage.role == "user", 0), else_=1).asc(), ChatMessage.id.asc())


def session_payload(db: Session, session: ChatSession) -> dict:
    messages = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(*MESSAGE_ORDER)
    ).scalars().all()
    first_user = next((m.content for m in messages if m.role == "user"), "新的对话")
    last = messages[-1].content if messages else "还没有消息"
    return {
        "id": session.id,
        "title": first_user[:28],
        "preview": last[:42],
        "message_count": len(messages),
        "created_at": session.created_at.isoformat(),
    }


def message_to_dict(message: ChatMessage) -> dict:
    sources = parse_json_list(getattr(message, "sources_json", "[]")) if message.role == "assistant" else []
    is_document_overview = bool(sources and all(source.get("summary_source") for source in sources if isinstance(source, dict)))
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "sources": sources,
        "citations": sources,
        "mode": getattr(message, "mode", "knowledge") or "knowledge",
        "citation_mode": "accessible_documents" if is_document_overview else "matched_chunks",
        "document_count": len(sources) if is_document_overview else 0,
        "summary_mode": is_document_overview,
    }


@router.get("/api/chat/sessions")
def list_chat_sessions(db: Session = Depends(get_db), user: User = Depends(require_user)):
    sessions = db.execute(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.created_at.desc())
    ).scalars().all()
    return [session_payload(db, s) for s in sessions]


@router.get("/api/chat/sessions/{session_id}")
def get_chat_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(*MESSAGE_ORDER)
    ).scalars().all()
    return {
        "session": session_payload(db, session),
        "messages": [message_to_dict(m) for m in messages],
    }


@router.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"ok": True}
