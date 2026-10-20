"""실제 공시 fixture 수집 (재현 절차). 네트워크가 필요하며 pytest에서는 실행하지 않습니다.

viewer 모드 (키 불필요): DART 공개 뷰어 HTML과 공개 검색 결과를 저장합니다.
    uv run python scripts/golden.py viewer --out tests/fixtures/real \\
        --rcept 20261019800110 20251223800740 ... \\
        --search "S-Oil:20250901:20261020:단일판매ㆍ공급계약체결"
  - 뷰어 HTML은 document.xml ZIP이 아니라 DART가 원문을 HTML로 바꿔 보여주는 페이지입니다(받은 바이트 그대로 저장).
  - 공개 검색 결과로 list.json 형식의 행을 재구성합니다(공식 API 응답이 아님, stock_code 없음).

api 모드 (OPENDART_API_KEY 필요, .env 또는 환경변수): document.xml ZIP과 list.json 응답을 저장합니다.
    uv run python scripts/golden.py api --out tests/fixtures/real/api --rcept 20261019800110 ...
  - 키는 출력·저장하지 않습니다. 저장하는 것은 응답 본문뿐입니다(요청 URL 미저장).
"""

import argparse
import asyncio
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}
CLS = {"유": "Y", "코": "K", "넥": "N", "기": "E"}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(url: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _clean(x: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def search_rows(company: str, start: str, end: str, report: str) -> list[dict]:
    body = urllib.parse.urlencode({"currentPage": 1, "maxResults": 100, "sort": "date", "series": "desc",
                                   "textCrpNm": company, "reportName": report, "startDate": start,
                                   "endDate": end}).encode()
    t = _get("https://dart.fss.or.kr/dsab007/detailSearch.ax", body,
             {"Referer": "https://dart.fss.or.kr/dsab007/main.do"}).decode("utf-8", "replace")
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", t, re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        m, cc = re.search(r"rcpNo=(\d{14})", tr), re.search(r"openCorpInfoNew\('(\d{8})'", tr)
        if not (m and cc and len(tds) >= 6):
            continue
        corp = _clean(tds[1])
        cls, name = (corp.split(" ", 1) + [""])[:2] if corp[:1] in CLS else ("", corp)
        rows.append({
            "corp_cls": CLS.get(cls), "corp_name": re.sub(r"\s+IR$", "", name).strip(), "corp_code": cc.group(1),
            "stock_code": None, "report_nm": re.sub(r"^(\[[^\]]+\])\s+", r"\1", _clean(tds[2])),
            "rcept_no": m.group(1), "flr_nm": _clean(tds[3]), "rcept_dt": _clean(tds[4]).replace(".", ""),
            "rm": _clean(tds[5]).replace(" ", ""),
        })
    return rows


def viewer(args) -> None:
    out = Path(args.out)
    (out / "viewer").mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"viewer": {}, "list_rows": []}
    for spec in args.search or []:
        company, start, end, report = (spec.split(":") + [""])[:4]
        rows = search_rows(company, start, end, report)
        known = {r["rcept_no"] for r in manifest["list_rows"]}
        manifest["list_rows"] += [r for r in rows if r["rcept_no"] not in known]
        manifest.setdefault("searches", []).append({"company": company, "start": start, "end": end,
                                                     "report": report, "rows": len(rows), "retrieved_at": _now()})
        print(f"search {company} {start}-{end}: {len(rows)} rows")
        time.sleep(1)
    for rcp in args.rcept or []:
        main = _get(f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}").decode("utf-8", "replace")
        a = re.findall(r'"([^"]*)"', re.search(r'viewDoc\("[^)]*\)', main).group(0))
        url = (f"https://dart.fss.or.kr/report/viewer.do?rcpNo={a[0]}&dcmNo={a[1]}&eleId={a[2]}"
               f"&offset={a[3]}&length={a[4]}&dtd={a[5]}")
        raw = _get(url)
        (out / "viewer" / f"{rcp}.html").write_bytes(raw)
        manifest["viewer"][rcp] = {"viewer_url": url, "dtd": a[5], "sha256": hashlib.sha256(raw).hexdigest(),
                                   "bytes": len(raw), "retrieved_at": _now()}
        print(f"viewer {rcp}: dtd={a[5]} {len(raw)} bytes")
        time.sleep(1)
    manifest["list_rows"].sort(key=lambda r: r["rcept_no"], reverse=True)
    manifest["_note"] = ("DART 공개 뷰어 HTML과 공개 검색 결과로 만든 fixture입니다. viewer/*.html은 document.xml ZIP이 "
                         "아니며, list_rows는 공개 검색 결과를 list.json 행 형식으로 재구성한 것입니다(stock_code 없음).")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


async def api(args) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from business_mcp import providers
    from business_mcp.config import get_settings
    from dart_core.client import DartClient

    if problem := providers.api_key_problem():
        sys.exit(f"api 모드를 실행할 수 없습니다: {problem}")
    out = Path(args.out)
    (out / "zip").mkdir(parents=True, exist_ok=True)
    (out / "list").mkdir(parents=True, exist_ok=True)
    index_path = out / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    async with DartClient(get_settings().opendart_api_key.get_secret_value().strip()) as client:
        for rcp in args.rcept:
            data = await client.get_zip("/api/document.xml", {"rcept_no": rcp})
            (out / "zip" / f"{rcp}.zip").write_bytes(data)
            day = rcp[:8]
            listing = await client.get_json("/api/list.json", {"bgn_de": day, "end_de": day, "last_reprt_at": "N",
                                                                "page_count": 100})
            row = next((r for r in listing.get("list", []) if r.get("rcept_no") == rcp), None)
            if row:
                corp_list = await client.get_json("/api/list.json", {
                    "corp_code": row["corp_code"], "bgn_de": f"{int(day[:4]) - 1}{day[4:]}", "end_de": day,
                    "last_reprt_at": "N", "page_count": 100})
                (out / "list" / f"{row['corp_code']}_{day}.json").write_text(
                    json.dumps(corp_list, ensure_ascii=False, indent=1), encoding="utf-8")
            index[rcp] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "retrieved_at": _now(),
                          "list_row": row}
            print(f"api {rcp}: {len(data)} bytes, row={'found' if row else 'not on first page'}")
    index_path.write_text(json.dumps(dict(sorted(index.items())), ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)
    v = sub.add_parser("viewer")
    v.add_argument("--out", required=True)
    v.add_argument("--rcept", nargs="*")
    v.add_argument("--search", nargs="*", help="회사:시작YYYYMMDD:끝YYYYMMDD[:보고서명]")
    a = sub.add_parser("api")
    a.add_argument("--out", required=True)
    a.add_argument("--rcept", nargs="+", required=True)
    args = p.parse_args()
    viewer(args) if args.mode == "viewer" else asyncio.run(api(args))


if __name__ == "__main__":
    main()
