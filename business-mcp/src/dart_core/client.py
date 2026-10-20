"""OpenDART HTTP 클라이언트 (list.json, corpCode.xml, document.xml).

- API 키는 `_KeyTransport`가 전송 직전에만 URL에 붙입니다. httpx의 요청 로그·Response.request·예외는
  키가 없는 원래 요청을 가리키므로 키가 로그나 예외 메시지에 남지 않습니다.
- 재시도(05 §6): 네트워크·타임아웃·HTTP 5xx 최대 3회(0.5s, 1s, 2s), 상태 800 최대 2회, 900 1회.
- 020 / HTTP 429: 재시도하지 않고 쿨다운. 쿨다운 동안은 네트워크 없이 바로 DartRateLimited.
- 리다이렉트는 따라가지 않습니다(키 없는 요청은 error1.html로 302 → 정상 데이터로 오인 방지).
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Self

import httpx
from lxml import etree

from dart_core.status import (
    NO_DATA,
    RETRIES,
    DartAuthError,
    DartError,
    DartNotFound,
    DartRateLimited,
    DartUnavailable,
    check_status,
)

BASE_URL = "https://opendart.fss.or.kr"
ZIP_MAGIC = b"PK\x03\x04"
ALLOWED_BASE = re.compile(r"^(https://opendart\.fss\.or\.kr|http://(127\.0\.0\.1|localhost)(:\d+)?)/?$")
logger = logging.getLogger(__name__)


class _KeyTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, key: str):
        self._inner = inner
        self._key = key

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        keyed = httpx.Request(
            request.method, request.url.copy_merge_params({"crtfc_key": self._key}),
            headers=request.headers, stream=request.stream, extensions=request.extensions,
        )
        return await self._inner.handle_async_request(keyed)

    async def aclose(self) -> None:
        await self._inner.aclose()


class DartClient:
    """DartClient는 자신이 만든 httpx.AsyncClient를 소유하고 aclose()에서 닫습니다.

    transport를 넘기면(테스트의 httpx.MockTransport 등) 그 transport도 함께 닫힙니다.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
        max_concurrency: int = 2,
        retry_delays: tuple[float, ...] = (0.5, 1.0, 2.0),
        rate_limit_cooldown: float = 300.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not api_key:
            raise DartAuthError(None, "OPENDART_API_KEY가 비어 있습니다.")
        if not ALLOWED_BASE.match(base_url):  # 키가 공식 주소·로컬 재생 서버 밖으로 나가지 않게 함
            raise DartAuthError(None, "base_url은 https://opendart.fss.or.kr 또는 http://127.0.0.1/localhost만 허용합니다.")
        self._http = httpx.AsyncClient(
            base_url=base_url,
            transport=_KeyTransport(transport or httpx.AsyncHTTPTransport(), api_key),
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            follow_redirects=False,
            headers={"User-Agent": "gongsi-business-mcp/0.1"},
        )
        self._sem = asyncio.Semaphore(max_concurrency)
        self._retry_delays = retry_delays
        self._cooldown = rate_limit_cooldown
        self._cooldown_until = 0.0
        self._sleep = sleep
        self._clock = clock
        self.request_count = 0  # 실제로 전송한 요청 수 (테스트·운영 확인용)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ── 공개 메서드 ──────────────────────────────────────────────────────

    async def get_json(self, path: str, params: dict) -> dict:
        """JSON API. 정상이면 본문 dict, 013이면 {"status": "013", "list": [], "total_count": 0, "total_page": 0}."""

        def interpret(r: httpx.Response) -> dict:
            if _looks_like_html(r):
                raise DartUnavailable(None, f"{path}: JSON 대신 HTML 응답")
            try:
                data = r.json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise DartUnavailable(None, f"{path}: JSON 본문을 해석할 수 없음") from None
            if not isinstance(data, dict) or "status" not in data:
                raise DartUnavailable(None, f"{path}: status 없는 응답")
            if not check_status(str(data["status"]), str(data.get("message", ""))):
                return {"status": NO_DATA, "list": [], "total_count": 0, "total_page": 0}
            return data

        return await self._request(path, params, interpret)

    async def get_zip(self, path: str, params: dict) -> bytes:
        """ZIP 바이너리 API(document.xml, corpCode.xml). 오류 본문(XML)이면 상태코드 예외, 013/014는 DartNotFound."""

        def interpret(r: httpx.Response) -> bytes:
            body = r.content
            if body[:4] == ZIP_MAGIC:
                return body
            if _looks_like_html(r):
                raise DartUnavailable(None, f"{path}: ZIP 대신 HTML 응답")
            try:
                root = etree.fromstring(body, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
            except etree.XMLSyntaxError:
                raise DartUnavailable(None, f"{path}: ZIP도 오류 XML도 아닌 응답") from None
            status, message = root.findtext(".//status"), root.findtext(".//message") or ""
            if status is None:
                raise DartUnavailable(None, f"{path}: status 없는 XML 응답")
            if not check_status(status, message):  # 오류 코드는 여기서 예외 (014 → DartNotFound)
                raise DartNotFound(status, f"{path}: 파일 없음 (OpenDART {status})")
            raise DartUnavailable(status, f"{path}: 상태 000인데 ZIP이 아닌 응답")

        return await self._request(path, params, interpret)

    # ── 내부 ─────────────────────────────────────────────────────────────

    def _check_cooldown(self, path: str) -> None:
        remaining = self._cooldown_until - self._clock()
        if remaining > 0:
            raise DartRateLimited("020", f"{path}: 요청 제한 쿨다운 중 ({remaining:.0f}초 남음)",
                                  cooldown_seconds=round(remaining))

    def _start_cooldown(self, seconds: float | None = None) -> None:
        self._cooldown_until = self._clock() + max(seconds or 0, self._cooldown)

    async def _request(self, path: str, params: dict, interpret: Callable[[httpx.Response], object]):
        params = {k: v for k, v in params.items() if v is not None}
        network_retries = 0
        status_retries: dict[str, int] = {}
        while True:
            self._check_cooldown(path)
            try:
                async with self._sem:
                    self.request_count += 1
                    r = await self._http.get(path, params=params)
                if r.status_code == 429:
                    retry_after = _retry_after(r)
                    self._start_cooldown(retry_after)
                    raise DartRateLimited(None, f"{path}: HTTP 429", cooldown_seconds=round(self._cooldown))
                if r.status_code >= 500:
                    raise _Transient(f"HTTP {r.status_code}")
                if 300 <= r.status_code < 400:
                    raise DartUnavailable(None, f"{path}: 예상하지 못한 리다이렉트 HTTP {r.status_code}")
                if r.status_code in (401, 403):
                    raise DartAuthError(None, f"{path}: HTTP {r.status_code}")
                if r.status_code >= 400:
                    raise DartUnavailable(None, f"{path}: HTTP {r.status_code}")
                return interpret(r)
            except (httpx.TransportError, _Transient) as e:
                if network_retries >= len(self._retry_delays):
                    reason = str(e) if isinstance(e, _Transient) else type(e).__name__
                    raise DartUnavailable(None, f"{path} 호출 실패: {reason}") from None  # URL(키) 미포함
                await self._sleep(self._retry_delays[network_retries])
                network_retries += 1
            except DartRateLimited as e:
                if e.status == "020":  # OpenDART 상태 020: 쿨다운을 걸고 재시도하지 않음
                    self._start_cooldown()
                    raise DartRateLimited("020", f"{path}: OpenDART 요청 제한 초과",
                                          cooldown_seconds=round(self._cooldown)) from None
                raise
            except DartError as e:
                limit = RETRIES.get(e.status or "", 0)
                done = status_retries.get(e.status or "", 0)
                if done >= limit:
                    raise
                status_retries[e.status] = done + 1
                await self._sleep(self._retry_delays[min(done, len(self._retry_delays) - 1)])


class _Transient(Exception):
    """재시도 대상(HTTP 5xx). 바깥으로는 DartUnavailable로 바뀝니다."""


def _looks_like_html(r: httpx.Response) -> bool:
    ctype = r.headers.get("content-type", "").lower()
    head = r.content[:200].lstrip().lower()
    return "text/html" in ctype or head.startswith((b"<!doctype html", b"<html"))


def _retry_after(r: httpx.Response) -> float | None:
    try:
        return float(r.headers.get("retry-after", ""))
    except ValueError:
        return None

