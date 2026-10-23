from typing import Literal

from disclosure_shared.config import ServiceSettings
from pydantic import Field, SecretStr, model_validator


class Settings(ServiceSettings):
    database_url: str = ""
    news_collection_enabled: bool = False
    news_usage_authorization: str = ""
    news_collection_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    news_retention_days: int = Field(default=7, ge=1, le=30)
    news_important_retention_days: int = Field(default=30, ge=1, le=30)
    news_unresolved_retention_hours: int = Field(default=48, ge=1, le=168)
    news_log_retention_days: int = Field(default=14, ge=1, le=90)
    news_max_articles: int = Field(default=50000, ge=100, le=1000000)
    news_max_storage_bytes: int = Field(default=134217728, ge=1048576)
    news_initial_hours: int = Field(default=24, ge=1, le=168)
    news_overlap_hours: int = Field(default=2, ge=1, le=24)
    news_max_lookback_hours: int = Field(default=72, ge=1, le=720)
    news_max_pages: int = Field(default=3, ge=1, le=10)
    news_company_call_budget: int = Field(default=120, ge=1, le=200)
    news_macro_call_budget: int = Field(default=30, ge=1, le=50)
    news_daily_call_budget: int = Field(default=6000, ge=1, le=25000)
    news_topics: list[str] = ["기준금리", "원달러 환율", "물가", "국제유가 원자재", "무역 관세", "산업 정책 공급망"]
    news_company_aliases: dict[str, list[str]] = {}
    news_company_industries: dict[str, list[str]] = {}
    news_classification_model: str = "gpt-5.4-mini"
    news_policy_version: str = "headline-v2"
    news_classification_concurrency: int = Field(default=2, ge=1, le=4)
    news_classification_batch_size: int = Field(default=10, ge=1, le=20)
    news_classification_max_batches: int = Field(default=20, ge=1, le=100)
    news_classification_timeout_seconds: int = Field(default=30, ge=1, le=60)
    news_classification_token_budget: int = Field(default=64000, ge=1000, le=500000)
    news_classification_tokens: int = Field(default=4000, ge=500, le=8000)
    news_classification_retries: int = Field(default=1, ge=0, le=2)
    news_classification_max_attempts: int = Field(default=3, ge=1, le=5)
    news_embedding_enabled: bool = False
    news_stale_hours: int = Field(default=3, ge=1, le=48)
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
