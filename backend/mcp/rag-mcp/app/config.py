from disclosure_shared.config import ServiceSettings


class Settings(ServiceSettings):
    database_url: str = ""
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "rag-mcp:*"]
