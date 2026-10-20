from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.core.security import create_access_token
from app.domain.analysis_events import AnalysisEventType as E
from app.domain.internal_exceptions import InternalAPIError
from app.main import app
from app.models import AnalysisEvent, AnalysisTask, AnalysisPerspectiveTask, AnalysisReport, Memo, MemoVersion
from app.models.enums import AnalysisStatus as S, AnalysisStage as G, PerspectiveStatus as P
from app.repositories import AnalysisEventRepository, AnalysisReportRepository
from app.schemas.internal import ReportSaveRequest, PerspectiveCreateRequest, InternalStateRequest
from app.services.internal_analysis import InternalAnalysisService
from test_analysis_api import analysis_context, analysis_client, seed_task
from test_auth_security import auth_settings
from test_domain import migrated_engine

KEY = "test-only-internal-api-key-not-for-production-123456789"
REPORT = {"content": "Analysis report body", "report": {"claims": [{"text": "Summary", "sources": []}]}, "has_warnings": False}
PERSPECTIVE = {"perspective_type": "FINANCE", "selection_reason": "Financial impact", "question": "Assess impact", "max_tool_calls": 5, "timeout_seconds": 120}


@pytest.fixture
def internal_client(analysis_client, analysis_context):
    analysis_context.settings.internal_api_key = SecretStr(KEY)
    yield analysis_client


def endpoint(task_id, suffix):
    return f"/internal/analyses/{task_id}/{suffix}"


def call(client, task_id, suffix, body=None, method="POST", *, key=KEY, headers=None):
    values = {} if key is None else {"X-Internal-API-Key": key}
    values.update(headers or {})
    return client.request(method, endpoint(task_id, suffix), json=body, headers=values)


def task(context, status=S.QUEUED, stage=G.REQUEST_VALIDATION):
    task_id = seed_task(context, status)
    with context.factory() as db:
        db.get(AnalysisTask, task_id).current_stage = stage
        db.commit()
    return task_id


def workflow(context, session):
    return InternalAnalysisService(session, context.settings, sleeper=lambda _: None)


@pytest.mark.postgres
@pytest.mark.parametrize("method,suffix,body", [
    ("GET", "context", None), ("GET", "status", None),
    ("POST", "events", {"event_type": "BASE_ANALYSIS_STARTED", "payload": {}}),
    ("POST", "state", {"status": "RUNNING"}), ("POST", "perspectives", PERSPECTIVE),
    ("PATCH", "perspectives/00000000-0000-0000-0000-000000000001", {"status": "RUNNING"}),
    ("POST", "report", REPORT),
])
def test_all_internal_routes_require_key_and_not_jwt(internal_client, analysis_context, method, suffix, body):
    task_id = task(analysis_context)
    for invalid in (None, "incorrect-test-key"):
        result = call(internal_client, task_id, suffix, body, method, key=invalid)
        assert result.status_code == 401
        assert result.json()["error"]["code"] == "INTERNAL_UNAUTHENTICATED"
    jwt = create_access_token(analysis_context.users[0], settings=analysis_context.settings)
    assert call(internal_client, task_id, suffix, body, method, key=None, headers={"Authorization": "Bearer " + jwt}).status_code == 401
    assert internal_client.request(method, endpoint(task_id, suffix) + "?internal_api_key=" + KEY, json=body).status_code == 401


