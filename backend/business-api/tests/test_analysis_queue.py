import json
import os
from threading import get_ident
from time import monotonic, sleep
from unittest.mock import MagicMock
from uuid import uuid4

import pika
import pytest

from app.core.config import Settings
from app.domain.analysis_exceptions import RabbitMQPublishFailed, RabbitMQUnavailable
from app.infrastructure.analysis_queue import (
    DEAD_KEY, RUN_KEY, RabbitMQAnalysisProducer, declare_topology, retry_routing_key,
)
from app.schemas.analysis import AnalysisMessage


def settings(**values):
    return Settings(_env_file=None, rabbitmq_url="amqp://test:clearly-test-only@localhost:5672/", **values)


def connection():
    value = MagicMock()
    value.is_open = True
    value.channel.return_value.is_open = True
    return value


def test_topology_and_backoff():
    channel = MagicMock()
    config = settings()
    declare_topology(channel, config)
    queues = {call.kwargs["queue"]: call.kwargs for call in channel.queue_declare.call_args_list}
    assert set(queues) == {"analysis.tasks", "analysis.tasks.dlq", "analysis.tasks.retry", "analysis.tasks.retry.2", "analysis.tasks.retry.3"}
    assert all(value["durable"] for value in queues.values())
    for name, ttl in [("analysis.tasks.retry", 5000), ("analysis.tasks.retry.2", 15000), ("analysis.tasks.retry.3", 45000)]:
        assert queues[name]["arguments"] == {"x-message-ttl": ttl, "x-dead-letter-exchange": "analysis.exchange", "x-dead-letter-routing-key": RUN_KEY}
    assert queues["analysis.tasks"]["arguments"]["x-dead-letter-routing-key"] == DEAD_KEY
    channel.exchange_declare.assert_called_once_with(exchange="analysis.exchange", exchange_type="direct", durable=True)


def test_confirm_message_reuse_and_connection_thread_ownership():
    conn = connection()
    owner = []

    def connect(parameters):
        owner.append(get_ident())
        assert parameters.connection_attempts == 1
        assert parameters.blocked_connection_timeout == 5
        return conn

    conn.channel.return_value.basic_publish.side_effect = lambda **kwargs: owner.append(get_ident())
    producer = RabbitMQAnalysisProducer(settings(), connection_factory=connect)
    try:
        ids = [uuid4(), uuid4()]
        for task_id in ids:
            producer.publish_analysis(task_id)
        assert len(set(owner)) == 1 and owner[0] != get_ident()
        assert conn.channel.call_count == 1
        channel = conn.channel.return_value
        channel.confirm_delivery.assert_called_once()
        messages = []
        for call, task_id in zip(channel.basic_publish.call_args_list, ids):
            values = call.kwargs
            message = json.loads(values["body"])
            assert set(message) == {"message_id", "task_id", "type", "retry_count"}
            assert message["task_id"] == str(task_id) and message["type"] == "RUN_ANALYSIS" and message["retry_count"] == 0
            assert values["mandatory"] and values["properties"].delivery_mode == 2
            assert values["properties"].message_id == message["message_id"]
            messages.append(message)
        assert messages[0]["message_id"] != messages[1]["message_id"]
    finally:
        producer.close()
    assert not producer._thread.is_alive()
    conn.close.assert_called_once()
    with pytest.raises(RabbitMQUnavailable):
        producer.publish_analysis(uuid4())


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_publish_attempts_and_stable_message_id(failures):
    connections = [connection() for _ in range(3)]
    calls = []
    for index, conn in enumerate(connections):
        def publish(*, index=index, **kwargs):
            calls.append(json.loads(kwargs["body"]))
            if index < failures:
                raise pika.exceptions.AMQPConnectionError("test-only-secret-must-not-propagate")
        conn.channel.return_value.basic_publish.side_effect = publish
    factory = MagicMock(side_effect=connections)
    sleeper = MagicMock()
    producer = RabbitMQAnalysisProducer(settings(), connection_factory=factory, sleeper=sleeper)
    try:
        if failures == 3:
            with pytest.raises(RabbitMQPublishFailed) as error:
                producer.publish_analysis(uuid4())
            assert "secret" not in str(error.value) and error.value.__cause__ is None
        else:
            producer.publish_analysis(uuid4())
        assert factory.call_count == min(failures + 1, 3)
        assert len({message["message_id"] for message in calls}) == 1
        assert sleeper.call_count == min(failures, 2)
    finally:
        producer.close()


@pytest.mark.parametrize("error", [pika.exceptions.UnroutableError([]), pika.exceptions.NackError([]), TimeoutError("test")])
def test_negative_confirm_and_timeout_are_not_success(error):
    conn = connection()
    conn.channel.return_value.basic_publish.side_effect = error
    producer = RabbitMQAnalysisProducer(settings(rabbitmq_publish_max_attempts=1), connection_factory=lambda _: conn)
    try:
        with pytest.raises(RabbitMQPublishFailed):
            producer.publish_analysis(uuid4())
    finally:
        producer.close()


