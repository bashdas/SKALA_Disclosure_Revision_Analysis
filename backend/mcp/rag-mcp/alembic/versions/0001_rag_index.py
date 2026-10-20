"""Create independent RAG document and vector index storage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from pgvector.sqlalchemy import Vector

revision = "0001_rag_index"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("documents",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("organization_id", pg.UUID(), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False),
        sa.Column("identifier", sa.String(100), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(150), nullable=False),
        sa.Column("source", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "document_type", "identifier", "version", "content_hash", "fingerprint", name="uq_document_identity"),
        sa.UniqueConstraint("id", "organization_id", name="uq_document_organization"),
        sa.CheckConstraint("document_type IN ('MEMO', 'DISCLOSURE')", name="ck_document_type"), schema="rag")
    op.create_table("chunks",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("document_id", pg.UUID(), nullable=False),
        sa.Column("organization_id", pg.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata_json", pg.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id", "organization_id"], ["rag.documents.id", "rag.documents.organization_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunk_position"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_chunk_position"), schema="rag")
    op.create_index("ix_chunk_scope", "chunks", ["organization_id", "document_id"], schema="rag")
    op.create_table("analysis_indexes",
        sa.Column("task_id", pg.UUID(), primary_key=True),
        sa.Column("organization_id", pg.UUID(), nullable=False),
        sa.Column("memo_document_id", pg.UUID(), nullable=False),
        sa.Column("disclosure_document_id", pg.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["memo_document_id", "organization_id"], ["rag.documents.id", "rag.documents.organization_id"]),
        sa.ForeignKeyConstraint(["disclosure_document_id", "organization_id"], ["rag.documents.id", "rag.documents.organization_id"]), schema="rag")


def downgrade():
    op.drop_table("analysis_indexes", schema="rag")
    op.drop_index("ix_chunk_scope", table_name="chunks", schema="rag")
    op.drop_table("chunks", schema="rag")
    op.drop_table("documents", schema="rag")
    # vector extension and schema can be shared; never remove them here.
