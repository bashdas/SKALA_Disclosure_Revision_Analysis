"""Remove organization partitions from derived retrieval storage."""
from alembic import op
import sqlalchemy as sa

revision = "0005_single_company"
down_revision = "0004_internal_reports"
branch_labels = depends_on = None


def upgrade():
    # Preserve every distinct vector/document; identical legacy cache entries can share one ID.
    op.execute("""CREATE TEMP TABLE report_document_merge ON COMMIT DROP AS
        SELECT id, first_value(id) OVER (PARTITION BY document_type, identifier, version, content_hash, fingerprint ORDER BY id) AS canonical
        FROM rag.documents""")
    # Remove old composite foreign keys before updating their document references.
    bind = op.get_bind()
    for table in ("chunks", "analysis_indexes"):
        for fk in sa.inspect(bind).get_foreign_keys(table, schema="rag"):
            if "organization_id" in fk["constrained_columns"]:
                op.drop_constraint(fk["name"], table, schema="rag", type_="foreignkey")
    for column in ("memo_document_id", "disclosure_document_id"):
        op.execute(f"UPDATE rag.analysis_indexes a SET {column}=m.canonical FROM report_document_merge m WHERE a.{column}=m.id AND m.id<>m.canonical")
    op.execute("DELETE FROM rag.chunks WHERE document_id IN (SELECT id FROM report_document_merge WHERE id<>canonical)")
    op.execute("DELETE FROM rag.documents WHERE id IN (SELECT id FROM report_document_merge WHERE id<>canonical)")
    for table in ("chunks", "analysis_indexes", "documents"):
        op.drop_column(table, "organization_id", schema="rag")
    op.create_unique_constraint("uq_document_identity", "documents",
        ["document_type", "identifier", "version", "content_hash", "fingerprint"], schema="rag")
    op.create_foreign_key("fk_chunks_document", "chunks", "documents", ["document_id"], ["id"],
        source_schema="rag", referent_schema="rag", ondelete="CASCADE")
    for column in ("memo_document_id", "disclosure_document_id"):
        op.create_foreign_key("fk_analysis_index_" + column, "analysis_indexes", "documents", [column], ["id"],
            source_schema="rag", referent_schema="rag")
    op.create_index("ix_chunk_scope", "chunks", ["document_id"], schema="rag")


def downgrade():
    from sqlalchemy.dialects.postgresql import UUID
    # Downgrade restores a single legacy partition; original organization boundaries are not recoverable.
    op.drop_constraint("fk_chunks_document", "chunks", schema="rag", type_="foreignkey")
    for column in ("memo_document_id", "disclosure_document_id"):
        op.drop_constraint("fk_analysis_index_" + column, "analysis_indexes", schema="rag", type_="foreignkey")
    op.drop_constraint("uq_document_identity", "documents", schema="rag", type_="unique")
    op.drop_index("ix_chunk_scope", table_name="chunks", schema="rag")
    for table in ("documents", "chunks", "analysis_indexes"):
        op.add_column(table, sa.Column("organization_id", UUID(), nullable=False,
            server_default=sa.text("'00000000-0000-0000-0000-000000000001'::uuid")), schema="rag")
        op.alter_column(table, "organization_id", server_default=None, schema="rag")
    op.create_unique_constraint("uq_document_organization", "documents", ["id", "organization_id"], schema="rag")
    op.create_unique_constraint("uq_document_identity", "documents",
        ["organization_id", "document_type", "identifier", "version", "content_hash", "fingerprint"], schema="rag")
    op.create_foreign_key("fk_chunks_document", "chunks", "documents", ["document_id", "organization_id"],
        ["id", "organization_id"], source_schema="rag", referent_schema="rag", ondelete="CASCADE")
    for column in ("memo_document_id", "disclosure_document_id"):
        op.create_foreign_key("fk_analysis_index_" + column, "analysis_indexes", "documents", [column, "organization_id"],
            ["id", "organization_id"], source_schema="rag", referent_schema="rag")
    op.create_index("ix_chunk_scope", "chunks", ["organization_id", "document_id"], schema="rag")
