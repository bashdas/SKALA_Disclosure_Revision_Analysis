from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db, get_session_factory
from app.core.security import decode_access_token
from app.domain.auth_exceptions import Forbidden, InvalidToken, Unauthenticated, UserNotFound
from app.models.enums import UserRole
from app.infrastructure.analysis_queue import AnalysisQueueProducer
from app.repositories import AnalysisRepository, FilingRepository, MemoRepository, UserRepository
from app.services.analysis import AnalysisService
from app.services.analysis_stream import AnalysisEventStream
from app.schemas.auth import CurrentUser, TokenPayload
from app.services.auth import AuthService
from app.services.user import UserService
from app.services.filing import FilingService
from app.services.memo import MemoService

_bearer = HTTPBearer(auto_error=False)


def get_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPayload:
    if credentials is None:
        raise Unauthenticated()
    return decode_access_token(credentials.credentials, settings=settings)


def get_current_user(
    payload: Annotated[TokenPayload, Depends(get_token_payload)],
    session: Annotated[Session, Depends(get_db)],
) -> CurrentUser:
    # Token validation precedes opening the DB dependency; claims are not authority.
    user = UserRepository(session).get_by_id(payload.sub)
    if user is None:
        raise UserNotFound()
    if (user.organization_id != payload.organization_id or user.role != payload.role
            or user.token_version != payload.token_version):
        raise InvalidToken()
    return CurrentUser(id=user.id, organization_id=user.organization_id, email=user.email, role=user.role)


def get_current_organization_id(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> UUID:
    return current_user.organization_id


def require_roles(*roles: UserRole, user_dependency=get_current_user):
    allowed = frozenset(UserRole(role) for role in roles)
    if not allowed:
        raise ValueError("require_roles needs at least one allowed role")

    def check_role(current_user: Annotated[CurrentUser, Depends(user_dependency)]) -> CurrentUser:
        if current_user.role not in allowed:
            raise Forbidden()
        return current_user

    return check_role


def get_auth_service(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(UserRepository(session), settings)



def get_filing_service(session: Annotated[Session, Depends(get_db)]) -> FilingService:
    return FilingService(FilingRepository(session))


def get_memo_service(session: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]) -> MemoService:
    return MemoService(MemoRepository(session), max_upload_bytes=settings.memo_upload_max_bytes)


def get_analysis_producer(request: Request) -> AnalysisQueueProducer:
    return request.app.state.analysis_producer


def get_analysis_service(
    session: Annotated[Session, Depends(get_db)],
    producer: Annotated[AnalysisQueueProducer, Depends(get_analysis_producer)],
) -> AnalysisService:
    return AnalysisService(AnalysisRepository(session), MemoRepository(session), producer)


def get_stream_session_factory() -> Callable[[], Session]:
    return get_session_factory()


def get_stream_current_user(
    payload: Annotated[TokenPayload, Depends(get_token_payload)],
    factory: Annotated[Callable[[], Session], Depends(get_stream_session_factory)],
) -> CurrentUser:
    # Reuse normal DB-backed authentication without a yield/request-scoped Session.
    with factory() as session:
        return get_current_user(payload, session)


def get_analysis_stream(
    factory: Annotated[Callable[[], Session], Depends(get_stream_session_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisEventStream:
    return AnalysisEventStream(factory, poll_interval=settings.sse_poll_interval_seconds,
        heartbeat_seconds=settings.sse_heartbeat_seconds)


def get_user_service(session: Annotated[Session, Depends(get_db)]) -> UserService:
    return UserService(UserRepository(session))
