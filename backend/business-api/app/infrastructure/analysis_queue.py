"""Synchronous facade; one dedicated thread owns all Pika objects and heartbeats."""
from concurrent.futures import Future
from queue import Empty, Full, Queue
from threading import Lock, Thread
from time import sleep
from typing import Protocol
from uuid import UUID

import pika

from app.core.config import Settings
from app.domain.analysis_exceptions import RabbitMQPublishFailed, RabbitMQUnavailable
from app.schemas.analysis import AnalysisMessage

RUN_KEY = "analysis.run"
DEAD_KEY = "analysis.dead"


def retry_routing_key(attempt: int) -> str:
    return f"analysis.retry.{attempt}"


def declare_topology(channel, settings: Settings) -> None:
    exchange = settings.rabbitmq_exchange
    channel.exchange_declare(exchange=exchange, exchange_type="direct", durable=True)
    channel.queue_declare(queue=settings.rabbitmq_analysis_dlq, durable=True)
    channel.queue_bind(queue=settings.rabbitmq_analysis_dlq, exchange=exchange, routing_key=DEAD_KEY)
    channel.queue_declare(queue=settings.rabbitmq_analysis_queue, durable=True, arguments={
        "x-dead-letter-exchange": exchange, "x-dead-letter-routing-key": DEAD_KEY,
    })
    channel.queue_bind(queue=settings.rabbitmq_analysis_queue, exchange=exchange, routing_key=RUN_KEY)
    for attempt in range(1, settings.rabbitmq_max_retries + 1):
        name = settings.rabbitmq_analysis_retry_queue + (f".{attempt}" if attempt > 1 else "")
        channel.queue_declare(queue=name, durable=True, arguments={
            "x-message-ttl": settings.rabbitmq_retry_delay_seconds * 1000 * 3 ** (attempt - 1),
            "x-dead-letter-exchange": exchange, "x-dead-letter-routing-key": RUN_KEY,
        })
        channel.queue_bind(queue=name, exchange=exchange, routing_key=retry_routing_key(attempt))


class AnalysisQueueProducer(Protocol):
    def publish_analysis(self, task_id: UUID) -> None: ...


class RabbitMQAnalysisProducer:
    def __init__(self, settings: Settings, *, connection_factory=pika.BlockingConnection, sleeper=sleep):
        self.settings = settings
        self._connect = connection_factory
        self._sleep = sleeper
        self._connection = self._channel = None
        self._jobs = Queue(maxsize=64)
        self._lock = Lock()
        self._closed = False
        self._thread = Thread(target=self._run, name="analysis-publisher", daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                operation, future = self._jobs.get(timeout=0.5)
            except Empty:
                if self._connection is not None:
                    try:
                        self._connection.process_data_events(time_limit=0)
                    except Exception:
                        self._disconnect()
                continue
            if operation is None:
                self._disconnect()
                future.set_result(None)
                return
            try:
                future.set_result(operation())
            except Exception as exc:
                future.set_exception(exc)

    def _call(self, operation):
        future = Future()
        with self._lock:
            if self._closed:
                raise RabbitMQUnavailable()
            try:
                self._jobs.put_nowait((operation, future))
            except Full:
                raise RabbitMQUnavailable() from None
        return future.result()

    def _disconnect(self):
        connection, self._connection, self._channel = self._connection, None, None
        if connection is not None and connection.is_open:
            try:
                connection.close()
            except Exception:
                pass

    def _ensure_channel(self):
        if self._connection is not None and self._connection.is_open and self._channel.is_open:
            return
        self._disconnect()
        parameters = pika.URLParameters(self.settings.rabbitmq_url.get_secret_value())
        timeout = self.settings.rabbitmq_publish_timeout_seconds
        parameters.connection_attempts = 1
        parameters.socket_timeout = timeout
        parameters.stack_timeout = timeout + 1
        parameters.blocked_connection_timeout = timeout
        parameters.heartbeat = 30
        self._connection = self._connect(parameters)
        self._channel = self._connection.channel()
        # Bound waits for topology RPCs as well as publisher confirms.
        timer = self._connection.call_later(timeout, self._timeout)
        try:
            declare_topology(self._channel, self.settings)
            self._channel.confirm_delivery()
        finally:
            self._connection.remove_timeout(timer)

    @staticmethod
    def _timeout():
        raise TimeoutError("RabbitMQ operation timed out")

    def _publish(self, message: AnalysisMessage):
        for attempt in range(self.settings.rabbitmq_publish_max_attempts):
            try:
                self._ensure_channel()
                timer = self._connection.call_later(self.settings.rabbitmq_publish_timeout_seconds, self._timeout)
                try:
                    self._channel.basic_publish(
                        exchange=self.settings.rabbitmq_exchange, routing_key=RUN_KEY,
                        body=message.model_dump_json().encode("utf-8"), mandatory=True,
                        properties=pika.BasicProperties(
                            content_type="application/json", delivery_mode=2, type=message.type,
                            message_id=str(message.message_id), headers={"retry_count": message.retry_count},
                        ),
                    )
                finally:
                    self._connection.remove_timeout(timer)
                return
            except Exception:
                # Never propagate library errors containing connection parameters/credentials.
                self._disconnect()
                if attempt + 1 < self.settings.rabbitmq_publish_max_attempts:
                    self._sleep(0.2 * 2 ** attempt)
        raise RabbitMQPublishFailed() from None

    def publish_analysis(self, task_id: UUID) -> None:
        message = AnalysisMessage(task_id=task_id)
        self._call(lambda: self._publish(message))

    def _probe(self):
        try:
            self._ensure_channel()
            timer = self._connection.call_later(self.settings.rabbitmq_publish_timeout_seconds, self._timeout)
            try:
                self._channel.exchange_declare(exchange=self.settings.rabbitmq_exchange, passive=True)
            finally:
                self._connection.remove_timeout(timer)
        except Exception:
            self._disconnect()
            raise RabbitMQUnavailable() from None

    def check_health(self) -> None:
        self._call(self._probe)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        future = Future()
        self._jobs.put((None, future))
        future.result()
        self._thread.join()
