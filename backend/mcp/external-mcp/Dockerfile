FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY shared /shared
RUN pip install --no-cache-dir /shared
COPY mcp/external-mcp/pyproject.toml ./
COPY mcp/external-mcp/app ./app
RUN pip install --no-cache-dir . && useradd --create-home appuser
USER appuser
EXPOSE 8083
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; from app.config import Settings; urllib.request.urlopen('http://127.0.0.1:%s/health' % Settings().external_mcp_port, timeout=2)"
CMD ["python", "-m", "app"]
