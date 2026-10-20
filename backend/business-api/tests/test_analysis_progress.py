import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_db, get_stream_session_factory
from app.core.security import create_access_token
from app.domain.analysis_events import AnalysisEventType as E
from app.domain.analysis_exceptions import InvalidEventPayload
from app.main import app
from app.models import AnalysisEvent, AnalysisTask, User
from app.models.enums import AnalysisStatus as S, UserRole
from app.repositories import AnalysisEventRepository, AnalysisRepository, MemoRepository
from app.schemas.analysis import AnalysisEventResponse
from app.services.analysis import AnalysisService
from app.services.analysis_event import AnalysisEventService
from app.services.analysis_stream import AnalysisEventStream, EventSnapshot
from test_analysis_api import analysis_context, analysis_client, request, seed_task
from test_auth_security import auth_settings
from test_domain import migrated_engine


def headers(context, index=0):
    return {"Authorization": "Bearer " + create_access_token(context.users[index], settings=context.settings)}


def path(task_id, suffix=""):
    return f"/api/v1/analyses/{task_id}" + suffix


def append(context, task_id, event_type=E.ANALYSIS_WARNING, payload=None):
    with context.factory() as db:
        return AnalysisEventService(AnalysisRepository(db), AnalysisEventRepository(db)).append_event(
            task_id, context.users[0].organization_id, event_type, payload or {"message": "Summary"})


def service(db, context):
    return AnalysisService(AnalysisRepository(db), MemoRepository(db), context.producer)


@pytest.mark.postgres
@pytest.mark.parametrize("index", [0, 1])
def test_detail_roles_and_no_internal_fields(analysis_client, analysis_context, index):
    response = request(analysis_client, analysis_context, user=index, memo=index)
    task_id = UUID(response.json()["task_id"])
    with analysis_context.factory() as db:
        task = db.get(AnalysisTask, task_id)
        task.error_message = "must-not-expose postgres://password or stack trace"
        db.commit()
    result = analysis_client.get(path(task_id), headers=headers(analysis_context, index))
    assert result.status_code == 200
    body = result.json()
    assert body["task_id"] == str(task_id) and body["status"] == "QUEUED"
    assert body["current_stage"] == "REQUEST_VALIDATION" and body["base_memo_version"] == 3
    assert body["disclosure_receipt_no"] == "20261020000123"
    assert body["corp_code"] is None and body["company_name_snapshot"] is None
    assert not ({"error_message", "organization_id", "requested_by", "thread_id"} & body.keys())
    assert "must-not-expose" not in result.text


@pytest.mark.postgres
@pytest.mark.parametrize("suffix,method", [("", "get"), ("/events", "get"), ("/events/stream", "get"), ("/cancel", "post")])
def test_scope_and_auth_on_every_endpoint(analysis_client, analysis_context, suffix, method):
    task_id = seed_task(analysis_context, S.QUEUED)
    old = app.dependency_overrides.get(get_stream_session_factory)
    app.dependency_overrides[get_stream_session_factory] = lambda: analysis_context.factory
    try:
        call = getattr(analysis_client, method)
        assert call(path(task_id, suffix)).status_code == 401
        assert call(path(task_id, suffix), headers=headers(analysis_context, 1)).status_code == 404
        assert call(path(uuid4(), suffix), headers=headers(analysis_context)).status_code == 404
    finally:
        if old is None:
            app.dependency_overrides.pop(get_stream_session_factory)
        else:
            app.dependency_overrides[get_stream_session_factory] = old


@pytest.mark.postgres
def test_queued_and_publish_failed_events(analysis_client, analysis_context):
    analysis_context.fail = True
    assert request(analysis_client, analysis_context).status_code == 503
    with analysis_context.factory() as db:
        rows = AnalysisEventRepository(db).list_by_analysis_task(analysis_context.calls[0])
        assert [row.sequence for row in rows] == [1, 2]
        assert [row.event_type for row in rows] == [E.ANALYSIS_QUEUED, E.ANALYSIS_FAILED]
        assert rows[1].payload_json == {"status": "FAILED", "code": "RABBITMQ_PUBLISH_FAILED"}
    analysis_context.fail = False
    response = request(analysis_client, analysis_context)
    with analysis_context.factory() as db:
        rows = AnalysisEventRepository(db).list_by_analysis_task(UUID(response.json()["task_id"]))
        assert len(rows) == 1 and rows[0].sequence == 1 and rows[0].event_type == E.ANALYSIS_QUEUED


