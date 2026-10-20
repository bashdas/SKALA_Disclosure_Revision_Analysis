import math
from typing import Protocol

import httpx

from app.errors import RagError

DIMENSION = 1536


class EmbeddingService(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def validate_vectors(vectors, count):
    if len(vectors) != count or any(
        len(v) != DIMENSION or not all(math.isfinite(x) for x in v)
        or not any(x != 0 for x in v) for v in vectors
    ):
        raise RagError("EMBEDDING_FAILED", "Invalid embedding response")
    return vectors


class OpenAIEmbeddingService:
    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str):
        self.client, self.api_key, self.model = client, api_key, model

    async def embed(self, texts):
        if not self.api_key:
            raise RagError("EMBEDDING_UNAVAILABLE", "Embedding API key is not configured")
        vectors = []
        try:
            for start in range(0, len(texts), 32):
                batch = texts[start:start + 32]
                response = await self.client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": batch, "encoding_format": "float"},
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item["index"])
                if [item["index"] for item in data] != list(range(len(batch))):
                    raise ValueError("Invalid indexes")
                vectors.extend(validate_vectors([item["embedding"] for item in data], len(batch)))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
            raise RagError("EMBEDDING_FAILED", "Embedding provider request failed") from None
        return vectors
