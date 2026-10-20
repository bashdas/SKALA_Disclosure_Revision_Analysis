from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """All future Business API ORM models must inherit this base."""


class DatabaseConfigurationError(ValueError):
    pass


def get_database_url() -> URL:
    try:
        url = make_url(get_settings().database_url)
    except ArgumentError:
        raise DatabaseConfigurationError("DATABASE_URL must be a PostgreSQL psycopg URL") from None
    if url.drivername != "postgresql+psycopg":
        raise DatabaseConfigurationError("DATABASE_URL must use postgresql+psycopg")
    return url


@lru_cache
def get_engine() -> Engine:
    # Lazy creation preserves process liveness even when the database is unavailable.
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={"connect_timeout": get_settings().database_connect_timeout},
        hide_parameters=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """One session per request; Service owns commit/rollback or session.begin().

    Closing rolls back any unfinished transaction, including failed requests.
    No automatic commit occurs when the dependency exits successfully.
    """
    with get_session_factory()() as session:
        yield session
