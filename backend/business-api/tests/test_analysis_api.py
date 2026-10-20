from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_analysis_producer
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.domain.analysis_exceptions import AnalysisAlreadyRunning, RabbitMQPublishFailed
from app.main import app
from app.models import AnalysisEvent, AnalysisPerspectiveTask, AnalysisReport, AnalysisTask, Memo, MemoVersion, Organization, User
from app.models.enums import AnalysisStage, AnalysisStatus as S, UserRole
from app.repositories import AnalysisRepository, MemoRepository
from app.services.analysis import AnalysisService
from test_auth_security import auth_settings
from test_domain import migrated_engine

RECEIPT = "20261020000123"


@pytest.fixture
def analysis_context(migrated_engine, auth_settings):
    factory = sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
    with factory() as db:
        orgs = [Organization(name="Analysis A"), Organization(name="Analysis B")]
        db.add_all(orgs)
        db.flush()
        users = [User(organization_id=org.id, email=f"{uuid4()}@example.test", password_hash="unused", role=role) for org, role in zip(orgs, [UserRole.RA, UserRole.ANALYST])]
        db.add_all(users)
        db.flush()
        memos = [Memo(organization_id=user.organization_id, company_name=None, title="Memo", current_version=3) for user in users]
        db.add_all(memos)
        db.flush()
        db.add_all([MemoVersion(memo_id=memo.id, version=3, content="private memo body", created_by=user.id) for memo, user in zip(memos, users)])
        db.commit()
    context = SimpleNamespace(factory=factory, users=users, memos=memos, settings=auth_settings, calls=[], fail=False)

    class Producer:
        def publish_analysis(self, task_id):
            # Broker delivery must only occur after QUEUED becomes visible outside request Session.
            with factory() as db:
                row = db.get(AnalysisTask, task_id)
                assert row is not None and row.status == S.QUEUED
            context.calls.append(task_id)
            if context.fail:
                raise RabbitMQPublishFailed()

    context.producer = Producer()
    try:
        yield context
    finally:
        with factory() as db:
            ids = [org.id for org in orgs]
            task_ids = select(AnalysisTask.id).where(AnalysisTask.organization_id.in_(ids))
            db.execute(delete(AnalysisEvent).where(AnalysisEvent.analysis_task_id.in_(task_ids)))
            db.execute(delete(AnalysisPerspectiveTask).where(AnalysisPerspectiveTask.analysis_task_id.in_(task_ids)))
            db.execute(delete(AnalysisReport).where(AnalysisReport.analysis_task_id.in_(task_ids)))
            db.execute(delete(AnalysisTask).where(AnalysisTask.organization_id.in_(ids)))
            db.execute(delete(MemoVersion).where(MemoVersion.memo_id.in_([memo.id for memo in memos])))
            db.execute(delete(Memo).where(Memo.organization_id.in_(ids)))
            db.execute(delete(User).where(User.organization_id.in_(ids)))
            db.execute(delete(Organization).where(Organization.id.in_(ids)))
            db.commit()


@pytest.fixture
def analysis_client(analysis_context):
    previous = app.dependency_overrides.copy()

    def session_override():
        with analysis_context.factory() as session:
            yield session

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_settings] = lambda: analysis_context.settings
    app.dependency_overrides[get_analysis_producer] = lambda: analysis_context.producer
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def request(client, context, *, user=0, memo=0, receipt=RECEIPT, **extra):
    return client.post("/api/v1/analyses", json={"memo_id": str(context.memos[memo].id), "disclosure_receipt_no": receipt, **extra}, headers={"Authorization": "Bearer " + create_access_token(context.users[user], settings=context.settings)})


@pytest.mark.postgres
@pytest.mark.parametrize("index", [0, 1])
def test_roles_creation_and_fixed_context(analysis_client, analysis_context, index):
    context = analysis_context
    result = request(analysis_client, context, user=index, memo=index)
    assert result.status_code == 202, result.text
    body = result.json()
    assert body["status"] == "QUEUED"
    assert context.calls == [UUID(body["task_id"])]
    with context.factory() as db:
        row = db.get(AnalysisTask, UUID(body["task_id"]))
        assert row.organization_id == context.users[index].organization_id
        assert row.requested_by == context.users[index].id
        assert row.base_memo_version == 3
        assert row.disclosure_receipt_no == RECEIPT
        assert row.status == S.QUEUED and row.current_stage == AnalysisStage.REQUEST_VALIDATION
        assert row.filing_id is None and row.corp_code is None and row.company_name_snapshot is None
        assert not row.has_warnings and row.started_at is None and row.completed_at is None
        assert UUID(row.thread_id)
        memo = db.get(Memo, row.memo_id)
        memo.current_version = 4
        db.commit()
        db.refresh(row)
        assert row.base_memo_version == 3


