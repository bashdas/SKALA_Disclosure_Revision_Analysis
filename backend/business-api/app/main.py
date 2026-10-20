from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from disclosure_shared.health import HealthResponse

from app.core.config import get_settings
from app.core.database import DatabaseConfigurationError, get_db

settings = get_settings()

app = FastAPI(title="business-api", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(service="business-api")


@app.get("/health/db", response_model=HealthResponse)
def database_health() -> HealthResponse:
    try:
        with contextmanager(get_db)() as session:
            session.execute(text("SELECT 1"))
    except (DatabaseConfigurationError, SQLAlchemyError):
        # Never expose connection strings, credentials, or driver errors to clients.
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return HealthResponse(service="business-api-db")
