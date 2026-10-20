import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.database import Base


@pytest.mark.postgres
def test_upgrade_downgrade_reupgrade_and_schema_isolation(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url or os.environ.get("TEST_ALLOW_SCHEMA_RESET") != "1":
        pytest.skip("Requires disposable TEST_DATABASE_URL and TEST_ALLOW_SCHEMA_RESET=1")
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names(schema="core")) == {table.name for table in Base.metadata.tables.values()}
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA rag_migration_probe"))
            connection.execute(text("CREATE TABLE rag_migration_probe.keep_me (id integer PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE public.checkpoint_migration_probe (id integer PRIMARY KEY)"))
        try:
            # Other schema objects must not become drop operations in core autogenerate.
            command.check(config)
            command.downgrade(config, "base")
            assert "core" not in inspect(engine).get_schema_names()
            assert inspect(engine).has_table("keep_me", schema="rag_migration_probe")
            assert inspect(engine).has_table("checkpoint_migration_probe", schema="public")
            command.upgrade(config, "head")
            command.check(config)
            inspector = inspect(engine)
            assert set(inspector.get_table_names(schema="core")) == {table.name for table in Base.metadata.tables.values()}
            for table in Base.metadata.tables.values():
                assert {index["name"] for index in inspector.get_indexes(table.name, schema="core")} >= {index.name for index in table.indexes}
                assert all(fk["options"]["ondelete"] == "RESTRICT" for fk in inspector.get_foreign_keys(table.name, schema="core"))
            assert {c["name"] for c in inspector.get_check_constraints("analysis_tasks", schema="core")} >= {"ck_analysis_tasks_status", "ck_analysis_tasks_base_version_positive"}
            assert inspector.get_enums(schema="core") == []
        finally:
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE public.checkpoint_migration_probe"))
                connection.execute(text("DROP TABLE rag_migration_probe.keep_me"))
                connection.execute(text("DROP SCHEMA rag_migration_probe RESTRICT"))
    finally:
        engine.dispose()
