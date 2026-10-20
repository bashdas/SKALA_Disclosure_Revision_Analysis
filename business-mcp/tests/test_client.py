"""DartClient: 공식 상태코드, HTTP 오류, 재시도 횟수, 020/429 쿨다운, 비밀값 유출 방지 (네트워크 없음)."""

import asyncio
import io
import logging
import zipfile

import httpx
import pytest

from dart_core.client import DartClient
from dart_core.status import DartAuthError, DartInvalidArgument, DartNotFound, DartRateLimited, DartUnavailable

KEY = "K" * 20 + "9" * 20  # 테스트용 가짜 키 (40자)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(handler, **kw) -> tuple[DartClient, list[httpx.Request], list[float]]:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    async def sleep(s):
        sleeps.append(s)

    client = DartClient(KEY, transport=httpx.MockTransport(wrapped), sleep=sleep, **kw)
    return client, seen, sleeps


def status(code: str, **extra):
    return lambda r: httpx.Response(200, json={"status": code, "message": f"msg {code}", **extra})


def zipped(name="a.xml", data=b"<x/>") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, data)
    return buf.getvalue()


async def test_ok_and_key_added_only_at_transport():
    client, seen, _ = make(status("000", list=[], total_count=0, total_page=0))
    async with client:
        data = await client.get_json("/api/list.json", {"corp_code": "00000001", "page_no": 1, "unused": None})
    assert data["status"] == "000"
    assert seen[0].url.params["crtfc_key"] == KEY and "unused" not in seen[0].url.params


async def test_013_is_empty_result_not_error():
    client, seen, _ = make(status("013"))
    async with client:
        data = await client.get_json("/api/list.json", {})
    assert data == {"status": "013", "list": [], "total_count": 0, "total_page": 0} and len(seen) == 1


@pytest.mark.parametrize("code, exc", [
    ("010", DartAuthError), ("011", DartAuthError), ("012", DartAuthError), ("101", DartAuthError),
    ("901", DartAuthError), ("014", DartNotFound), ("021", DartInvalidArgument), ("100", DartInvalidArgument),
])
async def test_status_mapping_without_retry(code, exc):
    client, seen, _ = make(status(code))
    async with client:
        with pytest.raises(exc) as e:
            await client.get_json("/api/list.json", {})
    assert len(seen) == 1 and e.value.status == code


@pytest.mark.parametrize("code, attempts", [("800", 3), ("900", 2)])
async def test_800_900_limited_retries(code, attempts):
    client, seen, sleeps = make(status(code))
    async with client:
        with pytest.raises(DartUnavailable):
            await client.get_json("/api/list.json", {})
    assert len(seen) == attempts and len(sleeps) == attempts - 1


async def test_5xx_and_network_retry_three_times_with_backoff():
    client, seen, sleeps = make(lambda r: httpx.Response(503))
    async with client:
        with pytest.raises(DartUnavailable):
            await client.get_json("/api/list.json", {})
    assert len(seen) == 4 and sleeps == [0.5, 1.0, 2.0]

    def boom(r):
        raise httpx.ConnectError("connection refused", request=r)

    client, seen, sleeps = make(boom)
    async with client:
        with pytest.raises(DartUnavailable) as e:
            await client.get_json("/api/list.json", {})
    assert len(seen) == 4 and "ConnectError" in str(e.value)


async def test_transient_then_success():
    responses = iter([httpx.Response(502), httpx.Response(200, json={"status": "000", "list": []})])
    client, seen, _ = make(lambda r: next(responses))
    async with client:
        assert (await client.get_json("/api/list.json", {}))["status"] == "000"
    assert len(seen) == 2


async def test_020_rate_limit_sets_cooldown_and_blocks_without_network():
    clock = Clock()
    client, seen, sleeps = make(status("020"), clock=clock, rate_limit_cooldown=300)
    async with client:
        with pytest.raises(DartRateLimited) as e:
            await client.get_json("/api/list.json", {})
        assert e.value.retryable and e.value.details["cooldown_seconds"] == 300
        with pytest.raises(DartRateLimited):
            await client.get_zip("/api/document.xml", {"rcept_no": "1" * 14})
        assert len(seen) == 1 and sleeps == []  # 즉시 반복 재시도 없음, 쿨다운 중 네트워크 0회
        clock.t += 301
        with pytest.raises(DartRateLimited):
            await client.get_json("/api/list.json", {})
    assert len(seen) == 2


