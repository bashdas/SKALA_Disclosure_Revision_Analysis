from typing import NotRequired, TypedDict


class Evidence(TypedDict):
    document_id: str
    location: str
    quote: str
    url: NotRequired[str | None]
    published_at: NotRequired[str | None]
