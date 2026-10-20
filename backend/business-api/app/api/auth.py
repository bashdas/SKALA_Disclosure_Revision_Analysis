from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_auth_service
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, service: Annotated[AuthService, Depends(get_auth_service)]) -> TokenResponse:
    user = service.authenticate(request.email, request.password.get_secret_value())
    return service.create_token(user)
