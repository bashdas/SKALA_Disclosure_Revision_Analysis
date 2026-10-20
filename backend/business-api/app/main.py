from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from disclosure_shared.health import HealthResponse

from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.filing import router as filing_router
from app.api.memo import router as memo_router
from app.api.exception_handlers import install_exception_handlers
from app.core.config import get_settings
from app.core.database import DatabaseConfigurationError, get_db
from app.infrastructure.analysis_queue import RabbitMQAnalysisProducer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lazy broker connection lets process health and unrelated APIs survive outages.
    producer = RabbitMQAnalysisProducer(get_settings())
    app.state.analysis_producer = producer
    try:
        yield
    finally:
        await run_in_threadpool(producer.close)


app = FastAPI(title="business-api", version="0.1.0", lifespan=lifespan)
install_exception_handlers(app)
app.include_router(analysis_router)
app.include_router(auth_router)
app.include_router(filing_router)
app.include_router(memo_router)


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


@app.get("/health/rabbitmq", response_model=HealthResponse)
def rabbitmq_health(request: Request) -> HealthResponse:
    request.app.state.analysis_producer.check_health()
    return HealthResponse(service="business-api-rabbitmq")