@pytest.mark.postgres
def test_event_sequence_payload_and_task_independence(analysis_context):
    one = seed_task(analysis_context, S.RUNNING)
    two = seed_task(analysis_context, S.RUNNING)
    assert append(analysis_context, one).sequence == 1
    result = append(analysis_context, one, E.PERSPECTIVE_SELECTED, {"perspective": "FINANCE", "reason": "Financial impact"})
    assert result.sequence == 2 and result.event_type == E.PERSPECTIVE_SELECTED
    assert result.payload == {"perspective": "FINANCE", "reason": "Financial impact"}
    assert append(analysis_context, two).sequence == 1
    with analysis_context.factory() as db:
        db.add(AnalysisEvent(analysis_task_id=one, sequence=1, event_type=E.ANALYSIS_WARNING, payload_json={}))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


@pytest.mark.postgres
def test_concurrent_event_appends_have_distinct_contiguous_sequences(analysis_context):
    task_id = seed_task(analysis_context, S.RUNNING)
    barrier = Barrier(6)

    def write(index):
        barrier.wait(timeout=5)
        return append(analysis_context, task_id, payload={"message": f"Summary {index}"}).sequence

    with ThreadPoolExecutor(max_workers=6) as pool:
        values = list(pool.map(write, range(6)))
    assert sorted(values) == list(range(1, 7))
    with analysis_context.factory() as db:
        assert [row.sequence for row in AnalysisEventRepository(db).list_by_analysis_task(task_id)] == list(range(1, 7))


@pytest.mark.postgres
@pytest.mark.parametrize("payload", [{"password": "do-not-save"}, {"JWT": "do-not-save"}, {"memo_content": "private"}, {"message": "a" * 501}, {"reason": "a" * 1001}, {"nested": {"api_key": "private"}}])
def test_event_payload_is_bounded_summary(analysis_context, payload):
    task_id = seed_task(analysis_context, S.RUNNING)
    with pytest.raises(InvalidEventPayload):
        append(analysis_context, task_id, payload=payload)
    with analysis_context.factory() as db:
        assert AnalysisEventRepository(db).get_latest_sequence(task_id) == 0


@pytest.mark.postgres
def test_events_api_cursor_order_and_empty(analysis_client, analysis_context):
    task_id = seed_task(analysis_context, S.RUNNING)
    assert analysis_client.get(path(task_id, "/events"), headers=headers(analysis_context)).json() == []
    for _ in range(3):
        append(analysis_context, task_id)
    result = analysis_client.get(path(task_id, "/events?after_sequence=1&limit=1"), headers=headers(analysis_context))
    assert result.status_code == 200 and [item["sequence"] for item in result.json()] == [2]
    assert result.json()[0]["payload"] == {"message": "Summary"}
    assert [item["sequence"] for item in analysis_client.get(path(task_id, "/events"), headers=headers(analysis_context)).json()] == [1, 2, 3]


@pytest.mark.postgres
@pytest.mark.parametrize("status", [S.CREATED, S.QUEUED, S.RUNNING, S.SAVING, S.SAVE_FAILED])
def test_cancel_allowed_state_completed_timestamp_and_idempotency(analysis_client, analysis_context, status):
    task_id = seed_task(analysis_context, status)
    result = analysis_client.post(path(task_id, "/cancel"), headers=headers(analysis_context))
    assert result.status_code == 200 and result.json() == {"task_id": str(task_id), "status": "CANCELLED"}
    with analysis_context.factory() as db:
        task = db.get(AnalysisTask, task_id)
        completed = task.completed_at
        assert task.status == S.CANCELLED and completed.utcoffset().total_seconds() == 0
        rows = AnalysisEventRepository(db).list_by_analysis_task(task_id)
        assert len(rows) == 1 and rows[0].event_type == E.ANALYSIS_CANCELLED
    assert analysis_client.post(path(task_id, "/cancel"), headers=headers(analysis_context)).status_code == 200
    with analysis_context.factory() as db:
        assert db.get(AnalysisTask, task_id).completed_at == completed
        assert AnalysisEventRepository(db).get_latest_sequence(task_id) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("status", [S.COMPLETED, S.COMPLETED_WITH_WARNINGS, S.FAILED])
