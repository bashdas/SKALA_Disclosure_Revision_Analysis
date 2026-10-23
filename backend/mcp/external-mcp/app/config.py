from typing import Literal
from urllib.parse import urlsplit

from disclosure_shared.config import ServiceSettings
from pydantic import Field, SecretStr, field_validator


class Settings(ServiceSettings):
    naver_client_id: SecretStr = SecretStr("")
    naver_client_secret: SecretStr = SecretStr("")
    naver_api_provider: Literal["hub", "legacy"] = "hub"
    news_usage_authorization: str = ""
    sec_user_agent: str = "DisclosureResearch/1.0"
    opendart_api_key: SecretStr = Field(default="", repr=False)
    serpapi_api_key: SecretStr = Field(default="", repr=False)
    opendart_base_url: str = "https://opendart.fss.or.kr/api"
    external_mcp_host: str = "0.0.0.0"
    external_mcp_port: int = Field(default=8083, ge=1, le=65535)
    external_mcp_request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    opendart_max_download_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    opendart_metadata_max_pages: int = Field(default=100, ge=1, le=1000)
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "external-mcp:*"]

    @field_validator("opendart_base_url")
    @classmethod
    def validate_base(cls, value):
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("OpenDART URL must be HTTPS without credentials/query/fragment")
        return value.rstrip("/") + "/"