@pytest.mark.postgres
def test_internal_context_uses_task_version_not_current_version(internal_client, analysis_context):
    task_id = task(analysis_context)
    with analysis_context.factory() as db:
        memo = db.get(Memo, analysis_context.memos[0].id)
        memo.current_version = 4
        db.add(MemoVersion(memo_id=memo.id, version=4, content="NEW VERSION NOT TASK INPUT", created_by=analysis_context.users[0].id))
        db.commit()
    result = call(internal_client, task_id, "context", method="GET")
    assert result.status_code == 200
    data = result.json()
    assert data["memo"]["version"] == 3 and data["memo"]["content"] == "private memo body"
    assert data["memo"]["id"] == str(analysis_context.memos[0].id)
    assert data["organization_id"] == str(analysis_context.users[0].organization_id)
    assert data["requested_by"] == str(analysis_context.users[0].id)
    assert data["disclosure_receipt_no"] == "20261020000123"
    assert data["corp_code"] is None and data["company_name"] is None
    assert all(value not in result.text for value in (KEY, "password_hash", "rabbitmq_url", "NEW VERSION NOT TASK INPUT"))
    assert call(internal_client, uuid4(), "context", method="GET").status_code == 404
    # Query scope fields do not change server-bound context.
    spoof = internal_client.get(endpoint(task_id, "context") + f"?organization_id={analysis_context.users[1].organization_id}&memo_id={analysis_context.memos[1].id}", headers={"X-Internal-API-Key": KEY})
    assert spoof.json() == data


@pytest.mark.postgres
def test_context_incomplete_version_or_wrong_organization(internal_client, analysis_context):
    task_id = task(analysis_context)
    with analysis_context.factory() as db:
        db.get(AnalysisTask, task_id).base_memo_version = 9
        db.commit()
    result = call(internal_client, task_id, "context", method="GET")
    assert result.status_code == 404 and result.json()["error"]["code"] == "MEMO_VERSION_NOT_FOUND"
    with analysis_context.factory() as db:
        db.get(AnalysisTask, task_id).memo_id = analysis_context.memos[1].id
        db.commit()
    result = call(internal_client, task_id, "context", method="GET")
    assert result.status_code == 404 and result.json()["error"]["code"] == "ANALYSIS_CONTEXT_NOT_FOUND"


@pytest.mark.postgres
@pytest.mark.parametrize("status,cancelled", [(S.RUNNING, False), (S.CANCELLED, True)])
def test_internal_status(internal_client, analysis_context, status, cancelled):
    task_id = task(analysis_context, status, G.BASE_ANALYSIS)
    response = call(internal_client, task_id, "status", method="GET")
    assert response.status_code == 200
    assert response.json()["status"] == status and response.json()["cancelled"] is cancelled
    assert call(internal_client, uuid4(), "status", method="GET").status_code == 404


@pytest.mark.postgres
def test_event_append_sequence_retry_and_warning(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING)
    for expected in (1, 2):
        result = call(internal_client, task_id, "events", {"event_type": "BASE_ANALYSIS_STARTED", "payload": {"message": "Summary"}})
        assert result.status_code == 201 and result.json()["sequence"] == expected
        assert result.json()["payload"] == {"message": "Summary"}
    assert call(internal_client, task_id, "events", {"event_type": "BASE_ANALYSIS_STARTED", "sequence": 10}).status_code == 422
    assert call(internal_client, task_id, "events", {"event_type": "ANALYSIS_STARTED"}).status_code == 409
    assert call(internal_client, task_id, "events", {"event_type": "ANALYSIS_WARNING", "payload": {"code": "INSUFFICIENT_EVIDENCE"}}).status_code == 201
    assert call(internal_client, task_id, "status", method="GET").json()["has_warnings"] is True


@pytest.mark.postgres
def test_state_transitions_stage_fallback_and_error(internal_client, analysis_context):
    task_id = task(analysis_context)
    response = call(internal_client, task_id, "state", {"status": "RUNNING", "stage": "INPUT_COLLECTION"})
    assert response.status_code == 200 and response.json()["current_stage"] == "INPUT_COLLECTION"
    assert call(internal_client, task_id, "state", {"stage": "RAG_PREPARATION", "has_warnings": True}).status_code == 200
    assert call(internal_client, task_id, "state", {"stage": "REQUEST_VALIDATION"}).status_code == 409
    assert call(internal_client, task_id, "state", {"status": "CREATED"}).status_code == 409
    failed = call(internal_client, task_id, "state", {"status": "FAILED", "error_stage": "INPUT_COLLECTION", "error_code": "DISCLOSURE_FETCH_FAILED", "error_message": "Source unavailable"})
    assert failed.status_code == 200 and failed.json()["status"] == "FAILED"
    with analysis_context.factory() as db:
        row = db.get(AnalysisTask, task_id)
        assert row.error_code == "DISCLOSURE_FETCH_FAILED" and row.error_message == "Source unavailable"
        assert row.started_at is not None and row.completed_at is not None
        assert [event.event_type for event in AnalysisEventRepository(db).list_by_analysis_task(task_id)] == [E.ANALYSIS_STARTED, E.ANALYSIS_FAILED]


