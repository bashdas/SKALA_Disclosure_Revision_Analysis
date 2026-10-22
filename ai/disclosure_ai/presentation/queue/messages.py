from typing import Literal
from uuid import UUID

from pydantic import Field

from disclosure_ai.domain.models.base import Model


class Message(Model):
    message_id: UUID
    task_id: UUID
    type: Literal["RUN_ANALYSIS"]
    retry_count: int = Field(ge=0)