@pytest.mark.postgres
def test_scope_missing_auth_and_no_client_scope(analysis_client, analysis_context):
    assert request(analysis_client, analysis_context, user=1).status_code == 404
    result = request(analysis_client, analysis_context, memo_id=str(uuid4()))
    assert result.status_code == 404 and result.json()["error"]["code"] == "MEMO_NOT_FOUND"
    assert analysis_client.post("/api/v1/analyses", json={"memo_id": str(uuid4()), "disclosure_receipt_no": RECEIPT}).status_code == 401
    assert request(analysis_client, analysis_context, organization_id=str(uuid4())).status_code == 422
    assert analysis_context.calls == []


@pytest.mark.postgres
@pytest.mark.parametrize("receipt", ["", "123", "2026102000012x", "２０２６１０２００００１２３", "20261020000123\n", " 20261020000123"])
def test_receipt_format(analysis_client, analysis_context, receipt):
    assert request(analysis_client, analysis_context, receipt=receipt).status_code == 422
    assert analysis_context.calls == []


def seed_task(context, status):
    with context.factory() as db:
        row = AnalysisTask(organization_id=context.users[0].organization_id, requested_by=context.users[0].id,
            memo_id=context.memos[0].id, base_memo_version=3, disclosure_receipt_no=RECEIPT,
            status=status, thread_id=str(uuid4()))
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.postgres
@pytest.mark.parametrize("status", [S.CREATED, S.QUEUED, S.RUNNING, S.SAVING, S.SAVE_FAILED])
def test_active_duplicate(analysis_client, analysis_context, status):
    existing = seed_task(analysis_context, status)
    result = request(analysis_client, analysis_context)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "ANALYSIS_ALREADY_RUNNING"
    assert result.json()["error"]["existing_task_id"] == str(existing)
    assert analysis_context.calls == []


@pytest.mark.postgres
@pytest.mark.parametrize("status", [S.COMPLETED, S.COMPLETED_WITH_WARNINGS, S.FAILED, S.CANCELLED])
def test_terminal_can_repeat(analysis_client, analysis_context, status):
    existing = seed_task(analysis_context, status)
    result = request(analysis_client, analysis_context)
    assert result.status_code == 202
    assert result.json()["task_id"] != str(existing)


@pytest.mark.postgres
@pytest.mark.parametrize("difference", ["version", "receipt", "organization"])
def test_duplicate_key_dimensions(analysis_client, analysis_context, difference):
    seed_task(analysis_context, S.QUEUED)
    params = {}
    if difference == "version":
        with analysis_context.factory() as db:
            db.get(Memo, analysis_context.memos[0].id).current_version = 4
            db.add(MemoVersion(memo_id=analysis_context.memos[0].id, version=4, content="New", created_by=analysis_context.users[0].id))
            db.commit()
    elif difference == "receipt":
        params["receipt"] = "20261020000124"
    else:
        params.update(user=1, memo=1)
    assert request(analysis_client, analysis_context, **params).status_code == 202


@pytest.mark.postgres
def test_failure_finalized_and_can_request_again(analysis_client, analysis_context):
    analysis_context.fail = True
    result = request(analysis_client, analysis_context)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "RABBITMQ_PUBLISH_FAILED"
    with analysis_context.factory() as db:
        row = db.get(AnalysisTask, analysis_context.calls[0])
        assert row.status == S.FAILED and row.completed_at.utcoffset().total_seconds() == 0
        assert row.error_code == "RABBITMQ_PUBLISH_FAILED"
        assert row.error_stage == AnalysisStage.REQUEST_VALIDATION
        assert row.started_at is None
    analysis_context.fail = False
    assert request(analysis_client, analysis_context).status_code == 202


@pytest.mark.postgres
def test_commit_failure_rolls_back_and_does_not_publish(analysis_context):
    context = analysis_context
    with context.factory() as db:
        service = AnalysisService(AnalysisRepository(db), MemoRepository(db), context.producer)
        with patch.object(db, "commit", side_effect=RuntimeError("injected commit failure")):
            with pytest.raises(RuntimeError):
                service.create(memo_id=context.memos[0].id, disclosure_receipt_no=RECEIPT, organization_id=context.users[0].organization_id, requested_by=context.users[0].id)
        assert not db.in_transaction()
    with context.factory() as db:
        assert db.scalar(select(AnalysisTask).where(AnalysisTask.memo_id == context.memos[0].id)) is None
    assert context.calls == []


