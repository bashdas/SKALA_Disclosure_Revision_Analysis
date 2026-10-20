import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, configure_mappers

from app.core.config import get_settings
from app.core.database import Base
from app.models import (
    AnalysisEvent, AnalysisPerspectiveTask, AnalysisReport, AnalysisTask, AuditLog, Contract,
    Filing, FilingVersion, Memo, MemoVersion, Organization,
    RevisionProposal, User,
)
from app.models.enums import AnalysisStatus, ImpactType, UserRole, ValidationStatus

ROOT = Path(__file__).resolve().parents[1]


def test_model_metadata_and_delete_policy():
    configure_mappers()
    assert len(Base.metadata.tables) == 13
    for table in Base.metadata.tables.values():
        assert table.schema == "core"
        for fk in table.foreign_keys:
            assert fk.ondelete == "RESTRICT"
        for column in table.columns:
            if column.name.endswith("_at"):
                assert column.type.timezone
    for mapper in Base.registry.mappers:
        for relation in mapper.relationships:
            assert not relation.cascade.delete
            assert not relation.cascade.delete_orphan
            assert relation.passive_deletes == "all"
    assert "password" not in User.__table__.columns


@pytest.fixture(scope="module")
def migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL model tests")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", url)
        get_settings.cache_clear()
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        get_settings.cache_clear()
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine):
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection) as session:
            yield session
        transaction.rollback()


@pytest.fixture
def graph(db):
    org = Organization(name="Example organization")
    db.add(org)
    db.flush()
    user = User(organization_id=org.id, email="analyst@example.test", password_hash="test-hash", role=UserRole.ANALYST)
    filing = Filing(organization_id=org.id, company_name="Example", receipt_no="202610200001", filing_type="contract", filed_at=datetime.now(timezone.utc))
    memo = Memo(organization_id=org.id, company_name="Example", title="Memo")
    db.add_all([user, filing, memo])
    db.flush()
    version = MemoVersion(memo_id=memo.id, version=1, content="original", created_by=user.id)
    task = AnalysisTask(organization_id=org.id, requested_by=user.id, memo_id=memo.id, base_memo_version=1, thread_id=str(uuid4()), disclosure_receipt_no="202610200001", company_name_snapshot="Example")
    db.add_all([version, task])
    db.flush()
    proposal = RevisionProposal(analysis_task_id=task.id, claim_id="claim-1", impact_type=ImpactType.HOLD, before_text="before", after_text=None, reason="review", evidence_json={"sources": [{"page": 1}]})
    db.add(proposal)
    db.flush()
    return SimpleNamespace(org=org, user=user, filing=filing, memo=memo, version=version, task=task, proposal=proposal)


def rejected(db, instance, constraint):
    with pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            db.add(instance)
            db.flush()
    assert error.value.orig.diag.constraint_name == constraint


@pytest.mark.postgres
def test_organization_and_relationships(db, graph):
    db.expire_all()
    assert graph.org.name == "Example organization"
    assert graph.user in graph.org.users
    assert graph.filing in graph.org.filings
    assert graph.memo in graph.org.memos
    assert graph.task in graph.org.analysis_tasks
    assert graph.version in graph.memo.memo_versions
    assert graph.proposal in graph.task.revision_proposals
    assert graph.user.role is UserRole.ANALYST
    assert graph.task.status is AnalysisStatus.CREATED
    assert graph.proposal.validation_status is ValidationStatus.PENDING
    assert graph.memo.current_version == 1
    assert graph.org.created_at.utcoffset() is not None
    assert graph.task.created_at.utcoffset() is not None
    assert graph.task.updated_at.utcoffset() is not None


@pytest.mark.postgres
def test_user_email_unique(db, graph):
    rejected(db, User(organization_id=graph.org.id, email=graph.user.email, password_hash="hash", role=UserRole.RA), "uq_users_email")


@pytest.mark.postgres
def test_filing_receipt_unique_per_organization(db, graph):
    rejected(db, Filing(organization_id=graph.org.id, company_name="Other", receipt_no=graph.filing.receipt_no, filing_type="contract", filed_at=datetime.now(timezone.utc)), "uq_filings_organization_receipt")
    other = Organization(name="Other org")
    db.add(other)
    db.flush()
    db.add(Filing(organization_id=other.id, company_name="Other", receipt_no=graph.filing.receipt_no, filing_type="contract", filed_at=datetime.now(timezone.utc)))
    db.flush()


@pytest.mark.postgres
def test_filing_version_constraints(db, graph):
    db.add(FilingVersion(filing_id=graph.filing.id, version=1, raw_content="raw", content_hash="hash"))
    db.flush()
    rejected(db, FilingVersion(filing_id=graph.filing.id, version=1, raw_content="raw", content_hash="hash"), "uq_filing_versions_filing_version")
    rejected(db, FilingVersion(filing_id=graph.filing.id, version=0, raw_content="raw", content_hash="hash"), "ck_filing_versions_version_positive")