def test_terminal_cancel_is_conflict(analysis_client, analysis_context, status):
    task_id = seed_task(analysis_context, status)
    response = analysis_client.post(path(task_id, "/cancel"), headers=headers(analysis_context))
    assert response.status_code == 409 and response.json()["error"]["code"] == "ANALYSIS_CANNOT_BE_CANCELLED"


@pytest.mark.postgres
def test_same_organization_nonrequester_cannot_cancel(analysis_client, analysis_context):
    task_id = seed_task(analysis_context, S.QUEUED)
    with analysis_context.factory() as db:
        other = User(organization_id=analysis_context.users[0].organization_id, email=f"{uuid4()}@example.test", password_hash="unused", role=UserRole.ANALYST)
        db.add(other)
        db.commit()
    try:
        token = create_access_token(other, settings=analysis_context.settings)
        response = analysis_client.post(path(task_id, "/cancel"), headers={"Authorization": "Bearer " + token})
        assert response.status_code == 403 and response.json()["error"]["code"] == "ANALYSIS_CANCEL_FORBIDDEN"
    finally:
        with analysis_context.factory() as db:
            db.execute(delete(User).where(User.id == other.id))
            db.commit()


@pytest.mark.postgres
def test_cancel_and_queued_creation_roll_back_when_event_fails(analysis_client, analysis_context):
    task_id = seed_task(analysis_context, S.RUNNING)
    with analysis_context.factory() as db:
        workflow = service(db, analysis_context)
        with patch.object(workflow.events.events, "add", side_effect=RuntimeError("injected event insert failure")):
            with pytest.raises(RuntimeError):
                workflow.cancel_analysis(task_id, analysis_context.users[0].organization_id, analysis_context.users[0].id)
        assert not db.in_transaction()
        assert db.get(AnalysisTask, task_id).status == S.RUNNING
        assert AnalysisEventRepository(db).get_latest_sequence(task_id) == 0
    with analysis_context.factory() as db:
        db.get(AnalysisTask, task_id).status = S.COMPLETED
        db.commit()
        workflow = service(db, analysis_context)
        with patch.object(workflow.events.events, "add", side_effect=RuntimeError("injected event insert failure")):
            with pytest.raises(RuntimeError):
                workflow.create(memo_id=analysis_context.memos[0].id, disclosure_receipt_no="20261020000123", organization_id=analysis_context.users[0].organization_id, requested_by=analysis_context.users[0].id)
        assert len(list(db.scalars(select(AnalysisTask).where(AnalysisTask.memo_id == analysis_context.memos[0].id)))) == 1
    assert analysis_context.calls == []


@pytest.mark.postgres
@pytest.mark.parametrize("query,last_id,expected", [("", None, [1, 2, 3]), ("?after_sequence=1", None, [2, 3]), ("", "2", [3]), ("?after_sequence=1", "2", [2, 3]), ("?after_sequence=0", "bad", [1, 2, 3])])
def test_sse_replay_format_cursor_and_closed_sessions(analysis_client, analysis_context, query, last_id, expected):
    task_id = seed_task(analysis_context, S.COMPLETED)
    for _ in range(3):
        append(analysis_context, task_id)
    counts = SimpleNamespace(active=0, opened=0)

    @contextmanager
    def factory():
        counts.active += 1
        counts.opened += 1
        try:
            with analysis_context.factory() as db:
                yield db
        finally:
            counts.active -= 1

    app.dependency_overrides[get_stream_session_factory] = lambda: factory
    original_db = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = lambda: pytest.fail("SSE must not use request-scoped get_db")
    try:
        auth = headers(analysis_context)
        if last_id is not None:
            auth["Last-Event-ID"] = last_id
        response = analysis_client.get(path(task_id, "/events/stream" + query), headers=auth)
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        blocks = [part for part in response.text.split("\n\n") if part]
        assert [int(block.splitlines()[0].removeprefix("id: ")) for block in blocks] == expected
        for block in blocks:
            lines = block.splitlines()
            assert lines[1] == "event: ANALYSIS_WARNING"
            assert json.loads(lines[2].removeprefix("data: "))["payload"] == {"message": "Summary"}
        assert counts.active == 0 and counts.opened == 2  # short auth + initial snapshot
    finally:
        app.dependency_overrides[get_db] = original_db
        app.dependency_overrides.pop(get_stream_session_factory)


