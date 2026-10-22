from typing import Protocol


class DisclosureGateway(Protocol):
    async def call(self, name: str, args: dict) -> dict: ...