def test_startup_is_lazy_and_health_failure_safe():
    factory = MagicMock(side_effect=RuntimeError("test-only-credential"))
    producer = RabbitMQAnalysisProducer(settings(), connection_factory=factory)
    try:
        factory.assert_not_called()
        with pytest.raises(RabbitMQUnavailable) as error:
            producer.check_health()
        assert "credential" not in str(error.value)
    finally:
        producer.close()


def test_secret_hidden_and_message_minimal():
    assert "clearly-test-only" not in repr(settings())
    assert AnalysisMessage(task_id=uuid4()).retry_count == 0


def test_real_rabbitmq_confirm_routing_retry_ttl_and_dlq():
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("TEST_RABBITMQ_URL required for isolated RabbitMQ integration probe")
    prefix = "test.analysis." + uuid4().hex
    config = Settings(_env_file=None, rabbitmq_url=url, rabbitmq_exchange=prefix + ".exchange",
        rabbitmq_analysis_queue=prefix, rabbitmq_analysis_retry_queue=prefix + ".retry",
        rabbitmq_analysis_dlq=prefix + ".dlq", rabbitmq_retry_delay_seconds=1)
    producer = RabbitMQAnalysisProducer(config)
    conn = pika.BlockingConnection(pika.URLParameters(url))
    channel = conn.channel()
    try:
        task_id = uuid4()
        producer.publish_analysis(task_id)
        producer.check_health()
        method, properties, raw = channel.basic_get(config.rabbitmq_analysis_queue, auto_ack=False)
        assert method is not None and properties.delivery_mode == 2
        body = json.loads(raw)
        assert body["task_id"] == str(task_id)
        # A reject without explicit retry routes to DLQ, never an infinite retry cycle.
        channel.basic_nack(method.delivery_tag, requeue=False)
        deadline = monotonic() + 5
        while monotonic() < deadline:
            dead, _, dead_body = channel.basic_get(config.rabbitmq_analysis_dlq, auto_ack=True)
            if dead is not None:
                break
            sleep(0.05)
        assert dead is not None and json.loads(dead_body)["task_id"] == str(task_id)
        body["retry_count"] = 1
        channel.confirm_delivery()
        channel.basic_publish(exchange=config.rabbitmq_exchange, routing_key=retry_routing_key(1), body=json.dumps(body).encode(), properties=pika.BasicProperties(delivery_mode=2), mandatory=True)
        retry = channel.queue_declare(queue=config.rabbitmq_analysis_retry_queue, passive=True)
        assert retry.method.message_count == 1
        deadline = monotonic() + 5
        while monotonic() < deadline:
            method, _, retry_body = channel.basic_get(config.rabbitmq_analysis_queue, auto_ack=True)
            if method is not None:
                break
            sleep(0.05)
        assert method is not None and json.loads(retry_body)["retry_count"] == 1
        # Passive declarations verify all expected queues exist on the real broker.
        for name in (config.rabbitmq_analysis_queue, config.rabbitmq_analysis_dlq, config.rabbitmq_analysis_retry_queue, config.rabbitmq_analysis_retry_queue + ".2", config.rabbitmq_analysis_retry_queue + ".3"):
            channel.queue_declare(queue=name, passive=True)
    finally:
        producer.close()
        if channel.is_open:
            for name in (prefix, prefix + ".dlq", prefix + ".retry", prefix + ".retry.2", prefix + ".retry.3"):
                channel.queue_delete(queue=name)
            channel.exchange_delete(exchange=config.rabbitmq_exchange)
        conn.close()


def test_health_requires_broker_rpc_even_for_cached_connection():
    conn = connection()
    producer = RabbitMQAnalysisProducer(settings(), connection_factory=lambda _: conn)
    try:
        producer.publish_analysis(uuid4())
        conn.channel.return_value.exchange_declare.side_effect = pika.exceptions.AMQPConnectionError("unavailable")
        with pytest.raises(RabbitMQUnavailable):
            producer.check_health()
        assert producer._connection is None
    finally:
        producer.close()


def test_lifespan_health_survives_unavailable_rabbitmq():
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import app
    producer = RabbitMQAnalysisProducer(Settings(_env_file=None,
        rabbitmq_url="amqp://test:clearly-test-only@127.0.0.1:1/", rabbitmq_publish_timeout_seconds=1))
    with patch("app.main.RabbitMQAnalysisProducer", return_value=producer):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            response = client.get("/health/rabbitmq")
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "RABBITMQ_UNAVAILABLE"
            assert "clearly-test-only" not in response.text
            assert client.get("/health").status_code == 200
    assert not producer._thread.is_alive()
