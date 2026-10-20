"""HTTP /mcp 엔드투엔드 검증. Business MCP 서버를 별도 프로세스(DATA_BACKEND=live)로 띄우고 FastMCP HTTP Client로 호출합니다.

    uv run python scripts/e2e_http.py --mode replay   # 키·네트워크 불필요: 로컬 가짜 OpenDART(실제 공시 fixture 재생)
    uv run python scripts/e2e_http.py --mode nokey    # live인데 키가 없을 때 /health 503과 Tool 오류 확인
    uv run python scripts/e2e_http.py --mode real     # 실제 OpenDART (프로젝트 .env의 OPENDART_API_KEY 필요)

real 모드는 키를 출력하지 않으며, 서버 로그에 키가 없는지도 검사합니다.
"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from fastmcp import Client

from business_mcp.schemas import ErrorResponse, FilingDiff, SearchFilingsResult

EXPECTED_TOOLS = {"search_filings", "get_filing_document", "get_filing_diff", "get_analysis_memo",
                  "save_review_decision"}
DUMMY_KEY = "R" * 40  # replay 전용 가짜 키


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 20) -> tuple[int, dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise TimeoutError(url)


def start_fake_opendart(port: int):
    import uvicorn
    from fake_opendart import FakeOpenDart

    fake = FakeOpenDart()
    server = uvicorn.Server(uvicorn.Config(fake.app(), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    return fake, server


def start_mcp(env: dict, log_path: Path) -> subprocess.Popen:
    with open(log_path, "wb") as log:  # 자식 프로세스가 파일 핸들을 물려받음
        return subprocess.Popen([sys.executable, "-m", "business_mcp.server"], cwd=ROOT, env=env, stdout=log,
                                stderr=log)


async def exercise(base: str, cases: list[dict]) -> list[str]:
    report = []
    async with Client(f"{base}/mcp") as c:
        tools = {t.name for t in await c.list_tools()}
        assert tools == EXPECTED_TOOLS, tools
        report.append(f"tools/list: {len(tools)}개 일치")
        r = await c.call_tool("search_filings", cases[0]["search"], raise_on_error=False)
        assert not r.is_error, r.content[0].text
        s = SearchFilingsResult.model_validate(r.structured_content)
        report.append(f"search_filings({cases[0]['search']['corp']}): status={s.status} filings={len(s.filings)} "
                      f"source={s.meta.source}")
        for case in cases:
            r = await c.call_tool("get_filing_diff", {"correction_rcept_no": case["rcept_no"]}, raise_on_error=False)
            assert not r.is_error, r.content[0].text
            d = FilingDiff.model_validate(r.structured_content)
            size = len(r.content[0].text.encode())
            assert d.match.original_rcept_no == case.get("original", d.match.original_rcept_no), d.match
            for key, before, after in case.get("values", []):
                ch = next(x for x in d.changes if x.field_key == key)
                assert (ch.before.value, ch.after.value) == (before, after), (key, ch.before, ch.after)
            report.append(f"get_filing_diff({case['rcept_no']}): match={d.match.status} original="
                          f"{d.match.original_rcept_no} previous={d.match.previous_rcept_no} changes={len(d.changes)} "
                          f"needs_review={d.needs_review} size={size}B source={d.meta.source}")
    return report


CASES = [
    {"rcept_no": "20261019800110", "original": "20251223800740",
     "search": {"corp": "S-Oil", "date_from": "2026-10-01", "date_to": "2026-10-20", "corrections_only": True},
     "values": [("contract_amount", 943000000000, 1284544500098), ("revenue_ratio", 2.6, 3.5)]},
    {"rcept_no": "20261019800117", "original": "20251027800243",
     "values": [("contract_amount", 1181000000000, 1740795519703)]},
    {"rcept_no": "20261019000366", "original": "20261014000424",
     "values": [("conversion_price", 2954, 2774), ("maturity_date", "2031-10-26", "2031-10-27")]},
    {"rcept_no": "20261016800813", "original": None},  # 뷰어 fixture에는 2단계 앞 원문이 없어 확정 보류
]
# 실제 OpenDART: 원본까지 3단계 추적 (tests/fixtures/real/golden.json C2.full_chain, 사람이 원문으로 확인)
REAL_CASES = [*CASES[:3], {"rcept_no": "20261016800813", "original": "20240603800216",
                           "values": [("contract_amount", 21520400000, 21787700000)]}]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["replay", "nokey", "real"], required=True)
    args = p.parse_args()
    work = Path(tempfile.mkdtemp(prefix="gongsi-e2e-"))
    mcp_port = free_port()
    env = {k: v for k, v in os.environ.items() if k not in ("OPENDART_API_KEY", "DART_BASE_URL")}
    env.update({"DATA_BACKEND": "live", "MCP_HOST": "127.0.0.1", "MCP_PORT": str(mcp_port),
                "DART_DATA_DIR": str(work / "data"), "PYTHONPATH": str(ROOT / "src"),
                "FASTMCP_SHOW_SERVER_BANNER": "false"})
    secret = None
    if args.mode in ("replay", "nokey"):
        env["BUSINESS_MCP_ENV_FILE"] = ""  # 로컬 .env의 실제 키·설정을 쓰지 않음
    if args.mode == "replay":
        fake_port = free_port()
        _fake, _server = start_fake_opendart(fake_port)
        wait_http_port(fake_port)
        env.update({"OPENDART_API_KEY": DUMMY_KEY, "DART_BASE_URL": f"http://127.0.0.1:{fake_port}"})
        secret = DUMMY_KEY
    elif args.mode == "real":
        from business_mcp import providers

        if problem := providers.api_key_problem():  # .env를 읽되 값은 출력하지 않음
            sys.exit(f"real 모드를 실행할 수 없습니다: {problem}")
        from business_mcp.config import get_settings

        secret = get_settings().opendart_api_key.get_secret_value().strip()
        env["OPENDART_API_KEY"] = secret
    log_path = work / "mcp.log"
    proc = start_mcp(env, log_path)
    try:
        status, health = wait_http(f"http://127.0.0.1:{mcp_port}/health")
        print(f"GET /health → {status} {health}")
        if args.mode == "nokey":
            assert status == 503 and health["status"] == "misconfigured"

            async def call():
                async with Client(f"http://127.0.0.1:{mcp_port}/mcp") as c:
                    r = await c.call_tool("get_filing_diff", {"correction_rcept_no": "20261019800110"},
                                          raise_on_error=False)
                    return ErrorResponse.model_validate_json(r.content[0].text).error

            err = asyncio.run(call())
            print(f"get_filing_diff → isError, code={err.code}: {err.message}")
            assert err.code == "UPSTREAM_AUTH"
        else:
            assert status == 200
            cases = REAL_CASES if args.mode == "real" else CASES
            for line in asyncio.run(exercise(f"http://127.0.0.1:{mcp_port}", cases)):
                print(line)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    log = log_path.read_bytes().decode("utf-8", "replace")
    if secret:
        assert secret not in log, "서버 로그에 API 키가 있습니다"
        print(f"서버 로그 {len(log)}자에 API 키 없음 확인")
    print(f"OK ({args.mode})")


def wait_http_port(port: int, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(port)


if __name__ == "__main__":
    main()
