from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.domain.analysis_state_machine import advance_analysis_stage, transition_analysis
from app.models import (
    AnalysisEvent, AnalysisPerspectiveTask, AnalysisReport, AnalysisTask, AuditLog,
    Filing, FilingVersion, MemoVersion, RevisionProposal,
)
from app.models.enums import AnalysisStage as G, AnalysisStatus as S, ImpactType, PerspectiveStatus, PerspectiveType
from app.repositories import (
    AnalysisEventRepository, AnalysisReportRepository, AnalysisRepository,
    AuditLogRepository, FilingRepository, MemoRepository, PerspectiveTaskRepository,
    RevisionRepository, UserRepository,
)
from test_domain import db, graph, migrated_engine

pytestmark = pytest.mark.postgres


def new_task(graph, **changes):
    values = dict(requested_by=graph.user.id, memo_id=graph.memo.id, base_memo_version=1, disclosure_receipt_no="new-receipt", company_name_snapshot="Example", thread_id=str(uuid4()))
    values.update(changes)
    return AnalysisTask(**values)


def new_perspective(graph, **changes):
    values = dict(analysis_task_id=graph.task.id, perspective_type=PerspectiveType.FINANCE, selection_reason="Reason", question="Question", max_tool_calls=2, timeout_seconds=30)
    values.update(changes)
    return AnalysisPerspectiveTask(**values)


def test_user_queries(db, graph):
    repo = UserRepository(db)
    assert repo.get_by_id(graph.user.id) is graph.user
    assert repo.get_by_email(graph.user.email) is graph.user
    assert repo.get_by_email("absent@example.test") is None
    assert repo.get_by_id(uuid4()) is None


def test_memo_current_version_and_version_history(db, graph):
    repo = MemoRepository(db)
    version2 = MemoVersion(memo_id=graph.memo.id, version=2, content="New", created_by=graph.user.id)
    db.add(version2)
    graph.memo.current_version = 2
    db.flush()
    assert repo.get_by_id(graph.memo.id) is graph.memo
    assert repo.get_by_id(graph.memo.id, for_update=True) is graph.memo
    assert repo.get_current_version(graph.memo.id, for_update=True) == 2
    assert graph.task.base_memo_version == 1
    assert repo.get_version(graph.memo.id, 1) is graph.version
    assert repo.get_version(graph.memo.id, 2) is version2
    assert repo.get_version(graph.memo.id, 999) is None
    assert repo.list_versions(graph.memo.id) == [graph.version, version2]
    assert repo.get_current_version(uuid4()) is None


def test_filing_receipt_is_global_unique_and_cache_can_be_absent(db, graph):
    repo = FilingRepository(db)
    db.add_all([FilingVersion(filing_id=graph.filing.id, version=2, raw_content="second", content_hash="hash2"),
        FilingVersion(filing_id=graph.filing.id, version=1, raw_content="first", content_hash="hash1")])
    db.flush()
    assert repo.get_by_id(graph.filing.id) is graph.filing
    assert repo.list_by_receipt_no(graph.filing.receipt_no) == [graph.filing]
    assert repo.get_by_receipt_no(graph.filing.receipt_no) is graph.filing
    assert repo.get_by_receipt_no("absent") is None
    assert repo.get_latest_version(graph.filing.id).version == 2
    assert repo.get_latest_version(uuid4()) is None


def test_analysis_add_get_and_company_list(db, graph):
    repo = AnalysisRepository(db)
    other = repo.add(new_task(graph))
    assert repo.get_by_id(other.id) is other
    assert repo.get_by_thread_id(other.thread_id) is other
    assert set(repo.list_all()) == {graph.task, other}
    assert repo.get_by_id(uuid4()) is None
    assert repo.get_by_thread_id("missing") is None


@pytest.mark.parametrize("status", list(S))
def test_active_duplicate_statuses(db, graph, status):
    repo = AnalysisRepository(db)
    graph.task.status = status
    db.flush()
    found = repo.find_active_duplicate(graph.memo.id, 1, graph.task.disclosure_receipt_no)
    if status in (S.CREATED, S.QUEUED, S.RUNNING, S.SAVING, S.SAVE_FAILED):
        assert found is graph.task
    else:
        assert found is None


@pytest.mark.parametrize("field,value", [("memo_id", uuid4()), ("base_memo_version", 2), ("disclosure_receipt_no", "other-receipt")])
def test_duplicate_requires_all_three_input_keys(db, graph, field, value):
    values = dict(memo_id=graph.memo.id, base_memo_version=1, disclosure_receipt_no=graph.task.disclosure_receipt_no)
    values[field] = value
    assert AnalysisRepository(db).find_active_duplicate(**values) is None


def test_locked_get_refreshes_cached_analysis_and_memo(db, graph):
    # A cached identity must not conceal a database change when used for transition locking.
    db.execute(text("UPDATE core.analysis_tasks SET status='QUEUED' WHERE id=:id"), {"id": graph.task.id})
    db.execute(text("UPDATE core.memos SET title='Updated in SQL' WHERE id=:id"), {"id": graph.memo.id})
    assert graph.task.status is S.CREATED
    assert graph.memo.title == "Memo"
    assert AnalysisRepository(db).get_by_id(graph.task.id, for_update=True).status is S.QUEUED
    assert MemoRepository(db).get_by_id(graph.memo.id, for_update=True).title == "Updated in SQL"


