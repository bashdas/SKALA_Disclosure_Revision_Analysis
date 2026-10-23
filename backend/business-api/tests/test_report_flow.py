from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import Base
from app.models import AnalysisPerspectiveTask, AnalysisReport, AnalysisTask, MemoVersion
from app.models.enums import AnalysisStage, AnalysisStatus, PerspectiveStatus, PerspectiveType
from test_domain import db, graph, migrated_engine, rejected  # shared PostgreSQL fixtures


def test_obsolete_models_removed():
    import app.models as models
    import app.models.enums as enums
    for name in ("Approval", "ApprovalItem", "RevisionApplication"):
        assert not hasattr(models, name)
    assert not hasattr(enums, "ApprovalStatus")
    for table in ("core.approvals", "core.approval_items", "core.revision_applications"):
        assert table not in Base.metadata.tables
    assert set(AnalysisStatus.__members__) == {
        "CREATED", "QUEUED", "RUNNING", "SAVING", "COMPLETED",
        "COMPLETED_WITH_WARNINGS", "SAVE_FAILED", "FAILED", "CANCELLED",
    }
    # Migration history intentionally retains the old schema; executable app code does not.
    app_path = Path(__file__).resolve().parents[1] / "app"
    for path in app_path.rglob("*.py"):
        code = path.read_text()
        assert not any(f"class {name}(" in code for name in ("Approval", "ApprovalItem", "RevisionApplication"))


@pytest.mark.postgres
def test_task_without_filing_and_fixed_memo_version(db, graph):
    task = graph.task
    assert task.filing_id is None
    assert task.disclosure_receipt_no == "202610200001"
    assert task.current_stage is None
    assert task.corp_code is None
    assert task.company_name_snapshot == "Example"
    assert task.has_warnings is False
    graph.memo.current_version = 2
    db.add(MemoVersion(memo_id=graph.memo.id, version=2, content="newer memo", created_by=graph.user.id))
    db.flush()
    db.expire_all()
    assert task.base_memo_version == 1
    assert graph.version.content == "original"
    assert graph.proposal.analysis_task_id == task.id


@pytest.mark.postgres
@pytest.mark.parametrize("status", list(AnalysisStatus))
def test_all_task_statuses(db, graph, status):
    graph.task.status = status
    db.flush()
    db.expire(graph.task)
    assert graph.task.status is status


@pytest.mark.postgres
@pytest.mark.parametrize("stage", list(AnalysisStage))
def test_task_stages(db, graph, stage):
    graph.task.current_stage = stage
    graph.task.error_stage = stage
    graph.task.has_warnings = True
    db.flush()
    db.expire(graph.task)
    assert graph.task.current_stage is stage
    assert graph.task.error_stage is stage
    assert graph.task.has_warnings


def perspective(task_id, **changes):
    values = dict(analysis_task_id=task_id, perspective_type=PerspectiveType.FINANCE, selection_reason="Financial impact", question="How does revenue change?", max_tool_calls=3, timeout_seconds=30)
    values.update(changes)
    return AnalysisPerspectiveTask(**values)


@pytest.mark.postgres
@pytest.mark.parametrize("kind", list(PerspectiveType))
def test_selected_perspective_and_jsonb(db, graph, kind):
    assert graph.task.perspective_tasks == []
    item = perspective(graph.task.id, perspective_type=kind)
    db.add(item)
    db.flush()
    assert item.status is PerspectiveStatus.REGISTERED
    assert item.result_json is None
    item.result_json = {"findings": [{"amount": "12.30"}], "warnings": []}
    item.status = PerspectiveStatus.COMPLETED
    db.flush()
    db.expire_all()
    assert item.result_json["findings"][0]["amount"] == "12.30"
    assert item in graph.task.perspective_tasks
    rejected(db, perspective(graph.task.id, perspective_type=kind), "uq_analysis_perspective_tasks_task_type")


@pytest.mark.postgres
@pytest.mark.parametrize("status", list(PerspectiveStatus))
def test_all_perspective_statuses(db, graph, status):
    item = perspective(graph.task.id, status=status)
    db.add(item)
    db.flush()
    db.expire(item)
    assert item.status is status


@pytest.mark.postgres
@pytest.mark.parametrize("values,constraint", [
    ({"max_tool_calls": -1}, "ck_analysis_perspective_tasks_tool_limit"),
    ({"timeout_seconds": 0}, "ck_analysis_perspective_tasks_timeout"),
])
def test_perspective_limits(db, graph, values, constraint):
    rejected(db, perspective(graph.task.id, **values), constraint)


@pytest.mark.postgres
def test_report_unique_and_memo_unchanged(db, graph):
    report = AnalysisReport(analysis_task_id=graph.task.id, content="Final report", report_json={"warnings": ["source unavailable"], "sections": [{"title": "Summary"}]}, has_warnings=True, no_additional_analysis_reason="Base analysis sufficient", generated_at=datetime.now(timezone.utc))
    db.add(report)
    db.flush()
    rejected(db, AnalysisReport(analysis_task_id=graph.task.id, content="Duplicate", generated_at=datetime.now(timezone.utc)), "uq_analysis_reports_analysis_task_id")
    db.expire_all()
    assert report.report_json["warnings"] == ["source unavailable"]
    assert report.has_warnings
    assert report.generated_at.utcoffset() is not None
    assert report.saved_at is None
    assert graph.task.report is report
    assert graph.memo.current_version == 1
    assert db.scalars(select(MemoVersion).where(MemoVersion.memo_id == graph.memo.id)).all() == [graph.version]
    assert graph.version.content == "original"


@pytest.mark.postgres
def test_unsaved_report_payload_survives_task_save_failed_state(db, graph):
    graph.task.status = AnalysisStatus.SAVE_FAILED
    graph.task.error_stage = AnalysisStage.REPORT_SAVE
    report = AnalysisReport(analysis_task_id=graph.task.id, content="Generated result", report_json={"complete": True}, generated_at=datetime.now(timezone.utc))
    db.add(report)
    db.flush()
    db.expire_all()
    assert graph.task.status is AnalysisStatus.SAVE_FAILED
    assert report.content == "Generated result"
    assert report.report_json == {"complete": True}
    assert report.saved_at is None


@pytest.mark.postgres
def test_new_children_prevent_loaded_task_deletion(db, graph):
    item = perspective(graph.task.id)
    report = AnalysisReport(analysis_task_id=graph.task.id, content="report", generated_at=datetime.now(timezone.utc))
    db.add_all([item, report])
    db.flush()
    # Use a separate task referenced only by the new children, avoiding old FK masking.
    task = AnalysisTask(requested_by=graph.user.id, memo_id=graph.memo.id, base_memo_version=1, disclosure_receipt_no="another-receipt", company_name_snapshot="Example", thread_id="new-children-only")
    db.add(task)
    db.flush()
    item.analysis_task_id = task.id
    report.analysis_task_id = task.id
    db.flush()
    assert task.perspective_tasks == [item]
    assert task.report is report
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(task)
            db.flush()
    assert db.get(AnalysisReport, report.id) is not None
    assert db.get(AnalysisPerspectiveTask, item.id) is not None


@pytest.mark.postgres
def test_new_enum_checks(db, graph):
    item = perspective(graph.task.id)
    db.add(item)
    db.flush()
    for table, column in [("analysis_tasks", "current_stage"), ("analysis_tasks", "error_stage"), ("analysis_perspective_tasks", "status"), ("analysis_perspective_tasks", "perspective_type")]:
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.execute(text(f"UPDATE core.{table} SET {column}='BAD'"))