@pytest.mark.postgres
def test_concurrent_identical_requests_create_only_one(analysis_context):
    context = analysis_context
    barrier = Barrier(2)

    def submit():
        with context.factory() as db:
            service = AnalysisService(AnalysisRepository(db), MemoRepository(db), context.producer)
            barrier.wait(timeout=5)
            try:
                return service.create(memo_id=context.memos[0].id, disclosure_receipt_no=RECEIPT, organization_id=context.users[0].organization_id, requested_by=context.users[0].id).task_id
            except AnalysisAlreadyRunning:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))
    assert sum(value is not None for value in outcomes) == 1
    assert len(context.calls) == 1
    with context.factory() as db:
        assert len(list(db.scalars(select(AnalysisTask).where(AnalysisTask.memo_id == context.memos[0].id)))) == 1


@pytest.mark.postgres
def test_missing_current_version_rolls_back(analysis_client, analysis_context):
    with analysis_context.factory() as db:
        db.get(Memo, analysis_context.memos[0].id).current_version = 9
        db.commit()
    result = request(analysis_client, analysis_context)
    assert result.status_code == 404
    assert result.json()["error"]["code"] == "MEMO_VERSION_NOT_FOUND"
    assert analysis_context.calls == []


@pytest.mark.postgres
def test_ambiguous_delivery_preserves_worker_progress(analysis_client, analysis_context):
    context = analysis_context

    def publish(task_id):
        with context.factory() as db:
            task = db.get(AnalysisTask, task_id)
            task.status = S.RUNNING
            db.commit()
        context.calls.append(task_id)
        raise RabbitMQPublishFailed()

    context.producer.publish_analysis = publish
    assert request(analysis_client, context).status_code == 503
    with context.factory() as db:
        assert db.get(AnalysisTask, context.calls[0]).status == S.RUNNING


@pytest.mark.postgres
def test_real_unavailable_broker_returns_503_and_failed_task(analysis_client, analysis_context):
    from app.core.config import Settings
    from app.infrastructure.analysis_queue import RabbitMQAnalysisProducer
    producer = RabbitMQAnalysisProducer(Settings(_env_file=None,
        rabbitmq_url="amqp://test:clearly-test-only@127.0.0.1:1/", rabbitmq_publish_timeout_seconds=1))
    previous = app.dependency_overrides[get_analysis_producer]
    app.dependency_overrides[get_analysis_producer] = lambda: producer
    try:
        response = request(analysis_client, analysis_context)
        assert response.status_code == 503
        assert "clearly-test-only" not in response.text
        with analysis_context.factory() as db:
            row = db.scalar(select(AnalysisTask).where(AnalysisTask.memo_id == analysis_context.memos[0].id))
            assert row.status == S.FAILED and row.error_code == "RABBITMQ_PUBLISH_FAILED"
            assert row.completed_at is not None
    finally:
        app.dependency_overrides[get_analysis_producer] = previous
        producer.close()


@pytest.mark.postgres
def test_api_real_broker_temporary_failure_then_confirmed_202(analysis_client, analysis_context):
    import json
    import os
    import pika
    from app.core.config import Settings
    from app.infrastructure.analysis_queue import RabbitMQAnalysisProducer
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("TEST_RABBITMQ_URL required")
    prefix = "test.api." + uuid4().hex
    settings = Settings(_env_file=None, rabbitmq_url=url, rabbitmq_exchange=prefix + ".exchange",
        rabbitmq_analysis_queue=prefix, rabbitmq_analysis_retry_queue=prefix + ".retry", rabbitmq_analysis_dlq=prefix + ".dlq")
    attempts = []

    def connect(parameters):
        attempts.append(1)
        if len(attempts) == 1:
            raise pika.exceptions.AMQPConnectionError("injected first connection failure")
        return pika.BlockingConnection(parameters)

    producer = RabbitMQAnalysisProducer(settings, connection_factory=connect, sleeper=lambda _: None)
    previous = app.dependency_overrides[get_analysis_producer]
    app.dependency_overrides[get_analysis_producer] = lambda: producer
    try:
        response = request(analysis_client, analysis_context)
        assert response.status_code == 202 and len(attempts) == 2
        conn = pika.BlockingConnection(pika.URLParameters(url))
        try:
            channel = conn.channel()
            method, _, raw = channel.basic_get(prefix, auto_ack=True)
            assert method is not None and json.loads(raw)["task_id"] == response.json()["task_id"]
            for name in (prefix, prefix + ".retry", prefix + ".retry.2", prefix + ".retry.3", prefix + ".dlq"):
                channel.queue_delete(queue=name)
            channel.exchange_delete(exchange=settings.rabbitmq_exchange)
        finally:
            conn.close()
    finally:
        app.dependency_overrides[get_analysis_producer] = previous
        producer.close()
