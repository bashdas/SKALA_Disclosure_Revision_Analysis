import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from disclosure_ai import worker
from disclosure_ai.business import BusinessError


@pytest.mark.parametrize("failed_publish", [False, True])
def test_worker_confirms_retry_before_ack(monkeypatch, failed_publish):
    actions = []
    message = worker.Message(
        message_id=uuid4(), task_id=uuid4(), type="RUN_ANALYSIS", retry_count=0
    )

    class Connection:
        is_open = True
        callback = None

        def channel(self):
            return channel

        def add_callback_threadsafe(self, callback):
            self.callback = callback

        def close(self):
            actions.append("close")
            self.is_open = False

    class Channel:
        is_open = True

        def queue_declare(self, **kwargs):
            assert kwargs["passive"]

        def confirm_delivery(self):
            actions.append("confirm")

        def basic_qos(self, **kwargs):
            assert kwargs["prefetch_count"] == 1

        def basic_consume(self, **kwargs):
            self.receive = kwargs["on_message_callback"]

        def basic_publish(self, **kwargs):
            actions.append("publish")
            assert kwargs["routing_key"] == "analysis.retry.1"
            assert kwargs["mandatory"]
            assert worker.Message.model_validate_json(kwargs["body"]).retry_count == 1
            if failed_publish:
                raise RuntimeError("confirmation unavailable")

        def basic_ack(self, **kwargs):
            actions.append("ack")

        def start_consuming(self):
            import time

            self.receive(
                self, SimpleNamespace(delivery_tag=7), None, message.model_dump_json().encode()
            )
            for _ in range(100):
                if connection.callback:
                    connection.callback()
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("worker completion missing")
            raise KeyboardInterrupt

    async def fail(task_id, state):
        await asyncio.sleep(0)
        raise BusinessError("TEMPORARY", True)

    connection, channel = Connection(), Channel()
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1/")
    monkeypatch.setattr(worker.pika, "BlockingConnection", lambda _: connection)
    monkeypatch.setattr(worker, "process_task", fail)
    worker.consume(Path("unused.sqlite"))
    assert actions == (
        ["confirm", "publish", "close"]
        if failed_publish
        else ["confirm", "publish", "ack", "close"]
    )


@pytest.mark.parametrize(
    "status,target",
    [("RUNNING", "FAILED"), ("SAVING", "SAVE_FAILED"), ("CANCELLED", None), ("SAVE_FAILED", None)],
)
def test_final_failure_updates_only_active_state(monkeypatch, status, target):
    calls = []

    async def fail(task_id, state):
        raise BusinessError("UPSTREAM_FAILED", True)

    async def internal(task_id, method, suffix, body=None):
        calls.append((method, suffix, body))
        return {"status": status}

    monkeypatch.setattr(worker, "process_task", fail)
    monkeypatch.setattr(worker, "internal_request", internal)
    message = worker.Message(
        message_id=uuid4(), task_id=uuid4(), type="RUN_ANALYSIS", retry_count=3
    )
    with pytest.raises(BusinessError):
        asyncio.run(worker.process_message(message, Path("unused.sqlite"), 3))
    assert calls[0] == ("GET", "status", None)
    assert len(calls) == (2 if target else 1)
    if target:
        assert calls[1][2]["status"] == target
        assert calls[1][2]["error_code"] == "AI_RETRIES_EXHAUSTED"


def test_final_retry_preserves_report_before_remote_save(monkeypatch, tmp_path):
    from disclosure_ai.ledger import Ledger

    message = worker.Message(
        message_id=uuid4(), task_id=uuid4(), type="RUN_ANALYSIS", retry_count=3
    )
    state = tmp_path / "state.sqlite"
    ledger = Ledger(str(state))
    ledger.begin(str(message.task_id), "fixed")
    ledger.keep(str(message.task_id), "report", {"content": "보존할 보고서"})
    ledger.db.close()
    posted = []

    async def fail(task_id, state):
        raise BusinessError("SAVE_FAILED", True)

    async def internal(task_id, method, suffix, body=None):
        if method == "POST":
            posted.append(body["status"])
        return {"status": "RUNNING", "current_stage": "REPORT_GENERATION"}

    monkeypatch.setattr(worker, "process_task", fail)
    monkeypatch.setattr(worker, "internal_request", internal)
    with pytest.raises(BusinessError):
        asyncio.run(worker.process_message(message, state, 3))
    assert posted == ["SAVING", "SAVE_FAILED"]
