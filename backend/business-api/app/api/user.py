from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_current_user, get_token_payload, get_user_service
from app.schemas.auth import CurrentUser, TokenPayload
from app.schemas.user import (
    AccountDeleteRequest,
    NameChangeRequest,
    PasswordChangeRequest,
    UserResponse,
)
from app.services.user import UserService

router = APIRouter(prefix="/api/v1/users", tags=["users"])
Principal = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[UserService, Depends(get_user_service)]


@router.get("/me", response_model=UserResponse)
def get_me(user: Principal, service: Service) -> UserResponse:
    return service.get_me(user)


@router.patch("/me/password", status_code=204)
def change_password(request: PasswordChangeRequest, user: Principal,
    payload: Annotated[TokenPayload, Depends(get_token_payload)], service: Service) -> Response:
    service.change_password(user, payload, request.current_password.get_secret_value(), request.new_password.get_secret_value())
    return Response(status_code=204)


@router.patch("/me", response_model=UserResponse)
def update_name(request: NameChangeRequest, user: Principal,
    payload: Annotated[TokenPayload, Depends(get_token_payload)], service: Service) -> UserResponse:
    return service.update_name(user, payload, request.name)


@router.delete("/me", status_code=204)
def delete_account(request: AccountDeleteRequest, user: Principal,
    payload: Annotated[TokenPayload, Depends(get_token_payload)], service: Service) -> Response:
    service.delete_account(user, payload, request.password.get_secret_value())
    return Response(status_code=204)