@pytest.mark.postgres
@pytest.mark.parametrize("value", ["-1", "bad", "1.5", "", "2147483648", "1\n"])
def test_invalid_last_event_id(analysis_client, analysis_context, value):
    task_id = seed_task(analysis_context, S.COMPLETED)
    app.dependency_overrides[get_stream_session_factory] = lambda: analysis_context.factory
    try:
        auth = headers(analysis_context)
        auth["Last-Event-ID"] = value
        response = analysis_client.get(path(task_id, "/events/stream"), headers=auth)
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_LAST_EVENT_ID"
    finally:
        app.dependency_overrides.pop(get_stream_session_factory)


@pytest.mark.postgres
def test_sse_rejects_query_tokens(analysis_client, analysis_context):
    task_id = seed_task(analysis_context, S.COMPLETED)
    app.dependency_overrides[get_stream_session_factory] = lambda: analysis_context.factory
    try:
        assert analysis_client.get(path(task_id, "/events/stream?token=test-only-value")).status_code == 401
        result = analysis_client.get(path(task_id, "/events/stream?token=test-only-value"), headers=headers(analysis_context))
        assert result.status_code == 400 and "test-only-value" not in result.text
    finally:
        app.dependency_overrides.pop(get_stream_session_factory)


@pytest.mark.postgres
def test_save_failed_heartbeat_disconnect_and_no_session_during_wait(analysis_context):
    task_id = seed_task(analysis_context, S.SAVE_FAILED)
    state = SimpleNamespace(time=0, active=0, polls=0)

    @contextmanager
    def factory():
        state.active += 1
        state.polls += 1
        try:
            with analysis_context.factory() as db:
                yield db
        finally:
            state.active -= 1

    async def pause(interval):
        assert state.active == 0
        state.time += interval

    class Request:
        async def is_disconnected(self):
            assert state.active == 0
            return state.time >= 3

    stream = AnalysisEventStream(factory, poll_interval=1, heartbeat_seconds=2, clock=lambda: state.time, sleeper=pause)
    initial = stream.snapshot(task_id, analysis_context.users[0].organization_id, 0)
    assert not initial.terminal

    async def collect():
        return [value async for value in stream.stream(Request(), task_id, analysis_context.users[0].organization_id, 0, initial)]

    assert asyncio.run(collect()) == [": heartbeat\n\n"]
    assert state.time == 3 and state.active == 0 and state.polls == 3


@pytest.mark.parametrize("value", ["１２", "-1", "bad", "2147483648", "", " 1"])
def test_last_event_id_parser_rejects_invalid_strings(value):
    from app.domain.analysis_exceptions import InvalidLastEventID
    from app.services.analysis_stream import resolve_after_sequence
    with pytest.raises(InvalidLastEventID):
        resolve_after_sequence(None, value)
    assert resolve_after_sequence(3, value) == 3


@pytest.mark.postgres
def test_concurrent_cancel_and_stale_session_are_idempotent(analysis_context):
    context = analysis_context
    task_id = seed_task(context, S.RUNNING)
    barrier = Barrier(2)

    def cancel():
        with context.factory() as db:
            stale = db.get(AnalysisTask, task_id)
            assert stale.status == S.RUNNING
            barrier.wait(timeout=5)
            return service(db, context).cancel_analysis(task_id, context.users[0].organization_id, context.users[0].id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: cancel(), range(2)))
    assert all(item.status == "CANCELLED" for item in results)
    with context.factory() as db:
        assert db.get(AnalysisTask, task_id).status == S.CANCELLED
        assert AnalysisEventRepository(db).get_latest_sequence(task_id) == 1


