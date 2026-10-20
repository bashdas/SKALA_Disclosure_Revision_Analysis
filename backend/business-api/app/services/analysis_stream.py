from collections.abc import Callable
from dataclasses import dataclass
import re
from time import monotonic
from uuid import UUID

import anyio
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import DatabaseConfigurationError
from app.domain.analysis_exceptions import AnalysisNotFound, InvalidLastEventID
from app.domain.analysis_state_machine import TERMINAL_ANALYSIS_STATUSES
from app.repositories import AnalysisEventRepository, AnalysisRepository
from app.schemas.analysis import AnalysisEventResponse

BATCH_SIZE = 200
MAX_SEQUENCE = 2147483647


def resolve_after_sequence(after_sequence: int | None, last_event_id: str | None) -> int:
    if after_sequence is not None:
        return after_sequence
    if last_event_id is None:
        return 0
    if not re.fullmatch(r"[0-9]{1,10}", last_event_id) or int(last_event_id) > MAX_SEQUENCE:
        raise InvalidLastEventID()
    return int(last_event_id)


@dataclass(frozen=True)
class EventSnapshot:
    events: list[AnalysisEventResponse]
    terminal: bool


def encode_event(event: AnalysisEventResponse) -> str:
    # JSON escaping prevents embedded newlines in summary strings from injecting frames.
    event_name = event.event_type if re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", event.event_type) else "message"
    return f"id: {event.sequence}\nevent: {event_name}\ndata: {event.model_dump_json()}\n\n"


class AnalysisEventStream:
    def __init__(self, session_factory: Callable[[], Session], *, poll_interval: float, heartbeat_seconds: float,
                 clock=monotonic, sleeper=anyio.sleep):
        self.session_factory = session_factory
        self.poll_interval = poll_interval
        self.heartbeat_seconds = heartbeat_seconds
        self.clock, self.sleep = clock, sleeper

    def snapshot(self, task_id: UUID, organization_id: UUID, after_sequence: int) -> EventSnapshot:
        # All ORM work and DTO materialization finish before returning, including auth's
        # separate session. No connection/transaction is retained while sending/sleeping.
        with self.session_factory() as session:
            task = AnalysisRepository(session).get_by_id_and_organization(task_id, organization_id)
            if task is None:
                raise AnalysisNotFound()
            rows = AnalysisEventRepository(session).list_after_sequence(task_id, after_sequence, limit=BATCH_SIZE)
            return EventSnapshot([AnalysisEventResponse.model_validate(row) for row in rows], task.status in TERMINAL_ANALYSIS_STATUSES)

    async def stream(self, request: Request, task_id: UUID, organization_id: UUID, after_sequence: int, initial: EventSnapshot):
        cursor, snapshot = after_sequence, initial
        last_output = self.clock()
        while not await request.is_disconnected():
            for event in snapshot.events:
                if await request.is_disconnected():
                    return
                yield encode_event(event)
                cursor = event.sequence
                last_output = self.clock()
            if snapshot.terminal and len(snapshot.events) < BATCH_SIZE:
                return
            # Drain a large backlog without waiting between full batches.
            if len(snapshot.events) < BATCH_SIZE:
                if self.clock() - last_output >= self.heartbeat_seconds:
                    yield ": heartbeat\n\n"
                    last_output = self.clock()
                await self.sleep(self.poll_interval)
                if await request.is_disconnected():
                    return
            try:
                snapshot = await run_in_threadpool(self.snapshot, task_id, organization_id, cursor)
            except (SQLAlchemyError, DatabaseConfigurationError, AnalysisNotFound):
                # Headers are already sent: close safely, let client reconnect at its last ID.
                yield ": stream unavailable; reconnect\n\n"
                return
