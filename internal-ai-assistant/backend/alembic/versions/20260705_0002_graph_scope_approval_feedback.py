"""add graph scope approval feedback schema

Revision ID: 20260705_0002
Revises: 20260627_0001
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260705_0002"
down_revision = "20260627_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="approved"))
    op.add_column("users", sa.Column("approval_note", sa.Text(), nullable=False, server_default=""))
    op.add_column("users", sa.Column("approved_by_user_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("approved_by_username", sa.String(length=100), nullable=False, server_default=""))
    op.add_column("users", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_users_approval_status"), "users", ["approval_status"], unique=False)
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_foreign_key(
            "fk_users_approved_by_user_id_users",
            "users",
            ["approved_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column("documents", sa.Column("knowledge_scope", sa.String(length=30), nullable=False, server_default="production"))
    op.add_column("documents", sa.Column("document_kind", sa.String(length=50), nullable=False, server_default="general"))
    op.add_column("documents", sa.Column("document_kind_confidence", sa.Float(), nullable=False, server_default="1.0"))
    op.add_column("documents", sa.Column("document_kind_reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("documents", sa.Column("document_kind_status", sa.String(length=30), nullable=False, server_default="confirmed"))
    op.create_index(op.f("ix_documents_knowledge_scope"), "documents", ["knowledge_scope"], unique=False)
    op.create_index(op.f("ix_documents_document_kind"), "documents", ["document_kind"], unique=False)
    op.create_index(op.f("ix_documents_document_kind_status"), "documents", ["document_kind_status"], unique=False)

    op.add_column("feedback", sa.Column("root_cause", sa.String(length=50), nullable=False, server_default=""))
    op.create_index(op.f("ix_feedback_root_cause"), "feedback", ["root_cause"], unique=False)

    op.create_table(
        "graph_entities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="confirmed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", "entity_type", name="ux_graph_entities_normalized_type"),
    )
    op.create_index(op.f("ix_graph_entities_name"), "graph_entities", ["name"], unique=False)
    op.create_index(op.f("ix_graph_entities_normalized_name"), "graph_entities", ["normalized_name"], unique=False)
    op.create_index(op.f("ix_graph_entities_entity_type"), "graph_entities", ["entity_type"], unique=False)
    op.create_index(op.f("ix_graph_entities_status"), "graph_entities", ["status"], unique=False)

    op.create_table(
        "graph_relations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_entity_id", sa.String(), nullable=False),
        sa.Column("target_entity_id", sa.String(), nullable=False),
        sa.Column("relation_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("source_document_id", sa.String(), nullable=False),
        sa.Column("source_chunk_id", sa.String(), nullable=True),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_chunk_id"], ["document_chunks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_graph_relations_source_entity_id"), "graph_relations", ["source_entity_id"], unique=False)
    op.create_index(op.f("ix_graph_relations_target_entity_id"), "graph_relations", ["target_entity_id"], unique=False)
    op.create_index(op.f("ix_graph_relations_relation_type"), "graph_relations", ["relation_type"], unique=False)
    op.create_index(op.f("ix_graph_relations_source_document_id"), "graph_relations", ["source_document_id"], unique=False)
    op.create_index(op.f("ix_graph_relations_source_chunk_id"), "graph_relations", ["source_chunk_id"], unique=False)
    op.create_index(op.f("ix_graph_relations_status"), "graph_relations", ["status"], unique=False)

    op.create_table(
        "graph_mentions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.String(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("mention_text", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["graph_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_graph_mentions_entity_id"), "graph_mentions", ["entity_id"], unique=False)
    op.create_index(op.f("ix_graph_mentions_document_id"), "graph_mentions", ["document_id"], unique=False)
    op.create_index(op.f("ix_graph_mentions_chunk_id"), "graph_mentions", ["chunk_id"], unique=False)

    op.create_table(
        "graph_extraction_status",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="not_started"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(op.f("ix_graph_extraction_status_status"), "graph_extraction_status", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_graph_extraction_status_status"), table_name="graph_extraction_status")
    op.drop_table("graph_extraction_status")

    op.drop_index(op.f("ix_graph_mentions_chunk_id"), table_name="graph_mentions")
    op.drop_index(op.f("ix_graph_mentions_document_id"), table_name="graph_mentions")
    op.drop_index(op.f("ix_graph_mentions_entity_id"), table_name="graph_mentions")
    op.drop_table("graph_mentions")

    op.drop_index(op.f("ix_graph_relations_status"), table_name="graph_relations")
    op.drop_index(op.f("ix_graph_relations_source_chunk_id"), table_name="graph_relations")
    op.drop_index(op.f("ix_graph_relations_source_document_id"), table_name="graph_relations")
    op.drop_index(op.f("ix_graph_relations_relation_type"), table_name="graph_relations")
    op.drop_index(op.f("ix_graph_relations_target_entity_id"), table_name="graph_relations")
    op.drop_index(op.f("ix_graph_relations_source_entity_id"), table_name="graph_relations")
    op.drop_table("graph_relations")

    op.drop_index(op.f("ix_graph_entities_status"), table_name="graph_entities")
    op.drop_index(op.f("ix_graph_entities_entity_type"), table_name="graph_entities")
    op.drop_index(op.f("ix_graph_entities_normalized_name"), table_name="graph_entities")
    op.drop_index(op.f("ix_graph_entities_name"), table_name="graph_entities")
    op.drop_table("graph_entities")

    op.drop_index(op.f("ix_feedback_root_cause"), table_name="feedback")
    op.drop_column("feedback", "root_cause")

    op.drop_index(op.f("ix_documents_document_kind_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_document_kind"), table_name="documents")
    op.drop_index(op.f("ix_documents_knowledge_scope"), table_name="documents")
    op.drop_column("documents", "document_kind_status")
    op.drop_column("documents", "document_kind_reason")
    op.drop_column("documents", "document_kind_confidence")
    op.drop_column("documents", "document_kind")
    op.drop_column("documents", "knowledge_scope")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_approved_by_user_id_users", type_="foreignkey")
    op.drop_index(op.f("ix_users_approval_status"), table_name="users")
    op.drop_column("users", "approved_at")
    op.drop_column("users", "approved_by_username")
    op.drop_column("users", "approved_by_user_id")
    op.drop_column("users", "approval_note")
    op.drop_column("users", "approval_status")
