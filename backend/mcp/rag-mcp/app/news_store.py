import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    Text,
    and_,
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
        Index("ix_market_news_expiry", "expires_at"),
        Index("ix_market_news_scope_published", "scope", "published_at"),
        Index("ix_market_news_industries", "industry_tags", postgresql_using="gin"),
        Index("ix_market_news_processing", "classification_status", "next_retry_at"),
        Index("ix_market_news_topics", "topic_tags", postgresql_using="gin"),
        CheckConstraint(
            "classification_status IN ('LEGACY','PENDING','CLASSIFIED','UNRESOLVED','FAILED')",
            name="ck_news_classification",
        ),
        CheckConstraint(
            "scope IN ('COMPANY','INDUSTRY','MACRO','UNRESOLVED')", name="ck_news_scope"
        ),
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
    embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    original_title: Mapped[str] = mapped_column(Text, server_default="")
    original_url: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    classification_status: Mapped[str] = mapped_column(Text, server_default="LEGACY")
    classification_method: Mapped[str] = mapped_column(Text, server_default="legacy")
    policy_version: Mapped[str] = mapped_column(Text, server_default="legacy")
    scope: Mapped[str] = mapped_column(Text, server_default="UNRESOLVED")
    industry_tags: Mapped[list] = mapped_column(JSONB, server_default="[]")
    topic_tags: Mapped[list] = mapped_column(JSONB, server_default="[]")
    search_queries: Mapped[list] = mapped_column(JSONB, server_default="[]")
    uncertainty: Mapped[str] = mapped_column(Text, server_default="")
    confidence: Mapped[float | None] = mapped_column(Float)
    importance: Mapped[str] = mapped_column(Text, server_default="NORMAL")
    index_status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewsQuery(Base):
    __tablename__ = "market_news_queries"
    __table_args__ = {"schema": "rag"}
    query: Mapped[str] = mapped_column(Text, primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSONB)


class NewsRun(Base):
    __tablename__ = "market_news_runs"
    __table_args__ = (
        Index("ix_market_news_runs_started", "started_at"),
        {"schema": "rag"},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB)


