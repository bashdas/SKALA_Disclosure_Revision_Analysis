FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY shared /shared
RUN pip install --no-cache-dir /shared
COPY mcp/rag-mcp/pyproject.toml ./
COPY mcp/rag-mcp/app ./app
RUN pip install --no-cache-dir . && useradd --create-home appuser
USER appuser
EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
