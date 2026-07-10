from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import ChatMessage, ChatSession, User
from app.routers import chat_api


def test_new_chat_persists_session_before_messages(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        user = User(id="chat-user", username="chat-user", password_hash="", is_active=True)
        db.add(user)
        db.commit()

        monkeypatch.setattr(
            chat_api,
            "get_model_config",
            lambda _db: {"api_key": "", "base_url": "", "model": ""},
        )
        monkeypatch.setattr(chat_api, "_main_compat_callable", lambda _name: None)
        monkeypatch.setattr(chat_api, "conversational_answer", lambda *_args, **_kwargs: "你好，有什么可以帮你？")
        monkeypatch.setattr(chat_api, "audit", lambda *_args, **_kwargs: None)

        response = chat_api.chat(chat_api.ChatRequest(question="你好"), db, user)

        session = db.get(ChatSession, response["session_id"])
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == response["session_id"])
            .order_by(ChatMessage.created_at)
            .all()
        )
        assert session is not None
        assert [message.role for message in messages] == ["user", "assistant"]
    finally:
        db.close()
