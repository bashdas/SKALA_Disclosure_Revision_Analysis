"""dart_core가 올리는 예외와 OpenDART 상태코드 매핑 (docs/05 §6, docs/07 §4-1).

Business MCP는 code/retryable/details로 오류 JSON을 만듭니다. 메시지에는 URL·API 키를 넣지 않습니다.
상태코드 의미는 OpenDART 개발가이드 '메시지 설명'(2026-10-20 확인)과 같습니다.
"""


class DartError(Exception):
    code: str = "INTERNAL"
    retryable: bool = False

    def __init__(self, status: str | None, message: str, **details):
        super().__init__(message)
        self.status = status
        self.details = details


class DartAuthError(DartError):
    code = "UPSTREAM_AUTH"


class DartRateLimited(DartError):
    code = "UPSTREAM_RATE_LIMITED"
    retryable = True  # 05 §1-2: true지만 즉시 재시도 금지 (클라이언트가 쿨다운 동안 호출을 막음)


class DartUnavailable(DartError):
    code = "UPSTREAM_UNAVAILABLE"
    retryable = True


class DartNotFound(DartError):
    code = "FILING_NOT_FOUND"


class DartInvalidArgument(DartError):
    code = "INVALID_ARGUMENT"


class DocumentParseError(DartError):
    code = "DOCUMENT_PARSE_FAILED"


OK = "000"
NO_DATA = "013"
_MAP: dict[str, type[DartError]] = {
    "010": DartAuthError, "011": DartAuthError, "012": DartAuthError, "101": DartAuthError, "901": DartAuthError,
    "014": DartNotFound,
    "020": DartRateLimited,
    "021": DartInvalidArgument, "100": DartInvalidArgument,
    "800": DartUnavailable, "900": DartUnavailable,
}
# 상태코드별 추가 재시도 횟수 (05 §6). 나머지는 재시도하지 않음.
RETRIES = {"800": 2, "900": 1}


def check_status(status: str, message: str) -> bool:
    """정상이면 True, 데이터 없음(013)이면 False, 그 밖에는 예외. 알 수 없는 코드는 UPSTREAM_UNAVAILABLE."""
    if status == OK:
        return True
    if status == NO_DATA:
        return False
    cls = _MAP.get(status, DartUnavailable)
    raise cls(status, f"OpenDART {status}: {message}")
