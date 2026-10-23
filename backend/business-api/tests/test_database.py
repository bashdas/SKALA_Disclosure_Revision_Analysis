import os
import runpy
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic import command, context
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import (
    Base, DatabaseConfigurationError, get_database_url, get_db,
    get_engine, get_session_factory,
)
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_database_url_environment(monkeypatch):
    url = "postgresql+psycopg://example:example@postgres:5432/disclosure"
    monkeypatch.setenv("DATABASE_URL", url)
    assert Settings().database_url == url
    assert "example:example" not in repr(Settings())
    assert get_database_url().drivername == "postgresql+psycopg"


@pytest.mark.parametrize("url", ["", "invalid", "sqlite://", "postgresql+asyncpg://u:p@localhost/db"])
def test_invalid_database_configuration(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(DatabaseConfigurationError):
        get_database_url()


def test_session_factory_without_connection(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    with get_session_factory()() as session:
        assert isinstance(session, Session)
        assert session.bind is get_engine()
        assert not session.in_transaction()


def test_dependency_closes_without_automatic_commit(monkeypatch):
    session = MagicMock()
    session.__enter__.return_value = session
    monkeypatch.setattr("app.core.database.get_session_factory", lambda: lambda: session)
    test_app = FastAPI()

    @test_app.get("/session")
    def endpoint(db=Depends(get_db)):
        assert db is session
        return {"ok": True}

    with TestClient(test_app) as client:
        assert client.get("/session").status_code == 200
    session.__exit__.assert_called_once()
    session.commit.assert_not_called()


def test_db_health_unconfigured_and_liveness():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/health/db")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}


def test_unreachable_database_fails_safely(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused:secret-value@127.0.0.1:1/unused")
    with get_session_factory()() as session:
        with pytest.raises(OperationalError):
            session.execute(text("SELECT 1"))
    with TestClient(app) as client:
        response = client.get("/health/db")
        assert response.status_code == 503
        assert "secret-value" not in response.text


def test_alembic_uses_application_metadata(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example:p%25ss@postgres/disclosure")
    configure = MagicMock()
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(context, "configure", configure)
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    monkeypatch.setattr(context, "run_migrations", MagicMock())
    runpy.run_path(str(ROOT / "alembic/env.py"))
    assert configure.call_args.kwargs["target_metadata"] is Base.metadata
    assert "core.organizations" not in Base.metadata.tables


@pytest.fixture
def postgres_url(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for real PostgreSQL tests")
    monkeypatch.setenv("DATABASE_URL", url)
    return url


@pytest.mark.postgres
def test_postgres_connection_and_health(postgres_url):
    with get_session_factory()() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        assert session.execute(text("SELECT version()")).scalar_one().startswith("PostgreSQL")
    with TestClient(app) as client:
        response = client.get("/health/db")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "business-api-db"}


@pytest.mark.postgres
def test_postgres_dependency_rolls_back_on_success_and_failure(postgres_url):
    # A transaction-local setting tests rollback without creating any tables.
    for fail in (False, True):
        dependency = get_db()
        session = next(dependency)
        session.execute(text("SET LOCAL application_name = 'uncommitted-test'"))
        transaction = session.get_transaction()
        if fail:
            with pytest.raises(RuntimeError, match="service failure"):
                dependency.throw(RuntimeError("service failure"))
        else:
            dependency.close()
        assert not transaction.is_active
        assert not session.in_transaction()


@pytest.mark.postgres
def test_postgres_bad_credentials(postgres_url):
    url = get_database_url().set(password="intentionally-wrong-test-password")
    engine = create_engine(url, connect_args={"connect_timeout": 2}, hide_parameters=True)
    try:
        with pytest.raises(OperationalError):
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_alembic_online_check(postgres_url):
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.current(config)
    command.check(config)
