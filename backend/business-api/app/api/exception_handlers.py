from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.analysis_exceptions import AnalysisError, AnalysisAlreadyRunning
from app.domain.auth_exceptions import AuthError
from app.domain.memo_upload_exceptions import MemoUploadError
from app.domain.resource_exceptions import ResourceNotFound


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


async def resource_not_found_handler(request: Request, exc: ResourceNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": {"code": exc.code, "message": exc.message}})


async def memo_upload_error_handler(request: Request, exc: MemoUploadError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


async def analysis_error_handler(request: Request, exc: AnalysisError) -> JSONResponse:
    error = {"code": exc.code, "message": exc.message}
    if isinstance(exc, AnalysisAlreadyRunning):
        error["existing_task_id"] = str(exc.existing_task_id)
    return JSONResponse(status_code=exc.status_code, content={"error": error})


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AnalysisError, analysis_error_handler)
    app.add_exception_handler(AuthError, auth_error_handler)
    app.add_exception_handler(MemoUploadError, memo_upload_error_handler)
    app.add_exception_handler(ResourceNotFound, resource_not_found_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
