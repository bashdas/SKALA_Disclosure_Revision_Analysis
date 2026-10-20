import uvicorn
from app.config import Settings

settings = Settings()
uvicorn.run("app.main:app", host=settings.rag_mcp_host, port=settings.rag_mcp_port)
