from secrets import compare_digest
from typing import Annotated

from fastapi import Depends
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.domain.internal_exceptions import InternalAPIError
from app.services.internal_analysis import InternalAnalysisService

_key_header = APIKeyHeader(name="X-Internal-API-Key", auto_error=False, scheme_name="InternalAPIKey")


def verify_internal_api_key(
    key: Annotated[str | None, Depends(_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not key:
        raise InternalAPIError("INTERNAL_UNAUTHENTICATED", "Internal authentication required", 401)
    expected = settings.internal_api_key.get_secret_value()
    if len(expected.encode("utf-8")) < 32 or expected.lower().startswith("change-me"):
        raise InternalAPIError("INTERNAL_AUTH_CONFIGURATION_ERROR", "Internal authentication unavailable", 503)
    if not compare_digest(key.encode("utf-8"), expected.encode("utf-8")):
        raise InternalAPIError("INTERNAL_UNAUTHENTICATED", "Internal authentication required", 401)


def get_internal_analysis_service(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InternalAnalysisService:
    return InternalAnalysisService(session, settings)
