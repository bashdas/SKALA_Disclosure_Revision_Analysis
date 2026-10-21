from functools import lru_cache

from pydantic import Field, SecretStr
from disclosure_shared.config import ServiceSettings


class Settings(ServiceSettings):
    external_mcp_url: str = "http://external-mcp:8083/mcp"
    external_mcp_timeout_seconds: float = Field(default=40, ge=1, le=120)
    database_url: str = Field(default="", repr=False)
    database_connect_timeout: int = Field(default=3, ge=1, le=60)
    sse_poll_interval_seconds: float = Field(default=1, ge=0.1, le=60)
    sse_heartbeat_seconds: float = Field(default=15, ge=1, le=300)
    memo_upload_max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    rabbitmq_url: SecretStr = Field(default="", repr=False)
    rabbitmq_analysis_queue: str = Field(default="analysis.tasks", min_length=1, max_length=240)
    rabbitmq_analysis_retry_queue: str = Field(default="analysis.tasks.retry", min_length=1, max_length=240)
    rabbitmq_analysis_dlq: str = Field(default="analysis.tasks.dlq", min_length=1, max_length=240)
    rabbitmq_exchange: str = Field(default="analysis.exchange", min_length=1, max_length=240)
    rabbitmq_max_retries: int = Field(default=3, ge=1, le=10)
    rabbitmq_retry_delay_seconds: int = Field(default=5, ge=1, le=60)
    rabbitmq_publish_max_attempts: int = Field(default=3, ge=1, le=5)
    rabbitmq_publish_timeout_seconds: float = Field(default=5, ge=1, le=30)
    internal_api_key: SecretStr = Field(default="", repr=False)
    internal_report_save_max_attempts: int = Field(default=3, ge=1, le=5)
    jwt_secret_key: SecretStr = Field(default="", repr=False)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=30, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
