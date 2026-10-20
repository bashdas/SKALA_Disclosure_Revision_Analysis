from functools import lru_cache

from pydantic import Field
from disclosure_shared.config import ServiceSettings


class Settings(ServiceSettings):
    database_url: str = Field(default="", repr=False)
    database_connect_timeout: int = Field(default=3, ge=1, le=60)
    rabbitmq_url: str = ""
    rabbitmq_analysis_queue: str = "analysis.tasks"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
