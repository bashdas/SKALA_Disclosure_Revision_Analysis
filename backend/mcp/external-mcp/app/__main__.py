import uvicorn

from app.config import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run("app.main:app", host=settings.external_mcp_host, port=settings.external_mcp_port)
