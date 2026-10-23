from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_auth_service, get_user_service
from app.schemas.user import SignupRequest, SignupResponse
from app.services.user import UserService
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, service: Annotated[AuthService, Depends(get_auth_service)]) -> TokenResponse:
    user = service.authenticate(request.email, request.password.get_secret_value())
    return service.create_token(user)


@router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(request: SignupRequest, service: Annotated[UserService, Depends(get_user_service)]) -> SignupResponse:
    return service.signup(str(request.email), request.password.get_secret_value(), request.organization_name, request.name, request.role)