@pytest.mark.postgres
@pytest.mark.parametrize("status", [S.CANCELLED, S.COMPLETED, S.COMPLETED_WITH_WARNINGS, S.FAILED])
def test_terminal_stale_state_update_rejected(internal_client, analysis_context, status):
    task_id = task(analysis_context, status)
    assert call(internal_client, task_id, "state", {"status": "RUNNING"}).status_code == 409
    with analysis_context.factory() as db:
        assert db.get(AnalysisTask, task_id).status == status


@pytest.mark.postgres
def test_stage_saving_and_completion_only_via_report(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING, G.BASE_ANALYSIS)
    assert call(internal_client, task_id, "state", {"stage": "REPORT_GENERATION"}).status_code == 200
    result = call(internal_client, task_id, "state", {"stage": "REPORT_SAVE"})
    assert result.status_code == 200 and result.json()["status"] == "SAVING"
    assert call(internal_client, task_id, "state", {"status": "COMPLETED"}).status_code == 409


@pytest.mark.postgres
def test_perspective_idempotent_registration_and_result(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING, G.PERSPECTIVE_ANALYSIS)
    one = call(internal_client, task_id, "perspectives", PERSPECTIVE)
    assert one.status_code == 200 and one.json()["status"] == "REGISTERED"
    perspective_id = one.json()["perspective_id"]
    retry = call(internal_client, task_id, "perspectives", {**PERSPECTIVE, "question": "Do not overwrite"})
    assert retry.json() == one.json()
    assert call(internal_client, task_id, "perspectives/" + perspective_id, {"status": "RUNNING"}, "PATCH").status_code == 200
    result = {"claims": [{"text": "Summary"}], "sources": [{"receipt_no": "20261020000123"}]}
    assert call(internal_client, task_id, "perspectives/" + perspective_id, {"status": "COMPLETED", "result": result}, "PATCH").status_code == 200
    assert call(internal_client, task_id, "perspectives/" + perspective_id, {"status": "RUNNING"}, "PATCH").status_code == 409
    with analysis_context.factory() as db:
        row = db.get(AnalysisPerspectiveTask, UUID(perspective_id))
        assert row.result_json == result and row.question == PERSPECTIVE["question"]
        assert row.started_at is not None and row.completed_at is not None
        assert db.get(AnalysisTask, task_id).current_stage == G.PERSPECTIVE_ANALYSIS
        assert [event.event_type for event in AnalysisEventRepository(db).list_by_analysis_task(task_id)] == [E.PERSPECTIVE_SELECTED, E.PERSPECTIVE_STARTED, E.PERSPECTIVE_COMPLETED]


@pytest.mark.postgres
@pytest.mark.parametrize("target", [P.INSUFFICIENT_EVIDENCE, P.LIMIT_REACHED, P.FAILED])
def test_perspective_degraded_terminal(internal_client, analysis_context, target):
    task_id = task(analysis_context, S.RUNNING, G.PERSPECTIVE_ANALYSIS)
    perspective_id = call(internal_client, task_id, "perspectives", PERSPECTIVE).json()["perspective_id"]
    assert call(internal_client, task_id, "perspectives/" + perspective_id, {"status": "RUNNING"}, "PATCH").status_code == 200
    result = call(internal_client, task_id, "perspectives/" + perspective_id, {"status": target, "failure_code": target, "failure_message": "Evidence unavailable"}, "PATCH")
    assert result.status_code == 200 and result.json()["status"] == target
    assert call(internal_client, task_id, "status", method="GET").json()["has_warnings"] is True


