from typing import Literal

from disclosure_shared.config import ServiceSettings
from pydantic import Field, SecretStr, model_validator


class Settings(ServiceSettings):
    database_url: str = ""
    business_mcp_url: str = "http://business-mcp:8081/mcp"
    external_mcp_url: str = "http://external-mcp:8083/mcp"
    rag_mcp_host: str = "0.0.0.0"
    rag_mcp_port: int = 8082
    rag_mcp_request_timeout_seconds: float = Field(default=60, gt=0)
    rag_chunk_size: int = Field(default=1000, ge=100, le=2000)
    rag_chunk_overlap: int = Field(default=100, ge=0)
    rag_min_similarity: float = Field(default=0.6, ge=0, le=1)
    rag_embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    openai_api_key: SecretStr = SecretStr("")
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "rag-mcp:*"]

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("chunk overlap must be smaller than chunk size")
        return self
