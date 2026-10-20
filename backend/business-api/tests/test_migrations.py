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


@pytest.fixture
def legacy_database(monkeypatch):
    """Destructive migration tests require explicit opt-in and a disposable DB."""
    from app.core.config import get_settings
    from uuid import uuid4

    url = os.environ.get("TEST_DATABASE_URL")
    if not url or os.environ.get("TEST_ALLOW_SCHEMA_RESET") != "1":
        pytest.skip("Requires disposable TEST_DATABASE_URL and TEST_ALLOW_SCHEMA_RESET=1")
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(url)
    command.downgrade(config, "base")
    command.upgrade(config, "0001_initial_core")
    ids = {key: uuid4() for key in ("org", "user", "memo", "version", "filing", "task", "proposal", "approval", "item", "application")}
    statements = [
        "INSERT INTO core.organizations (id,name) VALUES (:org,'Legacy org')",
        "INSERT INTO core.users (id,organization_id,email,password_hash,role) VALUES (:user,:org,'legacy@example.test','hash','ANALYST')",
        "INSERT INTO core.memos (id,organization_id,company_name,title) VALUES (:memo,:org,'Legacy Company','Original memo')",
        "INSERT INTO core.memo_versions (id,memo_id,version,content,created_by) VALUES (:version,:memo,1,'Original content',:user)",
        "INSERT INTO core.filings (id,organization_id,company_name,receipt_no,filing_type,filed_at) VALUES (:filing,:org,'Legacy Company','legacy-receipt','correction',now())",
        "INSERT INTO core.analysis_tasks (id,organization_id,requested_by,filing_id,memo_id,base_memo_version,thread_id,status) VALUES (:task,:org,:user,:filing,:memo,1,'legacy-thread','CREATED')",
        "INSERT INTO core.revision_proposals (id,analysis_task_id,claim_id,impact_type,before_text,reason) VALUES (:proposal,:task,'legacy-claim','HOLD','Before','Review')",
        "INSERT INTO core.approvals (id,analysis_task_id,status,approved_by) VALUES (:approval,:task,'APPROVED',:user)",
        "INSERT INTO core.approval_items (id,approval_id,revision_proposal_id,approved) VALUES (:item,:approval,:proposal,true)",
        "INSERT INTO core.revision_applications (id,analysis_task_id,approval_id,revision_proposal_id,result_memo_version) VALUES (:application,:task,:approval,:proposal,2)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), ids)
    try:
        yield engine, config, ids
    finally:
        # Empty only the explicitly opted-in disposable database, in FK dependency order.
        names = ["revision_applications", "approval_items", "approvals"] + [table.name for table in reversed(Base.metadata.sorted_tables)]
        existing = set(inspect(engine).get_table_names(schema="core"))
        with engine.begin() as connection:
            for name in names:
                if name in existing:
                    connection.execute(text(f"DELETE FROM core.{name}"))
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.postgres
def test_populated_legacy_upgrade_and_downgrade(legacy_database):
    engine, config, ids = legacy_database
    command.upgrade(config, "head")
    command.check(config)
    inspector = inspect(engine)
    assert not {"approvals", "approval_items", "revision_applications"} & set(inspector.get_table_names(schema="core"))
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM core.analysis_tasks WHERE id=:task"), ids).mappings().one()
        assert row["disclosure_receipt_no"] == "legacy-receipt"
        assert row["company_name_snapshot"] == "Legacy Company"
        assert row["corp_code"] is None
        assert row["base_memo_version"] == 1
        assert row["has_warnings"] is False
        assert connection.execute(text("SELECT content FROM core.memo_versions WHERE id=:version"), ids).scalar_one() == "Original content"
        assert connection.execute(text("SELECT count(*) FROM core.revision_proposals")).scalar_one() == 1
    # Compatible tasks can return to the old schema, but deleted approval history is not fabricated.
    command.downgrade(config, "0001_initial_core")
    assert {"approvals", "approval_items", "revision_applications"} <= set(inspect(engine).get_table_names(schema="core"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM core.approvals")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM core.analysis_tasks")).scalar_one() == 1
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.postgres
@pytest.mark.parametrize("status", ["WAITING_CONTRACT_CONFIRMATION", "WAITING_APPROVAL", "RESUME_QUEUED"])
def test_legacy_status_requires_manual_reconciliation(legacy_database, status):
    from sqlalchemy.exc import DBAPIError

    engine, config, ids = legacy_database
    with engine.begin() as connection:
        connection.execute(text("UPDATE core.analysis_tasks SET status=:status"), {"status": status})
    with pytest.raises(DBAPIError, match="Legacy analysis status requires manual reconciliation"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "0001_initial_core"
        assert connection.execute(text("SELECT status FROM core.analysis_tasks")).scalar_one() == status
        assert connection.execute(text("SELECT count(*) FROM core.approvals")).scalar_one() == 1
    assert "disclosure_receipt_no" not in {column["name"] for column in inspect(engine).get_columns("analysis_tasks", schema="core")}


@pytest.mark.postgres
@pytest.mark.parametrize("incompatibility", ["report", "perspective", "status", "missing_filing"])
def test_downgrade_guards_preserve_new_flow_data(legacy_database, incompatibility):
    from sqlalchemy.exc import DBAPIError
    from uuid import uuid4

    engine, config, ids = legacy_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        params = {"id": uuid4(), "task": ids["task"]}
        if incompatibility == "report":
            connection.execute(text("INSERT INTO core.analysis_reports (id,analysis_task_id,content,report_json,generated_at) VALUES (:id,:task,'Keep generated output',jsonb_build_object('keep',true),now())"), params)
        elif incompatibility == "perspective":
            connection.execute(text("INSERT INTO core.analysis_perspective_tasks (id,analysis_task_id,perspective_type,selection_reason,question,max_tool_calls,timeout_seconds) VALUES (:id,:task,'FINANCE','Keep reason','Question',1,10)"), params)
        elif incompatibility == "status":
            connection.execute(text("UPDATE core.analysis_tasks SET status='SAVE_FAILED'"))
        else:
            connection.execute(text("UPDATE core.analysis_tasks SET filing_id=NULL"))
    with pytest.raises(DBAPIError, match="before downgrading"):
        command.downgrade(config, "0001_initial_core")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == "0002_align_report_flow"
        if incompatibility == "report":
            assert connection.execute(text("SELECT content FROM core.analysis_reports")).scalar_one() == "Keep generated output"
        if incompatibility == "perspective":
            assert connection.execute(text("SELECT selection_reason FROM core.analysis_perspective_tasks")).scalar_one() == "Keep reason"
