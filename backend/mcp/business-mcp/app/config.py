from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from disclosure_shared.config import ServiceSettings


class Settings(ServiceSettings):
    business_api_base_url: str = "http://business-api:8080"
    internal_api_key: SecretStr = Field(default="", repr=False)
    business_mcp_host: str = "0.0.0.0"
    business_mcp_port: int = Field(default=8081, ge=1, le=65535)
    business_mcp_request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "business-mcp:*"]

    @field_validator("business_api_base_url")
    @classmethod
    def valid_base_url(cls, value):
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Business API base URL must be HTTP(S) without credentials/query/fragment")
        return value.rstrip("/")