@pytest.mark.postgres
def test_perspective_id_must_belong_to_task(internal_client, analysis_context):
    one = task(analysis_context, S.RUNNING)
    two = task(analysis_context, S.RUNNING)
    perspective_id = call(internal_client, one, "perspectives", PERSPECTIVE).json()["perspective_id"]
    assert call(internal_client, two, "perspectives/" + perspective_id, {"status": "RUNNING"}, "PATCH").status_code == 404


@pytest.mark.postgres
@pytest.mark.parametrize("task_warning,request_warning", [(False, False), (True, False), (False, True)])
def test_report_atomic_completion_and_immutable_retry(internal_client, analysis_context, task_warning, request_warning):
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    with analysis_context.factory() as db:
        db.get(AnalysisTask, task_id).has_warnings = task_warning
        db.commit()
    response = call(internal_client, task_id, "report", {**REPORT, "has_warnings": request_warning})
    expected_status = S.COMPLETED_WITH_WARNINGS if task_warning or request_warning else S.COMPLETED
    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected_status
    assert call(internal_client, task_id, "report", {**REPORT, "content": "Do not overwrite existing content"}).json() == response.json()
    with analysis_context.factory() as db:
        reports = list(db.scalars(select(AnalysisReport).where(AnalysisReport.analysis_task_id == task_id)))
        assert len(reports) == 1 and reports[0].content == REPORT["content"] and reports[0].report_json == REPORT["report"]
        assert reports[0].saved_at is not None
        assert db.get(AnalysisTask, task_id).status == expected_status
        assert [event.event_type for event in AnalysisEventRepository(db).list_by_analysis_task(task_id)] == [E.REPORT_SAVE_STARTED, E.REPORT_SAVED, E.ANALYSIS_COMPLETED]


@pytest.mark.postgres
@pytest.mark.parametrize("status", [S.CANCELLED, S.FAILED, S.CREATED, S.QUEUED])
def test_report_invalid_lifecycle_rejected(internal_client, analysis_context, status):
    task_id = task(analysis_context, status)
    assert call(internal_client, task_id, "report", REPORT).status_code == 409


