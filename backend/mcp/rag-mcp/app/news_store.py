import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Text,
    delete,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketNews(Base):
    __tablename__ = "market_news"
    __table_args__ = (
        Index("ix_market_news_published", "published_at"),
        Index("ix_market_news_first_seen", "first_seen_at"),
        Index("ix_market_news_codes", "company_codes", postgresql_using="gin"),
        Index("ix_market_news_names", "company_names", postgresql_using="gin"),
        Index("ix_market_news_common", "market_wide", "first_seen_at"),
        {"schema": "rag"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    company_codes: Mapped[list] = mapped_column(JSONB)
    company_names: Mapped[list] = mapped_column(JSONB)
    market_wide: Mapped[bool] = mapped_column(Boolean)
    classification_reason: Mapped[str] = mapped_column(Text)
    classifier_version: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(Vector(1536))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewsCollection(Base):
    __tablename__ = "market_news_collection"
    __table_args__ = {"schema": "rag"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB)


class NewsStore:
    def __init__(self, store):
        self.engine, self.sessions = store.engine, store.sessions

    @contextmanager
    def collection_lock(self):
        with self.engine.connect() as conn:
            acquired = conn.scalar(text("SELECT pg_try_advisory_lock(764383012)"))
            conn.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    conn.execute(text("SELECT pg_advisory_unlock(764383012)"))
                    conn.commit()

    def due(self, now, interval):
        with self.sessions() as session:
            row = session.get(NewsCollection, 1)
            return row is None or now >= row.started_at + timedelta(seconds=interval)

    def mark(self, started, status, details, finished=None):
        with self.sessions.begin() as session:
            session.execute(insert(NewsCollection).values(id=1, started_at=started, finished_at=finished,
                status=status, details=details).on_conflict_do_update(index_elements=[NewsCollection.id],
                    set_={"started_at": started, "finished_at": finished, "status": status, "details": details}))

    def targets(self):
        with self.sessions() as session:
            return [dict(row) for row in session.execute(text("""
                SELECT DISTINCT f.corp_code, f.company_name
                FROM core.company_favorites f JOIN core.users u ON u.id=f.user_id
                WHERE u.is_active = true ORDER BY f.corp_code, f.company_name
            """)).mappings()]

    def existing(self, urls, classifier_version):
        with self.sessions() as session:
            return {row.url: row.title for row in session.scalars(select(MarketNews).where(
                MarketNews.url.in_(urls), MarketNews.classifier_version == classifier_version))}

    def save(self, rows):
        with self.sessions.begin() as session:
            for row in rows:
                command = insert(MarketNews).values(id=uuid.uuid4(), **row)
                session.execute(command.on_conflict_do_update(index_elements=[MarketNews.url],
                    set_={key: getattr(command.excluded, key) for key in row if key != "first_seen_at"}))

    def purge(self, cutoff):
        with self.sessions.begin() as session:
            return session.execute(delete(MarketNews).where(
                func.coalesce(MarketNews.published_at, MarketNews.first_seen_at) < cutoff)).rowcount

    @staticmethod
    def scope(corp_code, company_name, as_of, days):
        return [or_(MarketNews.market_wide.is_(True),
                    MarketNews.company_codes.contains([corp_code]) if corp_code else False,
                    MarketNews.company_names.contains([company_name]) if company_name else False),
                MarketNews.first_seen_at <= as_of,
                or_(MarketNews.published_at.is_(None), MarketNews.published_at <= as_of),
                func.coalesce(MarketNews.published_at, MarketNews.first_seen_at) >= as_of - timedelta(days=days)]

    @staticmethod
    def item(row):
        return {"id": str(row.id), "title": row.title, "url": row.url,
                "company_codes": row.company_codes, "company_names": row.company_names,
                "market_wide": row.market_wide, "classification_reason": row.classification_reason,
                "first_seen_at": row.first_seen_at.isoformat(),
                "published_at": row.published_at.isoformat() if row.published_at else None}

    def search(self, corp_code, company_name, as_of, days, vector, limit):
        with self.sessions() as session:
            rows = session.scalars(select(MarketNews).where(*self.scope(corp_code, company_name, as_of, days))
                .order_by(MarketNews.embedding.cosine_distance(vector), MarketNews.first_seen_at.desc()).limit(limit))
            return [self.item(row) for row in rows]

    def articles(self, identifiers, corp_code, company_name, as_of, days):
        with self.sessions() as session:
            return [self.item(row) for row in session.scalars(select(MarketNews).where(
                MarketNews.id.in_(identifiers), *self.scope(corp_code, company_name, as_of, days)))]

    def status(self):
        with self.sessions() as session:
            row = session.get(NewsCollection, 1)
            return {"status": row.status, "started_at": row.started_at.isoformat(),
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    "details": row.details} if row else {"status": "NOT_STARTED"}
