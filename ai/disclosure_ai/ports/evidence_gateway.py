from typing import Protocol


class EvidenceGateway(Protocol):
    async def call(self, name: str, args: dict) -> dict: ...
