from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.domain.auth_exceptions import Forbidden, InvalidToken, Unauthenticated, UserNotFound
from app.models.enums import UserRole
from app.repositories import FilingRepository, MemoRepository, UserRepository
from app.schemas.auth import CurrentUser, TokenPayload
from app.services.auth import AuthService
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
    if user.organization_id != payload.organization_id or user.role != payload.role:
        raise InvalidToken()
    return CurrentUser(id=user.id, organization_id=user.organization_id, email=user.email, role=user.role)


def get_current_organization_id(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> UUID:
    return current_user.organization_id


def require_roles(*roles: UserRole):
    allowed = frozenset(UserRole(role) for role in roles)
    if not allowed:
        raise ValueError("require_roles needs at least one allowed role")

    def check_role(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
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
