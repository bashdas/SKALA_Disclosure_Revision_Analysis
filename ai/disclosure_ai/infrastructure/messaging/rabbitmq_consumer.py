import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import pika

from disclosure_ai.infrastructure.mcp.client import (
    BusinessError,
)


def consume(state: Path, process_message, Message):
    exchange = os.environ.get("RABBITMQ_EXCHANGE", "analysis.exchange")
    queue = os.environ.get("RABBITMQ_ANALYSIS_QUEUE", "analysis.tasks")
    max_retries = int(os.environ.get("RABBITMQ_MAX_RETRIES", "3"))
    if not 1 <= max_retries <= 10:
        raise ValueError("INVALID_RETRY_LIMIT")
    parameters = pika.URLParameters(os.environ["RABBITMQ_URL"])
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 10
    parameters.socket_timeout = 10
    with ThreadPoolExecutor(max_workers=1) as executor:
        while True:
            connection = None
            try:
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                # 큐와 재시도 TTL은 백엔드 Producer가 선언한 구성을 그대로 사용합니다.
                channel.queue_declare(queue=queue, passive=True)
                channel.confirm_delivery()
                channel.basic_qos(prefetch_count=1)

                def settle(
                    delivery_tag, raw, message, future, channel=channel, connection=connection
                ):
                    if not channel.is_open:
                        return
                    try:
                        result = future.result()
                        print(
                            json.dumps(
                                {"task_id": str(message.task_id), "status": result["status"]}
                            ),
                            flush=True,
                        )
                    except Exception as error:
                        attempt = message.retry_count + 1
                        retryable = not isinstance(error, BusinessError) or error.retryable
                        target = (
                            f"analysis.retry.{attempt}"
                            if retryable and attempt <= max_retries
                            else "analysis.dead"
                        )
                        payload = (
                            message.model_copy(update={"retry_count": attempt})
                            .model_dump_json()
                            .encode()
                        )
                        try:
                            channel.basic_publish(
                                exchange=exchange,
                                routing_key=target,
                                body=payload,
                                mandatory=True,
                                properties=pika.BasicProperties(
                                    content_type="application/json",
                                    delivery_mode=2,
                                    message_id=str(message.message_id),
                                    type=message.type,
                                    headers={"retry_count": attempt},
                                ),
                            )
                        except Exception:
                            # 재발행 확인을 받지 못하면 원본 ack를 보내지 않아 유실을 막습니다.
                            connection.close()
                            return
                        print(
                            json.dumps(
                                {
                                    "task_id": str(message.task_id),
                                    "status": target,
                                    "error": type(error).__name__,
                                }
                            ),
                            flush=True,
                        )
                    channel.basic_ack(delivery_tag=delivery_tag)

                def receive(
                    _channel, method, properties, raw, connection=connection, settle=settle
                ):
                    try:
                        if len(raw) > 16384:
                            raise ValueError("MESSAGE_TOO_LARGE")
                        message = Message.model_validate_json(raw)
                    except ValueError:
                        # 잘못된 메시지는 분석하거나 무한 재시도하지 않고 기존 DLQ로 보냅니다.
                        _channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
                        return
                    future = executor.submit(
                        asyncio.run, process_message(message, state, max_retries)
                    )

                    def done(completed):
                        try:
                            connection.add_callback_threadsafe(
                                partial(settle, method.delivery_tag, raw, message, completed)
                            )
                        except pika.exceptions.ConnectionWrongStateError:
                            pass

                    future.add_done_callback(done)

                channel.basic_consume(queue=queue, on_message_callback=receive, auto_ack=False)
                channel.start_consuming()
            except KeyboardInterrupt:
                return
            except Exception as error:
                print(
                    json.dumps({"status": "BROKER_RECONNECT", "error": type(error).__name__}),
                    flush=True,
                )
                time.sleep(2)
            finally:
                if connection is not None and connection.is_open:
                    connection.close()
