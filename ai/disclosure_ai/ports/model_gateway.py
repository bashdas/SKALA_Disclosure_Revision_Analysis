from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelResponse:
    parsed: Any
    total_tokens: int | None


class ModelFormatError(ValueError):
    pass


class ModelTransportError(RuntimeError):
    def __init__(self, retryable: bool):
        self.retryable = retryable
        super().__init__("MODEL_TRANSPORT_ERROR")


class ModelGateway(Protocol):
    async def parse(
        self, messages: list[dict], schema: type, output_limit: int
    ) -> ModelResponse: ...
    async def close(self) -> None: ...
