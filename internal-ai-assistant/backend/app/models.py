from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint
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
    approval_status = Column(String(30), default="approved", nullable=False, index=True)  # pending/approved/rejected
    approval_note = Column(Text, default="", nullable=False)
    approved_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_username = Column(String(100), default="", nullable=False)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    groups = relationship("Group", secondary=user_group_link, back_populates="users", foreign_keys=[user_group_link.c.user_id, user_group_link.c.group_id])


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
    knowledge_scope = Column(String(30), nullable=False, default="production", index=True)  # production/test
    document_kind = Column(String(50), nullable=False, default="general", index=True)  # table/employee_guide/workorder/form/policy/general
    document_kind_confidence = Column(Float, nullable=False, default=1.0)
    document_kind_reason = Column(Text, nullable=False, default="")
    document_kind_status = Column(String(30), nullable=False, default="confirmed", index=True)  # auto/needs_review/confirmed
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


class GraphEntity(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (
        UniqueConstraint("normalized_name", "entity_type", name="ux_graph_entities_normalized_type"),
    )
    id = Column(String, primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    normalized_name = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(80), nullable=False, index=True)
    description = Column(Text, nullable=False, default="")
    confidence = Column(Float, nullable=False, default=0.0)
    status = Column(String(30), nullable=False, default="confirmed", index=True)  # confirmed/ignored
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class GraphRelation(Base):
    __tablename__ = "graph_relations"
    id = Column(String, primary_key=True)
    source_entity_id = Column(String, ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_entity_id = Column(String, ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(String(80), nullable=False, index=True)
    description = Column(Text, nullable=False, default="")
    confidence = Column(Float, nullable=False, default=0.0)
    source_document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    source_chunk_id = Column(String, ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True, index=True)
    source_page_number = Column(Integer, nullable=True)
    evidence_text = Column(Text, nullable=False, default="")
    status = Column(String(30), nullable=False, default="pending", index=True)  # pending/confirmed/ignored/auto
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    source_entity = relationship("GraphEntity", foreign_keys=[source_entity_id])
    target_entity = relationship("GraphEntity", foreign_keys=[target_entity_id])
    document = relationship("Document")
    chunk = relationship("DocumentChunk")


class GraphMention(Base):
    __tablename__ = "graph_mentions"
    id = Column(String, primary_key=True)
    entity_id = Column(String, ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String, ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True, index=True)
    page_number = Column(Integer, nullable=True)
    mention_text = Column(String(255), nullable=False, default="")
    confidence = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    entity = relationship("GraphEntity")


class GraphExtractionStatus(Base):
    __tablename__ = "graph_extraction_status"
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(30), nullable=False, default="not_started", index=True)  # not_started/pending/processing/ready/failed
    message = Column(Text, nullable=False, default="")
    entity_count = Column(Integer, nullable=False, default=0)
    relation_count = Column(Integer, nullable=False, default=0)
    pending_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    document = relationship("Document")


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


class TableSchemaAlias(Base):
    __tablename__ = "table_schema_aliases"
    __table_args__ = (
        UniqueConstraint("document_id", "sheet_name", "raw_name", "semantic_name", name="ux_table_schema_aliases_mapping"),
    )
    id = Column(String, primary_key=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    sheet_name = Column(String(120), nullable=False, default="")
    raw_name = Column(String(255), nullable=False, default="")
    semantic_name = Column(String(80), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="confirmed", index=True)  # confirmed/ignored
    confidence = Column(Float, nullable=False, default=0.0)
    suggestion_key = Column(String(500), nullable=False, default="", index=True)
    reasons_json = Column(Text, nullable=False, default="[]")
    samples_json = Column(Text, nullable=False, default="[]")
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    document = relationship("Document")


class WikiPage(Base):
    __tablename__ = "wiki_pages"
    __table_args__ = (
        UniqueConstraint("slug", "knowledge_scope", name="ux_wiki_pages_slug_scope"),
    )
    id = Column(String, primary_key=True)
    slug = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    page_type = Column(String(50), nullable=False, default="source", index=True)  # source/entity/concept/rule/overview
    status = Column(String(30), nullable=False, default="draft", index=True)  # draft/published/archived
    knowledge_scope = Column(String(30), nullable=False, default="production", index=True)
    summary = Column(Text, nullable=False, default="")
    content_md = Column(Text, nullable=False, default="")
    checksum = Column(String(80), nullable=False, default="", index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    sources = relationship("WikiPageSource", cascade="all, delete-orphan", back_populates="page")
    outgoing_links = relationship("WikiPageLink", cascade="all, delete-orphan", foreign_keys="WikiPageLink.source_page_id", back_populates="source_page")


class WikiPageSource(Base):
    __tablename__ = "wiki_page_sources"
    id = Column(String, primary_key=True)
    page_id = Column(String, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String, ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True, index=True)
    page_number = Column(Integer, nullable=True)
    source_order = Column(Integer, nullable=False, default=0)
    quote = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    page = relationship("WikiPage", back_populates="sources")
    document = relationship("Document")
    chunk = relationship("DocumentChunk")


class WikiPageLink(Base):
    __tablename__ = "wiki_page_links"
    __table_args__ = (
        UniqueConstraint("source_page_id", "target_page_id", "link_type", name="ux_wiki_page_links_unique"),
    )
    id = Column(String, primary_key=True)
    source_page_id = Column(String, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    target_page_id = Column(String, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    link_type = Column(String(50), nullable=False, default="wikilink", index=True)
    anchor_text = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    source_page = relationship("WikiPage", foreign_keys=[source_page_id], back_populates="outgoing_links")
    target_page = relationship("WikiPage", foreign_keys=[target_page_id])


class WikiCompileStatus(Base):
    __tablename__ = "wiki_compile_status"
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(30), nullable=False, default="not_started", index=True)  # not_started/ready/failed/stale
    message = Column(Text, nullable=False, default="")
    page_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=False, default="")
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
    root_cause = Column(String(50), nullable=False, default="", index=True)
    handled_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    handled_by_username = Column(String(100), nullable=False, default="")
    handled_at = Column(DateTime, nullable=True)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(120), primary_key=True)
    value = Column(Text, nullable=False, default="")