@pytest.mark.postgres
def test_memo_versions_and_current_version(db, graph):
    rejected(db, Memo(organization_id=graph.org.id, company_name="Example", title="bad", current_version=0), "ck_memos_current_version_positive")
    rejected(db, MemoVersion(memo_id=graph.memo.id, version=1, content="duplicate", created_by=graph.user.id), "uq_memo_versions_memo_version")
    rejected(db, MemoVersion(memo_id=graph.memo.id, version=0, content="bad", created_by=graph.user.id), "ck_memo_versions_version_positive")


@pytest.mark.postgres
def test_contract_decimal_and_dates(db, graph):
    contract = Contract(filing_id=graph.filing.id, contract_name="Contract", amount=Decimal("12345678901234567890.1234"), start_date=date(2026, 1, 1))
    db.add(contract)
    db.flush()
    db.expire(contract)
    assert isinstance(contract.amount, Decimal)
    assert contract.amount == Decimal("12345678901234567890.1234")
    assert contract.start_date == date(2026, 1, 1)
    assert contract.end_date is None


@pytest.mark.postgres
def test_task_version_and_thread_unique(db, graph):
    values = dict(organization_id=graph.org.id, requested_by=graph.user.id, filing_id=graph.filing.id, memo_id=graph.memo.id, disclosure_receipt_no="202610200001", company_name_snapshot="Example")
    rejected(db, AnalysisTask(**values, base_memo_version=0, thread_id=str(uuid4())), "ck_analysis_tasks_base_version_positive")
    rejected(db, AnalysisTask(**values, base_memo_version=1, thread_id=graph.task.thread_id), "uq_analysis_tasks_thread_id")

@pytest.mark.postgres
def test_event_sequence_and_jsonb(db, graph):
    event = AnalysisEvent(analysis_task_id=graph.task.id, sequence=1, event_type="created", payload_json={"status": "CREATED", "values": [1, True, None]})
    audit = AuditLog(organization_id=graph.org.id, user_id=graph.user.id, action="test", resource_type="task", resource_id=str(graph.task.id), metadata_json={"nested": {"value": 1}})
    db.add_all([event, audit])
    db.flush()
    rejected(db, AnalysisEvent(analysis_task_id=graph.task.id, sequence=1, event_type="duplicate"), "uq_analysis_events_task_sequence")
    rejected(db, AnalysisEvent(analysis_task_id=graph.task.id, sequence=0, event_type="bad"), "ck_analysis_events_sequence_positive")
    db.expire_all()
    assert event.payload_json["values"] == [1, True, None]
    assert audit.metadata_json == {"nested": {"value": 1}}
    assert graph.proposal.evidence_json == {"sources": [{"page": 1}]}
    assert graph.proposal.after_text is None
    assert graph.task.analysis_events == [event]
    assert db.execute(text("SELECT jsonb_typeof(payload_json) FROM core.analysis_events WHERE id=:id"), {"id": event.id}).scalar_one() == "object"

@pytest.mark.postgres
@pytest.mark.parametrize("parent", ["org", "user", "memo", "task"])
def test_loaded_parent_delete_preserves_history(db, graph, parent):
    # Load collections so the ORM must also obey the non-cascading policy.
    list(graph.org.users)
    list(graph.org.filings)
    list(graph.org.memos)
    list(graph.org.analysis_tasks)
    list(graph.memo.memo_versions)
    list(graph.task.revision_proposals)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(getattr(graph, parent))
            db.flush()
    assert db.get(MemoVersion, graph.version.id) is not None
    assert db.get(AnalysisTask, graph.task.id) is not None


@pytest.mark.postgres
def test_enum_checks_reject_raw_sql(db, graph):
    for table, column in [("users", "role"), ("analysis_tasks", "status"), ("revision_proposals", "impact_type"), ("revision_proposals", "validation_status")]:
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.execute(text(f"UPDATE core.{table} SET {column}='BAD'"))


@pytest.mark.postgres
def test_audit_prevents_user_deletion(db, graph):
    # Independent user is referenced only by audit history.
    user = User(organization_id=graph.org.id, email="audit-only@example.test", password_hash="hash", role=UserRole.RA)
    db.add(user)
    db.flush()
    audit = AuditLog(organization_id=graph.org.id, user_id=user.id, action="test", resource_type="user", resource_id=str(user.id))
    db.add(audit)
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(user)
            db.flush()
    assert db.get(AuditLog, audit.id) is not None


@pytest.mark.postgres
def test_foreign_key_and_required_fields(db, graph):
    with pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            db.add(User(organization_id=uuid4(), email="missing-org@example.test", password_hash="hash", role=UserRole.RA))
            db.flush()
    assert error.value.orig.sqlstate == "23503"
    with pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            db.add(AnalysisReport(analysis_task_id=graph.task.id, content=None, generated_at=datetime.now(timezone.utc)))
            db.flush()
    assert error.value.orig.sqlstate == "23502"
