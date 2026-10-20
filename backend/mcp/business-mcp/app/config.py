from disclosure_shared.config import ServiceSettings


class Settings(ServiceSettings):
    business_api_base_url: str = "http://business-api:8080"
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "business-mcp:*"]
