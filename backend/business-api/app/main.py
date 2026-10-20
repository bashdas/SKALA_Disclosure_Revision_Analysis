from fastapi import FastAPI
from disclosure_shared.health import HealthResponse
from app.core.config import Settings

settings = Settings()

app = FastAPI(title="business-api", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(service="business-api")
