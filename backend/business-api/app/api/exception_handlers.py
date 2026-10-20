from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.auth_exceptions import AuthError


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    code, message = exc.code, exc.message
    if code == "USER_NOT_FOUND":
        code, message = "INVALID_TOKEN", "Invalid token"
    status = 403 if code == "FORBIDDEN" else 503 if code == "AUTH_CONFIGURATION_ERROR" else 401
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}}, headers=headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Default errors can echo input dictionaries, including passwords. Omit input/context.
    details = [{"loc": error["loc"], "type": error["type"], "msg": error["msg"]} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": details})


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AuthError, auth_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