@pytest.mark.parametrize("status", list(PerspectiveStatus))
def test_perspective_get_type_list_and_active_filter(db, graph, status):
    repo = PerspectiveTaskRepository(db)
    item = repo.add(new_perspective(graph, status=status))
    assert repo.get_by_id(item.id) is item
    assert repo.get_by_analysis_task_and_type(graph.task.id, PerspectiveType.FINANCE) is item
    assert repo.get_by_analysis_task_and_type(graph.task.id, PerspectiveType.FX_HEDGE) is None
    assert repo.list_by_analysis_task(graph.task.id) == [item]
    assert repo.list_by_analysis_task(uuid4()) == []
    expected = [item] if status in (PerspectiveStatus.REGISTERED, PerspectiveStatus.RUNNING) else []
    assert repo.list_active_by_analysis_task(graph.task.id) == expected
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            repo.add(new_perspective(graph))


def test_revision_queries_have_no_approval_dependency(db, graph):
    repo = RevisionRepository(db)
    item = repo.add(RevisionProposal(analysis_task_id=graph.task.id, claim_id="claim-2", impact_type=ImpactType.FACT_UPDATE, before_text="old", after_text="new", reason="Evidence"))
    assert repo.get_by_id(item.id) is item
    assert set(repo.list_by_analysis_task(graph.task.id)) == {graph.proposal, item}
    assert repo.list_by_analysis_task(uuid4()) == []
    assert repo.get_by_id(uuid4()) is None


def test_report_get_exists_and_unique_constraint(db, graph):
    repo = AnalysisReportRepository(db)
    assert repo.get_by_analysis_task(graph.task.id) is None
    assert not repo.exists_by_analysis_task(graph.task.id)
    item = repo.add(AnalysisReport(analysis_task_id=graph.task.id, content="report", generated_at=datetime.now(timezone.utc)))
    assert repo.get_by_id(item.id) is item
    assert repo.get_by_analysis_task(graph.task.id) is item
    assert repo.exists_by_analysis_task(graph.task.id)
    assert not repo.exists_by_analysis_task(uuid4())
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            repo.add(AnalysisReport(analysis_task_id=graph.task.id, content="duplicate", generated_at=datetime.now(timezone.utc)))
    assert item.content == "report"


def test_events_order_and_latest_sequence_do_not_allocate_sequence(db, graph):
    repo = AnalysisEventRepository(db)
    assert repo.get_latest_sequence(graph.task.id) == 0
    for sequence in (3, 1, 2):
        repo.add(AnalysisEvent(analysis_task_id=graph.task.id, sequence=sequence, event_type="test"))
    assert [item.sequence for item in repo.list_by_analysis_task(graph.task.id)] == [1, 2, 3]
    assert repo.get_latest_sequence(graph.task.id) == 3
    assert repo.get_latest_sequence(graph.task.id) == 3
    assert repo.list_by_analysis_task(uuid4()) == []
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            repo.add(AnalysisEvent(analysis_task_id=graph.task.id, sequence=3, event_type="duplicate"))


def test_audit_resource_lookup_is_company_wide(db, graph):
    repo = AuditLogRepository(db)
    item = repo.add(AuditLog(user_id=graph.user.id, action="request", resource_type="analysis", resource_id=str(graph.task.id)))
    repo.add(AuditLog(user_id=graph.user.id, action="other", resource_type="memo", resource_id=str(graph.task.id)))
    assert repo.list_by_resource("analysis", str(graph.task.id)) == [item]
    assert repo.list_by_resource("analysis", "missing") == []
    assert not hasattr(repo, "delete") and not hasattr(repo, "update")


@pytest.mark.parametrize("kind", ["analysis", "perspective", "revision", "report", "event", "audit"])
def test_add_only_flushes_and_caller_can_rollback(db, graph, migrated_engine, kind):
    if kind == "analysis":
        repo, item = AnalysisRepository(db), new_task(graph)
    elif kind == "perspective":
        repo, item = PerspectiveTaskRepository(db), new_perspective(graph)
    elif kind == "revision":
        repo, item = RevisionRepository(db), RevisionProposal(analysis_task_id=graph.task.id, claim_id="rollback", impact_type=ImpactType.HOLD, before_text="before", reason="reason")
    elif kind == "report":
        repo, item = AnalysisReportRepository(db), AnalysisReport(analysis_task_id=graph.task.id, content="rollback", generated_at=datetime.now(timezone.utc))
    elif kind == "event":
        repo, item = AnalysisEventRepository(db), AnalysisEvent(analysis_task_id=graph.task.id, sequence=1, event_type="rollback")
    else:
        repo, item = AuditLogRepository(db), AuditLog(user_id=graph.user.id, action="rollback", resource_type="task", resource_id=str(graph.task.id))
    nested = db.begin_nested()
    assert repo.add(item) is item
    key = item.id
    assert db.get(type(item), key) is item
    with migrated_engine.connect() as observer:
        assert observer.execute(select(type(item).id).where(type(item).id == key)).scalar_one_or_none() is None
    nested.rollback()
    assert db.get(type(item), key) is None
    assert db.is_active
    assert db.get(type(graph.user), graph.user.id) is graph.user


def test_state_machine_changes_persist_via_caller_flush(db, graph):
    item = graph.task
    transition_analysis(item, S.QUEUED)
    transition_analysis(item, S.RUNNING)
    for stage in (G.INPUT_COLLECTION, G.REPORT_GENERATION, G.REPORT_SAVE):
        advance_analysis_stage(item, stage)
    start = item.started_at
    transition_analysis(item, S.SAVE_FAILED)
    transition_analysis(item, S.SAVING)
    item.has_warnings = True
    transition_analysis(item, S.COMPLETED_WITH_WARNINGS)
    db.flush()
    db.expire(item)
    found = AnalysisRepository(db).get_by_id(item.id)
    assert found.status is S.COMPLETED_WITH_WARNINGS
    assert found.current_stage is G.REPORT_SAVE
    assert found.started_at == start
    assert found.completed_at.utcoffset() is not None