async def test_http_429_is_not_retried():
    clock = Clock()
    client, seen, _ = make(lambda r: httpx.Response(429, headers={"retry-after": "900"}), clock=clock,
                           rate_limit_cooldown=60)
    async with client:
        with pytest.raises(DartRateLimited):
            await client.get_json("/api/list.json", {})
        clock.t += 120  # Retry-After(900초)가 기본 쿨다운보다 길면 그만큼 기다림
        with pytest.raises(DartRateLimited):
            await client.get_json("/api/list.json", {})
    assert len(seen) == 1


@pytest.mark.parametrize("response, message", [
    (httpx.Response(302, headers={"location": "https://opendart.fss.or.kr/error1.html"}), "리다이렉트"),
    (httpx.Response(200, text="<html><body>점검 중</body></html>", headers={"content-type": "text/html"}), "HTML"),
    (httpx.Response(200, text="not json"), "JSON"),
    (httpx.Response(200, json={"message": "no status"}), "status"),
    (httpx.Response(404), "HTTP 404"),
])
async def test_bad_bodies_are_not_data(response, message):
    client, seen, _ = make(lambda r: response)
    async with client:
        with pytest.raises(DartUnavailable) as e:
            await client.get_json("/api/list.json", {})
    assert message in str(e.value) and len(seen) == 1


async def test_http_403_is_auth():
    client, _, _ = make(lambda r: httpx.Response(403))
    async with client:
        with pytest.raises(DartAuthError):
            await client.get_json("/api/list.json", {})


async def test_zip_endpoint_distinguishes_zip_error_xml_and_html():
    bodies = {
        "zip": httpx.Response(200, content=zipped()),
        "014": httpx.Response(200, content=b'<?xml version="1.0" encoding="UTF-8"?><result><status>014</status>'
                                           b"<message>file</message></result>"),
        "013": httpx.Response(200, content=b"<result><status>013</status><message>none</message></result>"),
        "html": httpx.Response(200, content=b"<!DOCTYPE html><html></html>"),
        "garbage": httpx.Response(200, content=b"\x00\x01binary"),
    }
    for kind, resp in bodies.items():
        client, _, _ = make(lambda r, resp=resp: resp)
        async with client:
            if kind == "zip":
                assert (await client.get_zip("/api/document.xml", {"rcept_no": "1" * 14}))[:2] == b"PK"
            elif kind in ("014", "013"):
                with pytest.raises(DartNotFound):
                    await client.get_zip("/api/document.xml", {"rcept_no": "1" * 14})
            else:
                with pytest.raises(DartUnavailable):
                    await client.get_zip("/api/document.xml", {"rcept_no": "1" * 14})


async def test_concurrency_limit():
    in_flight = peak = 0

    async def handler(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json={"status": "000", "list": []})

    client = DartClient(KEY, transport=httpx.MockTransport(handler), max_concurrency=2)
    async with client:
        await asyncio.gather(*(client.get_json("/api/list.json", {}) for _ in range(8)))
    assert peak == 2 and client.request_count == 8


def _chain_text(exc: BaseException) -> str:
    parts, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        parts += [str(exc), repr(exc), repr(getattr(exc, "request", None))]
        exc = exc.__cause__ or exc.__context__
    return " ".join(parts)


async def test_api_key_never_in_logs_or_exceptions(caplog):
    caplog.set_level(logging.DEBUG)  # httpx/httpcore 디버그 로그까지 포함
    errors = []

    def boom(r):
        raise httpx.ConnectTimeout("timed out", request=r)

    for handler in (status("000", list=[]), status("010"), status("020"), lambda r: httpx.Response(500), boom):
        client, _, _ = make(handler)
        async with client:
            try:
                await client.get_json("/api/list.json", {"corp_code": "00000001"})
            except Exception as e:  # noqa: BLE001
                errors.append(e)
    assert len(errors) == 4
    assert KEY not in caplog.text
    for e in errors:
        assert KEY not in _chain_text(e)
    assert any("HTTP Request" in r.getMessage() for r in caplog.records)  # httpx는 키 없는 원래 요청을 기록


def test_base_url_restricted_and_empty_key_rejected():
    with pytest.raises(DartAuthError):
        DartClient(KEY, base_url="https://evil.example.com")
    with pytest.raises(DartAuthError):
        DartClient("")
    DartClient(KEY, base_url="http://127.0.0.1:8199")


async def test_client_owns_and_closes_transport():
    closed = []

    class T(httpx.MockTransport):
        async def aclose(self):
            closed.append(True)

    client = DartClient(KEY, transport=T(status("000")))
    await client.aclose()
    assert closed == [True]