@pytest.mark.postgres
def test_sse_drains_multiple_batches_then_closes(analysis_client, analysis_context):
    task_id = seed_task(analysis_context, S.COMPLETED_WITH_WARNINGS)
    with analysis_context.factory() as db:
        db.add_all([AnalysisEvent(analysis_task_id=task_id, sequence=seq, event_type=E.ANALYSIS_WARNING, payload_json={"message": "Summary"}) for seq in range(1, 206)])
        db.commit()
    app.dependency_overrides[get_stream_session_factory] = lambda: analysis_context.factory
    try:
        result = analysis_client.get(path(task_id, "/events/stream"), headers=headers(analysis_context))
        assert result.status_code == 200
        assert [int(line.removeprefix("id: ")) for line in result.text.splitlines() if line.startswith("id:")] == list(range(1, 206))
    finally:
        app.dependency_overrides.pop(get_stream_session_factory)


@pytest.mark.postgres
@pytest.mark.parametrize("status", [S.COMPLETED, S.COMPLETED_WITH_WARNINGS, S.FAILED, S.CANCELLED])
def test_sse_terminal_without_remaining_events_closes(analysis_client, analysis_context, status):
    task_id = seed_task(analysis_context, status)
    app.dependency_overrides[get_stream_session_factory] = lambda: analysis_context.factory
    try:
        response = analysis_client.get(path(task_id, "/events/stream"), headers=headers(analysis_context))
        assert response.status_code == 200 and response.text == ""
    finally:
        app.dependency_overrides.pop(get_stream_session_factory)


@pytest.mark.postgres
def test_actual_asgi_disconnect_stops_stream_without_open_db_session(analysis_client, analysis_context):
    task_id = seed_task(analysis_context, S.RUNNING)
    append(analysis_context, task_id)
    state = SimpleNamespace(active=0, opened=0)

    @contextmanager
    def factory():
        state.active += 1
        state.opened += 1
        try:
            with analysis_context.factory() as db:
                yield db
        finally:
            state.active -= 1

    app.dependency_overrides[get_stream_session_factory] = lambda: factory

    async def run():
        disconnect = asyncio.Event()
        response_parts = []
        received_request = False

        async def receive():
            nonlocal received_request
            if not received_request:
                received_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and b"id: 1\n" in message.get("body", b""):
                assert state.active == 0
                response_parts.append(message["body"])
                disconnect.set()

        url = path(task_id, "/events/stream")
        token = headers(analysis_context)["Authorization"]
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "GET", "scheme": "http", "path": url,
            "raw_path": url.encode(), "query_string": b"", "root_path": "",
            "headers": [(b"authorization", token.encode())], "server": ("test", 80), "client": ("test", 1)}
        await asyncio.wait_for(app(scope, receive, send), timeout=3)
        assert len(response_parts) == 1

    try:
        asyncio.run(run())
        assert state.active == 0 and state.opened == 2
    finally:
        app.dependency_overrides.pop(get_stream_session_factory)


@pytest.mark.postgres
def test_stream_polls_new_committed_events_then_terminal(analysis_context):
    context = analysis_context
    task_id = seed_task(context, S.RUNNING)
    initial = EventSnapshot([], False)
    pauses = []

    async def pause(interval):
        pauses.append(interval)
        with context.factory() as db:
            service(db, context).cancel_analysis(task_id, context.users[0].organization_id, context.users[0].id)

    class Request:
        async def is_disconnected(self):
            return False

    stream = AnalysisEventStream(context.factory, poll_interval=1, heartbeat_seconds=15, sleeper=pause)

    async def collect():
        return [frame async for frame in stream.stream(Request(), task_id, context.users[0].organization_id, 0, initial)]

    result = asyncio.run(collect())
    assert len(result) == 1 and "event: ANALYSIS_CANCELLED" in result[0]
    assert pauses == [1]
