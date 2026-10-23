"""Allow company internal report vectors."""
from alembic import op

revision = "0004_internal_reports"
down_revision = "0003_news_pipeline"
branch_labels = depends_on = None


def replace(expression):
    op.drop_constraint("ck_document_type", "documents", schema="rag", type_="check")
    op.create_check_constraint("ck_document_type", "documents", expression, schema="rag")


def upgrade():
    replace("document_type IN ('MEMO', 'DISCLOSURE', 'INTERNAL_REPORT')")


def downgrade():
    op.execute("DELETE FROM rag.documents WHERE document_type='INTERNAL_REPORT'")
    replace("document_type IN ('MEMO', 'DISCLOSURE')")
