"""오류 코드와 ToolError(JSON) 변환 경계 (docs/05 §1-2).

예상 가능한 업무 결과(후보 다수, 결과 없음)는 오류가 아니라 정상 응답의 상태값입니다.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import Middleware, MiddlewareContext

from dart_core.status import DartError

logger = logging.getLogger(__name__)


class DomainError(Exception):
    code = "INTERNAL"
    retryable = False

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable, "details": self.details}


class InvalidArgument(DomainError):
    code = "INVALID_ARGUMENT"


class CompanyNotFound(DomainError):
    code = "COMPANY_NOT_FOUND"


class FilingNotFound(DomainError):
    code = "FILING_NOT_FOUND"


class NotACorrection(DomainError):
    code = "NOT_A_CORRECTION"


class MemoNotFound(DomainError):
    code = "MEMO_NOT_FOUND"


class VersionConflict(DomainError):
    code = "VERSION_CONFLICT"


class NotImplementedYet(DomainError):
    code = "NOT_IMPLEMENTED"


class UpstreamNotConfigured(DomainError):
    """live 모드 설정 문제(키 없음·형식 오류). 운영자 조치가 필요해 UPSTREAM_AUTH로 보고합니다."""

    code = "UPSTREAM_AUTH"


def _tool_error(body: dict) -> ToolError:
    return ToolError(json.dumps({"error": body}, ensure_ascii=False))


@contextmanager
def tool_errors() -> Iterator[None]:
    """Tool 본문을 감싸 도메인·dart_core 예외를 ToolError(JSON)로 바꿉니다."""
    try:
        yield
    except ToolError:
        raise
    except DomainError as e:
        raise _tool_error(e.to_dict()) from None
    except DartError as e:
        raise _tool_error({"code": e.code, "message": str(e), "retryable": e.retryable,
                           "details": {"dart_status": e.status, **e.details}}) from None
    except Exception:
        logger.exception("unexpected error in tool")  # 스택트레이스는 서버 로그에만
        raise _tool_error(
            {"code": "INTERNAL", "message": "서버 내부 오류가 발생했습니다.", "retryable": False, "details": {}}
        ) from None


class ArgumentErrorMiddleware(Middleware):
    """FastMCP 인자 검증 실패(pydantic)를 INVALID_ARGUMENT 오류 JSON으로 바꿉니다. 입력값은 담지 않습니다."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        try:
            return await call_next(context)
        except ValidationError as e:
            cause = e.__cause__
            errors = []
            if hasattr(cause, "errors"):
                errors = [
                    {"loc": ".".join(str(p) for p in err["loc"]), "type": err["type"], "msg": err["msg"]}
                    for err in cause.errors(include_url=False, include_context=False, include_input=False)
                ]
            raise _tool_error(
                {
                    "code": "INVALID_ARGUMENT",
                    "message": "입력 형식이 계약과 맞지 않습니다.",
                    "retryable": False,
                    "details": {"tool": context.message.name, "errors": errors},
                }
            ) from None
