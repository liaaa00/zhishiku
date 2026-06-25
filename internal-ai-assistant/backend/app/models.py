from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from .database import Base

user_group_link = Table(
    "user_group_link",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", String, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

document_group_link = Table(
    "document_group_link",
    Base.metadata,
    Column("document_id", String, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", String, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    groups = relationship("Group", secondary=user_group_link, back_populates="users")


class Group(Base):
    __tablename__ = "groups"
    id = Column(String, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    users = relationship("User", secondary=user_group_link, back_populates="groups")
    documents = relationship("Document", secondary=document_group_link, back_populates="groups")


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    source_type = Column(String(20), nullable=False, default="pdf")
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    groups = relationship("Group", secondary=document_group_link, back_populates="documents")
    chunks = relationship("DocumentChunk", cascade="all, delete-orphan", back_populates="document")
    table_rows = relationship("DocumentTableRow", cascade="all, delete-orphan", back_populates="document")
    page_index = relationship("DocumentPageIndex", cascade="all, delete-orphan", back_populates="document", uselist=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(String, primary_key=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    page_number = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding_json = Column(Text, nullable=False)
    document = relationship("Document", back_populates="chunks")


class DocumentTableRow(Base):
    __tablename__ = "document_table_rows"
    id = Column(String, primary_key=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    sheet_name = Column(String(120), nullable=False, default="")
    row_number = Column(Integer, nullable=True)
    row_key = Column(String(200), nullable=False, default="")
    row_json = Column(Text, nullable=False)
    row_text = Column(Text, nullable=False)
    is_header = Column(Boolean, nullable=False, default=False)
    source_chunk_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    document = relationship("Document", back_populates="table_rows")


class DocumentPageIndex(Base):
    __tablename__ = "document_page_indexes"
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(30), nullable=False, default="not_built")  # not_built/pending/processing/ready/failed
    index_type = Column(String(30), nullable=False, default="pageindex")
    engine = Column(String(80), nullable=False, default="")
    workspace_doc_id = Column(String(120), nullable=False, default="")
    index_path = Column(String(500), nullable=False, default="")
    doc_description = Column(Text, nullable=False, default="")
    page_count = Column(Integer, nullable=False, default=0)
    node_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    document = relationship("Document", back_populates="page_index")


class DocumentProcessingStatus(Base):
    __tablename__ = "document_processing_status"
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="pending")  # pending/processing/ready/failed
    stage = Column(String(80), nullable=False, default="uploaded")
    message = Column(Text, nullable=False, default="")
    chunks = Column(Integer, nullable=False, default=0)
    searchable = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    document = relationship("Document")


class BackgroundTask(Base):
    __tablename__ = "background_tasks"
    id = Column(String, primary_key=True)
    task_type = Column(String(80), nullable=False, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="pending", index=True)  # pending/running/success/failed
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=False, default="")
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    document = relationship("Document")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True)
    actor_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_username = Column(String(100), nullable=False, default="system")
    action = Column(String(120), nullable=False, index=True)
    resource_type = Column(String(80), nullable=False, default="")
    resource_id = Column(String, nullable=False, default="")
    detail_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sources_json = Column(Text, nullable=False, default="[]")
    mode = Column(String(20), nullable=False, default="knowledge")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(100), nullable=False, default="")
    session_id = Column(String, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    message_id = Column(String, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    rating = Column(String(30), nullable=False, default="")
    category = Column(String(50), nullable=False, default="other", index=True)
    content = Column(Text, nullable=False)
    question_snapshot = Column(Text, nullable=False, default="")
    answer_snapshot = Column(Text, nullable=False, default="")
    sources_json = Column(Text, nullable=False, default="[]")
    status = Column(String(30), nullable=False, default="new", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(Text, nullable=False, default="")
    admin_note = Column(Text, nullable=False, default="")
    handled_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    handled_by_username = Column(String(100), nullable=False, default="")
    handled_at = Column(DateTime, nullable=True)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(120), primary_key=True)
    value = Column(Text, nullable=False, default="")