@pytest.mark.postgres
def test_report_save_failure_retries_marks_save_failed_and_recovers(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    error = OperationalError("injected", {}, Exception("do-not-expose-db-url"))
    with patch.object(AnalysisReportRepository, "add", side_effect=error) as add:
        response = call(internal_client, task_id, "report", REPORT)
        assert response.status_code == 503 and response.json()["error"]["code"] == "REPORT_SAVE_FAILED"
        assert "do-not-expose" not in response.text
        assert add.call_count == 3
    with analysis_context.factory() as db:
        row = db.get(AnalysisTask, task_id)
        assert row.status == S.SAVE_FAILED and row.completed_at is None
        assert row.error_code == "REPORT_SAVE_FAILED"
        assert AnalysisReportRepository(db).get_by_analysis_task(task_id) is None
        assert [event.event_type for event in AnalysisEventRepository(db).list_by_analysis_task(task_id)] == [E.REPORT_SAVE_STARTED, E.REPORT_SAVE_FAILED]
    result = call(internal_client, task_id, "report", REPORT)
    assert result.status_code == 200 and result.json()["status"] == "COMPLETED"


@pytest.mark.postgres
def test_transient_report_save_error_then_success(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    original = AnalysisReportRepository.add
    attempts = []

    def add(repository, row):
        attempts.append(1)
        if len(attempts) < 3:
            raise OperationalError("injected", {}, Exception("test failure"))
        return original(repository, row)

    with patch.object(AnalysisReportRepository, "add", new=add):
        result = call(internal_client, task_id, "report", REPORT)
    assert result.status_code == 200 and len(attempts) == 3


@pytest.mark.postgres
def test_report_and_completion_rollback_if_saved_event_insert_fails(analysis_context):
    analysis_context.settings.internal_api_key = SecretStr(KEY)
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    with analysis_context.factory() as db:
        worker = workflow(analysis_context, db)
        original = worker.events.events.add

        def add(row):
            if row.event_type == E.REPORT_SAVED:
                raise RuntimeError("injected event failure")
            return original(row)

        with patch.object(worker.events.events, "add", side_effect=add):
            with pytest.raises(RuntimeError):
                worker.save_report(task_id, ReportSaveRequest(**REPORT))
        assert not db.in_transaction()
    with analysis_context.factory() as db:
        assert AnalysisReportRepository(db).get_by_analysis_task(task_id) is None
        assert db.get(AnalysisTask, task_id).status == S.SAVING
        assert [event.event_type for event in AnalysisEventRepository(db).list_by_analysis_task(task_id)] == [E.REPORT_SAVE_STARTED]


@pytest.mark.postgres
@pytest.mark.parametrize("suffix,body", [("state", {"status": "RUNNING"}), ("perspectives", PERSPECTIVE), ("report", REPORT), ("events", {"event_type": "BASE_ANALYSIS_STARTED"})])
@pytest.mark.parametrize("field", ["organization_id", "requested_by", "memo_id", "base_memo_version", "disclosure_receipt_no"])
def test_internal_request_cannot_override_context(internal_client, analysis_context, suffix, body, field):
    task_id = task(analysis_context)
    result = call(internal_client, task_id, suffix, {**body, field: str(uuid4())})
    assert result.status_code == 422


@pytest.mark.postgres
def test_known_secret_and_sensitive_json_fields_rejected(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    result = call(internal_client, task_id, "report", {**REPORT, "content": KEY})
    assert result.status_code == 422 and KEY not in result.text
    assert call(internal_client, task_id, "report", {**REPORT, "report": {"nested": {"api_key": "private"}}}).status_code == 422
    assert call(internal_client, task_id, "events", {"event_type": "ANALYSIS_WARNING", "payload": {"message": KEY}}).status_code == 422


@pytest.mark.postgres
def test_internal_key_does_not_authenticate_public_api(internal_client, analysis_context):
    assert internal_client.get("/api/v1/memos", headers={"X-Internal-API-Key": KEY}).status_code == 401
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["InternalAPIKey"]["in"] == "header"
    assert schema["paths"]["/internal/analyses/{task_id}/context"]["get"]["security"] == [{"InternalAPIKey": []}]


@pytest.mark.postgres
@pytest.mark.parametrize("invalid", ["", "change-me-in-production", "too-short"])
def test_unconfigured_internal_key_fails_closed(internal_client, analysis_context, invalid):
    analysis_context.settings.internal_api_key = SecretStr(invalid)
    result = call(internal_client, uuid4(), "status", method="GET")
    assert result.status_code == 503 and result.json()["error"]["code"] == "INTERNAL_AUTH_CONFIGURATION_ERROR"
    assert KEY not in result.text


@pytest.mark.postgres
def test_internal_concurrent_perspective_and_report_are_idempotent(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING, G.PERSPECTIVE_ANALYSIS)
    barrier = Barrier(2)

    def register():
        with analysis_context.factory() as db:
            barrier.wait(timeout=5)
            return workflow(analysis_context, db).register_perspective(task_id, PerspectiveCreateRequest(**PERSPECTIVE)).perspective_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: register(), range(2)))
    assert ids[0] == ids[1]
    with analysis_context.factory() as db:
        db.get(AnalysisTask, task_id).current_stage = G.REPORT_GENERATION
        db.commit()
    barrier = Barrier(2)

    def save():
        with analysis_context.factory() as db:
            barrier.wait(timeout=5)
            return workflow(analysis_context, db).save_report(task_id, ReportSaveRequest(**REPORT)).report_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: save(), range(2)))
    assert ids[0] == ids[1]
    with analysis_context.factory() as db:
        assert len(list(db.scalars(select(AnalysisReport).where(AnalysisReport.analysis_task_id == task_id)))) == 1
        names = [row.event_type for row in AnalysisEventRepository(db).list_by_analysis_task(task_id)]
        assert names.count(E.PERSPECTIVE_SELECTED) == names.count(E.REPORT_SAVE_STARTED) == names.count(E.REPORT_SAVED) == 1