class NewsUsage(Base):
    __tablename__ = "market_news_usage"
    __table_args__ = {"schema": "rag"}
    day: Mapped[str] = mapped_column(Text, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer)


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
            session.execute(
                insert(NewsCollection)
                .values(
                    id=1,
                    started_at=started,
                    finished_at=finished,
                    status=status,
                    details=details,
                )
                .on_conflict_do_update(
                    index_elements=[NewsCollection.id],
                    set_={
                        "started_at": started,
                        "finished_at": finished,
                        "status": status,
                        "details": details,
                    },
                )
            )

    def targets(self):
        with self.sessions() as session:
            return [
                dict(row)
                for row in session.execute(
                    text("""
                SELECT DISTINCT f.corp_code, f.company_name
                FROM core.company_favorites f JOIN core.users u ON u.id=f.user_id
                WHERE u.is_active = true ORDER BY f.corp_code, f.company_name
            """)
                ).mappings()
            ]

    def query_states(self):
        with self.sessions() as session:
            return {
                r.query: {
                    "last_success_at": r.last_success_at,
                    "last_checked_at": r.last_checked_at,
                    "details": r.details,
                }
                for r in session.scalars(select(NewsQuery))
            }

    def record_query(self, query, now, complete, details):
        with self.sessions.begin() as session:
            values = {"query": query, "last_checked_at": now, "details": details}
            if complete:
                values["last_success_at"] = now
            command = insert(NewsQuery).values(**values)
            session.execute(
                command.on_conflict_do_update(
                    index_elements=[NewsQuery.query],
                    set_={
                        k: getattr(command.excluded, k) for k in values if k != "query"
                    },
                )
            )

    def claim_api_call(self, day, budget):
        with self.sessions.begin() as session:
            session.execute(
                insert(NewsUsage).values(day=day, calls=0).on_conflict_do_nothing()
            )
            return (
                session.execute(
                    text(
                        "UPDATE rag.market_news_usage SET calls=calls+1 "
                        "WHERE day=:day AND calls<:budget RETURNING calls"
                    ),
                    {"day": day, "budget": budget},
                ).scalar()
                is not None
            )

    def run_record(self, started, status, details):
        with self.sessions.begin() as session:
            session.add(
                NewsRun(
                    started_at=started,
                    finished_at=func.now(),
                    status=status,
                    details=details,
                )
            )

    def save_pending(self, rows, query, now, unresolved_hours):
        with self.sessions.begin() as session:
            for item in rows:
                row = session.scalar(
                    select(MarketNews).where(MarketNews.url == item["url"])
                )
                if row:
                    row.last_seen_at = now
                    row.search_queries = list(
                        dict.fromkeys([*row.search_queries, query])
                    )[-30:]
                    if (
                        row.title != item["title"]
                        or row.classification_status == "LEGACY"
                    ):
                        row.title, row.original_title = (
                            item["title"],
                            item["original_title"],
                        )
                        row.published_at, row.original_url = (
                            item["published_at"],
                            item.get("original_url"),
                        )
                        row.classification_status, row.index_status = (
                            "PENDING",
                            "PENDING",
                        )
                        row.company_codes, row.company_names = [], []
                        row.market_wide, row.scope = False, "UNRESOLVED"
                        row.embedding, row.attempts, row.next_retry_at = None, 0, None
                    continue
                session.add(
                    MarketNews(
                        **item,
                        company_codes=[],
                        company_names=[],
                        market_wide=False,
                        classification_reason="분류 대기",
                        classifier_version="pending",
                        first_seen_at=now,
                        classified_at=now,
                        last_seen_at=now,
                        search_queries=[query],
                        classification_status="PENDING",
                        scope="UNRESOLVED",
                        expires_at=now + timedelta(hours=unresolved_hours),
                    )
                )

    def pending(self, now, max_attempts, limit, policy, retry=False):
        with self.sessions() as session:
            rows = session.scalars(
                select(MarketNews)
                .where(
                    MarketNews.expires_at > now,
                    MarketNews.classification_status != "LEGACY",
                    MarketNews.published_at.is_not(None),
                    or_(
                        MarketNews.classification_status.in_(
                            ["PENDING", "FAILED", "UNRESOLVED"]
                        ),
                        MarketNews.policy_version != policy,
                    ),
                    or_(MarketNews.attempts < max_attempts, retry),
                    or_(
                        MarketNews.next_retry_at.is_(None),
                        MarketNews.next_retry_at <= now,
                        retry,
                    ),
                )
                .order_by(MarketNews.first_seen_at, MarketNews.id)
                .limit(limit)
            )
            return [{**self.item(r), "attempts": r.attempts} for r in rows]

    def classified(self, item, tag, method, version, policy, now, settings):
        with self.sessions.begin() as session:
            row = session.get(MarketNews, uuid.UUID(item["id"]))
            if row is None or row.title != item["title"]:
                return
            for key, value in tag.items():
                setattr(row, key, value)
            row.classification_status = (
                "UNRESOLVED" if tag["scope"] == "UNRESOLVED" else "CLASSIFIED"
            )
            row.classification_method, row.classifier_version, row.policy_version = (
                method,
                version,
                policy,
            )
            row.classified_at, row.attempts, row.last_error = (
                now,
                row.attempts + 1,
                None,
            )
            row.next_retry_at = (
                now + timedelta(hours=1)
                if row.classification_status == "UNRESOLVED"
                else None
            )
            age = (
                timedelta(hours=settings.news_unresolved_retention_hours)
                if tag["scope"] == "UNRESOLVED"
                else timedelta(
                    days=settings.news_important_retention_days
                    if tag["importance"] == "HIGH"
                    else settings.news_retention_days
                )
            )
            row.expires_at = min(row.first_seen_at, row.published_at) + age
            row.index_status = (
                "READY"
                if row.embedding is not None
                else "PENDING"
                if settings.news_embedding_enabled
                else "METADATA_READY"
            )

    def classification_failed(self, items, now, error):
        with self.sessions.begin() as session:
            for item in items:
                row = session.get(MarketNews, uuid.UUID(item["id"]))
                if row and row.title == item["title"]:
                    row.classification_status, row.last_error = "FAILED", error
                    row.attempts += 1
                    row.next_retry_at = now + timedelta(
                        minutes=min(60, 5 * 2**row.attempts)
                    )

    def unindexed(self, limit):
        with self.sessions() as session:
            return [
                self.item(r)
                for r in session.scalars(
                    select(MarketNews)
                    .where(
                        MarketNews.classification_status == "CLASSIFIED",
                        MarketNews.index_status.in_(["PENDING", "FAILED"]),
                    )
                    .order_by(MarketNews.first_seen_at)
                    .limit(limit)
                )
            ]

    def indexed(self, item, vector=None, error=None):
        with self.sessions.begin() as session:
            row = session.get(MarketNews, uuid.UUID(item["id"]))
            if row and row.title == item["title"]:
                row.embedding, row.index_status, row.last_error = (
                    vector,
                    "FAILED" if error else "READY",
                    error,
                )

    def cleanup(self, now, settings, dry_run=True):
        # ponytail: 행 크기 합계로 활성 데이터량을 제한합니다. 물리 디스크 한도는 PostgreSQL 운영 모니터링으로 관리합니다.
        with self.sessions.begin() as session:
            rows = list(
                session.execute(
                    text(
                        "SELECT id, expires_at, classification_status, importance, "
                        "pg_column_size(market_news) AS bytes FROM rag.market_news ORDER BY "
                        "(expires_at<=:now) DESC, (classification_status IN ('FAILED','UNRESOLVED','LEGACY')) DESC, "
                        "(importance='HIGH'), published_at NULLS FIRST, first_seen_at, id"
                    ),
                    {"now": now},
                ).mappings()
            )
            count, size, ids = len(rows), sum(r["bytes"] for r in rows), []
            for row in rows:
                if (
                    row["expires_at"] <= now
                    or count > settings.news_max_articles
                    or size > settings.news_max_storage_bytes
                ):
                    ids.append(row["id"])
                    count -= 1
                    size -= row["bytes"]
            if not dry_run:
                if ids:
                    session.execute(delete(MarketNews).where(MarketNews.id.in_(ids)))
                session.execute(
                    delete(NewsRun).where(
                        NewsRun.started_at
                        < now - timedelta(days=settings.news_log_retention_days)
                    )
                )
                session.execute(
                    delete(NewsQuery).where(
                        NewsQuery.last_checked_at
                        < now - timedelta(days=settings.news_log_retention_days)
                    )
                )
                session.execute(
                    delete(NewsUsage).where(
                        NewsUsage.day
                        < (now - timedelta(days=settings.news_log_retention_days))
                        .date()
                        .isoformat()
                    )
                )
            return {
                "dry_run": dry_run,
                "delete_count": len(ids),
                "remaining_count": count,
                "remaining_logical_bytes": size,
                "sample_ids": [str(i) for i in ids[:20]],
            }

    @staticmethod
    def scope(
        corp_code,
        company_name,
        as_of,
        days,
        now,
        scopes=None,
        topics=None,
        industries=None,
    ):
        relevant = [
            MarketNews.company_codes.contains([corp_code]) if corp_code else False,
            MarketNews.scope == "MACRO",
        ]
        relevant.extend(
            MarketNews.industry_tags.contains([tag]) for tag in (industries or [])
        )
        if topics:
            relevant.append(
                and_(
                    MarketNews.scope == "INDUSTRY",
                    or_(*(MarketNews.topic_tags.contains([tag]) for tag in topics)),
                )
            )
        filters = [
            or_(*relevant),
            MarketNews.classification_status == "CLASSIFIED",
            MarketNews.first_seen_at <= as_of,
            MarketNews.classified_at <= as_of,
            MarketNews.published_at <= as_of,
            MarketNews.published_at >= as_of - timedelta(days=days),
            MarketNews.expires_at > now,
        ]
        if scopes:
            filters.append(MarketNews.scope.in_(scopes))
        if topics:
            filters.append(
                or_(*(MarketNews.topic_tags.contains([tag]) for tag in topics))
            )
        return filters

    @staticmethod
    def item(row):
        return {
            "id": str(row.id),
            "title": row.title,
            "original_title": row.original_title,
            "url": row.url,
            "original_url": row.original_url,
            "company_codes": row.company_codes,
            "company_names": row.company_names,
            "market_wide": row.market_wide,
            "scope": row.scope,
            "industry_tags": row.industry_tags,
            "topic_tags": row.topic_tags,
            "classification_status": row.classification_status,
            "classification_reason": row.classification_reason,
            "classification_method": row.classification_method,
            "policy_version": row.policy_version,
            "uncertainty": row.uncertainty,
            "confidence": row.confidence,
            "importance": row.importance,
            "index_status": row.index_status,
            "first_seen_at": row.first_seen_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(),
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "expires_at": row.expires_at.isoformat(),
            "search_queries": row.search_queries,
            "title_only": True,
            "provider": "NAVER_SEARCH",
        }

    def search(
        self,
        corp_code,
        company_name,
        as_of,
        days,
        vector,
        limit,
        query="",
        scopes=None,
        topics=None,
        industries=None,
        now=None,
    ):
        from datetime import timezone

        now = now or datetime.now(timezone.utc)
        with self.sessions() as session:
            # 제목은 짧아 전문 검색 서버 없이 PostgreSQL의 단어 일치와 선택적 벡터를 합칩니다.
            words = list(dict.fromkeys(query.split()))[:12]
            lexical = sum(
                (func.strpos(func.lower(MarketNews.title), w.lower()) > 0).cast(Integer)
                for w in words
            )
            recent = func.extract("epoch", MarketNews.published_at) / 86400 / 30
            score = lexical * 2 + recent
            if vector is not None:
                score = score + func.coalesce(
                    1 - MarketNews.embedding.cosine_distance(vector), 0
                )
            rows = session.scalars(
                select(MarketNews)
                .where(
                    *self.scope(
                        corp_code,
                        company_name,
                        as_of,
                        days,
                        now,
                        scopes,
                        topics,
                        industries,
                    )
                )
                .order_by(score.desc(), MarketNews.published_at.desc(), MarketNews.id)
                .limit(limit)
            )
            return [self.item(row) for row in rows]

    def articles(
        self, identifiers, corp_code, company_name, as_of, days, industries=None
    ):
        from datetime import timezone

        with self.sessions() as session:
            return [
                self.item(row)
                for row in session.scalars(
                    select(MarketNews).where(
                        MarketNews.id.in_(identifiers),
                        *self.scope(
                            corp_code,
                            company_name,
                            as_of,
                            days,
                            datetime.now(timezone.utc),
                            industries=industries,
                        ),
                    )
                )
            ]

    def status(self):
        with self.sessions() as session:
            row = session.get(NewsCollection, 1)
            return (
                {
                    "status": row.status,
                    "started_at": row.started_at.isoformat(),
                    "finished_at": row.finished_at.isoformat()
                    if row.finished_at
                    else None,
                    "details": row.details,
                }
                if row
                else {"status": "NOT_STARTED"}
            )
