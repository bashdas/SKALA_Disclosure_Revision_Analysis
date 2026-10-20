FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY shared /shared
RUN pip install --no-cache-dir /shared
COPY mcp/rag-mcp/pyproject.toml ./
COPY mcp/rag-mcp/app ./app
COPY mcp/rag-mcp/alembic ./alembic
COPY mcp/rag-mcp/alembic.ini ./alembic.ini
RUN pip install --no-cache-dir . && useradd --create-home appuser
USER appuser
EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('RAG_MCP_PORT', '8082') + '/health', timeout=2)"
CMD ["python", "-m", "app"]