@pytest.mark.postgres
def test_state_refresh_rejects_stale_cancelled_entity(internal_client, analysis_context):
    from app.services.analysis import AnalysisService
    from app.repositories import AnalysisRepository, MemoRepository
    task_id = task(analysis_context, S.QUEUED)
    with analysis_context.factory() as stale_session:
        stale = stale_session.get(AnalysisTask, task_id)
        assert stale.status == S.QUEUED
        with analysis_context.factory() as db:
            AnalysisService(AnalysisRepository(db), MemoRepository(db), analysis_context.producer).cancel_analysis(
                task_id, analysis_context.users[0].organization_id, analysis_context.users[0].id)
        with pytest.raises(InternalAPIError) as failure:
            workflow(analysis_context, stale_session).update_state(task_id, InternalStateRequest(status=S.RUNNING))
        assert failure.value.code == "ANALYSIS_NOT_ACTIVE"
        assert stale_session.get(AnalysisTask, task_id).status == S.CANCELLED


@pytest.mark.postgres
def test_cancel_between_report_prepare_and_write_is_respected(internal_client, analysis_context):
    from app.services.analysis import AnalysisService
    from app.repositories import AnalysisRepository, MemoRepository
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    with analysis_context.factory() as db:
        worker = workflow(analysis_context, db)
        write = worker._write_report

        def cancel_then_write(*args):
            with analysis_context.factory() as other:
                AnalysisService(AnalysisRepository(other), MemoRepository(other), analysis_context.producer).cancel_analysis(
                    task_id, analysis_context.users[0].organization_id, analysis_context.users[0].id)
            return write(*args)

        with patch.object(worker, "_write_report", side_effect=cancel_then_write):
            with pytest.raises(InternalAPIError) as failure:
                worker.save_report(task_id, ReportSaveRequest(**REPORT))
            assert failure.value.code == "REPORT_NOT_ALLOWED"
    with analysis_context.factory() as db:
        assert db.get(AnalysisTask, task_id).status == S.CANCELLED
        assert AnalysisReportRepository(db).get_by_analysis_task(task_id) is None


@pytest.mark.postgres
def test_lost_report_commit_confirmation_recovers_existing_report(internal_client, analysis_context):
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    with analysis_context.factory() as db:
        commit = db.commit
        commits = []

        def lost_confirmation():
            commit()
            commits.append(1)
            if len(commits) == 2:
                raise OperationalError("injected", {}, Exception("commit confirmation lost"))

        with patch.object(db, "commit", side_effect=lost_confirmation):
            response = workflow(analysis_context, db).save_report(task_id, ReportSaveRequest(**REPORT))
        assert response.status == S.COMPLETED
        assert len(list(db.scalars(select(AnalysisReport).where(AnalysisReport.analysis_task_id == task_id)))) == 1
        assert [row.event_type for row in AnalysisEventRepository(db).list_by_analysis_task(task_id)].count(E.REPORT_SAVED) == 1


@pytest.mark.postgres
def test_total_db_failure_cannot_guarantee_save_failed_marker(internal_client, analysis_context):
    from app.repositories import AnalysisRepository
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    error = OperationalError("injected", {}, Exception("database inaccessible"))
    with patch.object(AnalysisRepository, "get_by_id", side_effect=error):
        response = call(internal_client, task_id, "report", REPORT)
        assert response.status_code == 503
        assert "database inaccessible" not in response.text
    with analysis_context.factory() as db:
        assert db.get(AnalysisTask, task_id).status == S.RUNNING
        assert AnalysisReportRepository(db).get_by_analysis_task(task_id) is None


@pytest.mark.postgres
@pytest.mark.parametrize("body", [{**REPORT, "content": "text\x00invalid"}, {**REPORT, "report": {"text": "value\x00invalid"}}])
def test_invalid_postgresql_text_rejected_before_save(internal_client, analysis_context, body):
    task_id = task(analysis_context, S.RUNNING, G.REPORT_GENERATION)
    assert call(internal_client, task_id, "report", body).status_code == 422
    with analysis_context.factory() as db:
        assert db.get(AnalysisTask, task_id).status == S.RUNNING
