"""[REPLAY] tests/fixtures/real의 실제 공시를 OpenDART API 형식으로 돌려주는 가짜 서버.

source="viewer": 원문은 DART 공개 뷰어 HTML이고(document.xml ZIP 아님), 이 서버가 ZIP으로 감싸 줍니다.
source="api": 원문은 실제 OpenDART document.xml 응답 ZIP(api/zip/*.zip, 받은 바이트 그대로)입니다.
list.json 행은 실제 list.json 스냅샷(api/list/*.json)과 공개 검색 재구성 행(manifest.json, stock_code 없음)을
합친 것이며, 같은 접수번호는 실제 스냅샷 행을 씁니다. 목록 응답의 포장(페이지 계산 등)은 이 서버가 만듭니다.

httpx.MockTransport(handler)로 쓰거나, app()을 uvicorn으로 띄워 HTTP로 쓸 수 있습니다.
"""

import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "real"


def _zip(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, data)
    return buf.getvalue()


def _error_xml(status: str, message: str) -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><result><status>{status}</status>'
            f"<message>{message}</message></result>").encode()


class FakeOpenDart:
    def __init__(self, fixtures: Path = FIXTURES, *, strip_links: bool = False, source: str = "viewer"):
        manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
        rows = {r["rcept_no"]: r for r in manifest["list_rows"]}
        self.source = source
        self.docs: dict[str, bytes] = {}
        if source == "api":
            for p in sorted((fixtures / "api" / "list").glob("*.json")):
                rows.update({r["rcept_no"]: r for r in json.loads(p.read_text(encoding="utf-8"))["list"]})
            for p in sorted((fixtures / "api" / "zip").glob("*.zip")):
                self.docs[p.stem] = p.read_bytes()
        else:
            for rcept_no in manifest["viewer"]:
                raw = (fixtures / "viewer" / f"{rcept_no}.html").read_bytes()
                if strip_links:  # '관련공시' 링크가 없는 원문을 흉내 냄 (일자 단서만 남김)
                    raw = raw.replace(b"rcpNo=", b"rcpNoX=")
                self.docs[rcept_no] = raw
        self.rows: list[dict] = list(rows.values())
        self.requests: list[httpx.Request] = []
        self.document_downloads: dict[str, int] = {}

    def corp_code_xml(self) -> bytes:
        seen = {}
        for r in self.rows:
            seen.setdefault(r["corp_code"], r["corp_name"])
        body = "".join(f"<list><corp_code>{c}</corp_code><corp_name>{n}</corp_name><corp_eng_name></corp_eng_name>"
                       f"<stock_code> </stock_code><modify_date>20261001</modify_date></list>" for c, n in seen.items())
        return f'<?xml version="1.0" encoding="UTF-8"?><result>{body}</result>'.encode()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        q = request.url.params
        if len(q.get("crtfc_key", "")) != 40:
            return httpx.Response(200, json={"status": "010", "message": "등록되지 않은 인증키입니다."})
        path = request.url.path
        if path == "/api/list.json":
            return self._list(q)
        if path == "/api/document.xml":
            rc = q.get("rcept_no", "")
            self.document_downloads[rc] = self.document_downloads.get(rc, 0) + 1
            if rc not in self.docs:
                return httpx.Response(200, content=_error_xml("014", "파일이 존재하지 않습니다."))
            body = self.docs[rc] if self.source == "api" else _zip(f"{rc}.html", self.docs[rc])
            return httpx.Response(200, content=body, headers={"content-type": "application/x-msdownload"})
        if path == "/api/corpCode.xml":
            return httpx.Response(200, content=_zip("CORPCODE.xml", self.corp_code_xml()))
        return httpx.Response(404)

    def _list(self, q) -> httpx.Response:
        def d(s: str) -> date:
            return datetime.strptime(s, "%Y%m%d").date()

        bgn, end = d(q["bgn_de"]), d(q["end_de"])
        if not q.get("corp_code") and (end - bgn).days > 92:
            return httpx.Response(200, json={"status": "100", "message": "필드의 부적절한 값입니다."})
        rows = [r for r in self.rows if bgn <= d(r["rcept_dt"]) <= end
                and (not q.get("corp_code") or r["corp_code"] == q["corp_code"])
                and (q.get("last_reprt_at", "N") == "N" or "정" not in (r.get("rm") or ""))]
        rows.sort(key=lambda r: r["rcept_no"], reverse=q.get("sort_mth", "desc") == "desc")
        if not rows:
            return httpx.Response(200, json={"status": "013", "message": "조회된 데이타가 없습니다."})
        page_no, page_count = int(q.get("page_no", 1)), int(q.get("page_count", 10))
        total_page = -(-len(rows) // page_count)
        chunk = rows[(page_no - 1) * page_count: page_no * page_count]
        return httpx.Response(200, json={"status": "000", "message": "정상", "page_no": page_no,
                                         "page_count": page_count, "total_count": len(rows),
                                         "total_page": total_page, "list": chunk})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def app(self):
        """uvicorn용 ASGI 앱 (scripts/replay_e2e.py)."""
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Route

        async def endpoint(request):
            r = self.handler(httpx.Request("GET", str(request.url)))
            return Response(r.content, status_code=r.status_code,
                            media_type=r.headers.get("content-type", "application/octet-stream"))

        return Starlette(routes=[Route("/api/{name}", endpoint)])
