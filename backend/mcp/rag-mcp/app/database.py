import hashlib
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.embedding import DIMENSION


class Base(DeclarativeBase):
    pass


class RagDocument(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "document_type", "identifier", "version", "content_hash", "fingerprint", name="uq_document_identity"),
        UniqueConstraint("id", "organization_id", name="uq_document_organization"),
        CheckConstraint("document_type IN ('MEMO', 'DISCLOSURE', 'INTERNAL_REPORT')", name="ck_document_type"),
        {"schema": "rag"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID)
    document_type: Mapped[str] = mapped_column(String(20))
    identifier: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(150))
    source: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RagChunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        ForeignKeyConstraint(["document_id", "organization_id"], ["rag.documents.id", "rag.documents.organization_id"], ondelete="CASCADE"),
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_position"),
        CheckConstraint("chunk_index >= 0", name="ck_chunk_position"),
        Index("ix_chunk_scope", "organization_id", "document_id"),
        {"schema": "rag"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(DIMENSION))
    metadata_json: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisIndex(Base):
    __tablename__ = "analysis_indexes"
    __table_args__ = (
        ForeignKeyConstraint(["memo_document_id", "organization_id"], ["rag.documents.id", "rag.documents.organization_id"]),
        ForeignKeyConstraint(["disclosure_document_id", "organization_id"], ["rag.documents.id", "rag.documents.organization_id"]),
        {"schema": "rag"},
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID)
    memo_document_id: Mapped[uuid.UUID] = mapped_column(UUID)
    disclosure_document_id: Mapped[uuid.UUID] = mapped_column(UUID)


class RagStore:
    def __init__(self, database_url):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def find_document(self, identity):
        with self.sessions() as session:
            document = session.scalar(select(RagDocument).filter_by(**identity))
            if document is None:
                return None
            count = session.scalar(select(func.count()).select_from(RagChunk).where(RagChunk.document_id == document.id))
            return {"id": document.id, "chunks": count, "source": document.source}

    def save_document(self, identity, source, chunks, vectors):
        with self.sessions.begin() as session:
            document_id = session.scalar(insert(RagDocument).values(id=uuid.uuid4(), **identity, source=source)
                .on_conflict_do_nothing(constraint="uq_document_identity").returning(RagDocument.id))
            if document_id is not None:
                session.add_all([RagChunk(document_id=document_id, organization_id=identity["organization_id"],
                    chunk_index=index, text=chunk.text, embedding=vector, metadata_json=chunk.metadata,
                    content_hash=hashlib.sha256(chunk.text.encode()).hexdigest())
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))])
        return self.find_document(identity)

    def link(self, task_id, organization_id, memo_id, disclosure_id):
        with self.sessions.begin() as session:
            row = session.get(AnalysisIndex, task_id, with_for_update=True)
            if row and row.organization_id != organization_id:
                raise ValueError("Task organization mismatch")
            session.execute(insert(AnalysisIndex).values(task_id=task_id, organization_id=organization_id,
                memo_document_id=memo_id, disclosure_document_id=disclosure_id).on_conflict_do_update(
                    index_elements=[AnalysisIndex.task_id], set_={"memo_document_id": memo_id, "disclosure_document_id": disclosure_id}))

    def search(self, task_id, organization_id, memo_id, version, receipt_no, fingerprint, vector, types, top_k, minimum):
        with self.sessions() as session:
            manifest = session.get(AnalysisIndex, task_id)
            if not manifest or manifest.organization_id != organization_id:
                return None
            documents = [session.get(RagDocument, manifest.memo_document_id), session.get(RagDocument, manifest.disclosure_document_id)]
            if (documents[0].identifier != str(memo_id) or documents[0].version != str(version)
                    or documents[1].identifier != receipt_no or any(d.fingerprint != fingerprint for d in documents)):
                return None
            distance = RagChunk.embedding.cosine_distance(vector)
            rows = session.execute(select(RagChunk, RagDocument, distance.label("distance"))
                .join(RagDocument, RagDocument.id == RagChunk.document_id)
                .where(RagChunk.organization_id == organization_id,
                    RagChunk.document_id.in_([d.id for d in documents]), RagDocument.document_type.in_(types),
                    distance <= 2 * (1 - minimum))
                .order_by(distance, RagChunk.document_id, RagChunk.chunk_index).limit(top_k))
            return [{"document_type": document.document_type, "text": chunk.text,
                "score": max(0.0, min(1.0, 1 - float(dist) / 2)),
                "source": {**document.source, **chunk.metadata_json, "document_id": str(document.id), "chunk_index": chunk.chunk_index}}
                for chunk, document, dist in rows]

    def search_reports(self, organization_id, document_ids, fingerprint, vector, top_k, minimum):
        with self.sessions() as session:
            distance = RagChunk.embedding.cosine_distance(vector)
            rows = session.execute(select(RagChunk, RagDocument, distance.label("distance"))
                .join(RagDocument, RagDocument.id == RagChunk.document_id)
                .where(RagChunk.organization_id == organization_id,
                    RagDocument.organization_id == organization_id,
                    RagDocument.document_type == "INTERNAL_REPORT",
                    RagDocument.fingerprint == fingerprint,
                    RagChunk.document_id.in_(document_ids), distance <= 2 * (1 - minimum))
                .order_by(distance, RagChunk.document_id, RagChunk.chunk_index).limit(top_k))
            return [{**doc.source, **chunk.metadata_json, "quote": chunk.text,
                "chunk_id": str(chunk.id), "score": max(0., min(1., 1 - float(dist) / 2))}
                for chunk, doc, dist in rows]
