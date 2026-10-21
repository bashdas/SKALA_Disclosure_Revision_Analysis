FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY pyproject.toml ./
COPY disclosure_ai ./disclosure_ai
RUN pip install --no-cache-dir . && useradd --create-home appuser && mkdir /state && chown appuser:appuser /state
ENV XDG_CACHE_HOME=/state/cache
USER appuser
CMD ["python", "-m", "disclosure_ai.entrypoints.worker", "--state", "/state/ai-state.sqlite"]
