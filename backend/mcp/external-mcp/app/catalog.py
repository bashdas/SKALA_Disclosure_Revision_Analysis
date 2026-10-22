"""OpenDART 회사 및 공시 검색과 DART가 연결한 본문 이력을 조회합니다."""
import asyncio
import calendar
from hashlib import sha256
from datetime import date, datetime
from io import BytesIO
import json
import re
import time
import zipfile

import httpx
from lxml import etree

from app.client import OpenDartClient
from app.errors import OpenDartError, check_status
from app.market_ranking import MarketRanking


class DisclosureCatalog:
    def __init__(self, client: OpenDartClient):
        self.client = client
        self.companies: list[dict] = []
        self.loaded_at = 0.0
        self.lock = asyncio.Lock()
        self.market_ranking = MarketRanking(getattr(client, "transport", None))

    async def search_companies(self, query: str, limit: int = 20, offset: int = 0, seed: str = "", sort: str = "default", snapshot: str = "") -> dict:
        async with self.lock:
            if not self.companies or time.monotonic() - self.loaded_at >= 86400:
                raw = await self.client._get("corpCode.xml", {})
                try:
                    # 회사명 검색에는 전체 고유번호 파일이 필요하므로 하루 동안 메모리에서 재사용합니다.
                    with zipfile.ZipFile(BytesIO(raw)) as archive:
                        member = archive.getinfo("CORPCODE.xml")
                        if member.file_size > 64 * 1024 * 1024:
                            raise ValueError()
                        xml = archive.read(member)
                    if b"<!ENTITY" in xml or b"<!DOCTYPE" in xml:
                        raise ValueError()
                    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
                    rows = []
                    for node in root.findall("list"):
                        code, name = node.findtext("corp_code", ""), node.findtext("corp_name", "")
                        if re.fullmatch(r"[0-9]{8}", code) and name.strip():
                            rows.append({"corp_code": code, "company_name": name, "stock_code": node.findtext("stock_code", "").strip()})
                    if not rows:
                        raise ValueError()
                    self.companies, self.loaded_at = rows, time.monotonic()
                except (ValueError, KeyError, zipfile.BadZipFile, etree.LxmlError):
                    raise OpenDartError("OPENDART_UNAVAILABLE") from None
        key = query.strip().casefold()
        matches = [row for row in self.companies if key in row["company_name"].casefold() or key == row["stock_code"] or key == row["corp_code"]]
        if sort in {"market_cap_desc", "market_cap_asc"}:
            snapshot, values = await self.market_ranking.get(snapshot)
            direction = -1 if sort == "market_cap_desc" else 1
            matches.sort(key=lambda row: (
                row["stock_code"] not in values,
                direction * values.get(row["stock_code"], 0),
                row["company_name"], row["corp_code"],
            ))
            return {"items": matches[offset:offset + limit], "total_count": len(matches),
                "has_more": offset + limit < len(matches), "snapshot": snapshot}
        if sort == "name":
            matches.sort(key=lambda row: (row["company_name"], row["corp_code"]))
            return {"items": matches[offset:offset + limit], "total_count": len(matches), "has_more": offset + limit < len(matches)}
        matches.sort(key=lambda row: (row["company_name"] != query.strip(), not bool(row["stock_code"]), row["company_name"]))
        # 같은 방문의 페이지는 동일한 무작위 순서를 유지해 기업 중복과 누락을 막습니다.
        if seed and not key:
            matches.sort(key=lambda row: sha256(f"{seed}:{row['corp_code']}".encode()).digest())
        return {"items": matches[offset:offset + limit], "total_count": len(matches), "has_more": offset + limit < len(matches)}

    async def search_disclosures(self, corp_code: str | None, start_date: date, end_date: date, page: int = 1, query: str = "") -> dict:
        if start_date > end_date:
            raise OpenDartError("INVALID_SEARCH_RANGE")
        if corp_code is None:
            month = end_date.year * 12 + end_date.month - 4
            year, month0 = divmod(month, 12)
            earliest = date(year, month0 + 1, min(end_date.day, calendar.monthrange(year, month0 + 1)[1]))
            if start_date < earliest:
                raise OpenDartError("INVALID_SEARCH_RANGE")
        raw = await self.client._get("list.json", {**({"corp_code": corp_code} if corp_code else {}),
            "bgn_de": start_date.strftime("%Y%m%d"), "end_de": end_date.strftime("%Y%m%d"),
            "last_reprt_at": "N", "page_count": 20, "page_no": page, "sort": "date", "sort_mth": "desc"})
        try:
            data = json.loads(raw)
            check_status(data["status"], allow_empty=True)
            if data["status"] in ("013", "014"):
                return {"items": [], "total_count": 0, "has_more": False}
            rows = []
            for row in data["list"]:
                receipt = row["rcept_no"]
                if not re.fullmatch(r"[0-9]{14}", receipt) or (corp_code and row["corp_code"] != corp_code):
                    raise ValueError()
                rows.append({"receipt_no": receipt, "corp_code": row["corp_code"], "company_name": row["corp_name"],
                    "report_name": row["report_nm"], "filed_at": datetime.strptime(row["rcept_dt"], "%Y%m%d").date().isoformat(),
                    "is_correction": bool(re.match(r"^\[(?:기재|첨부)?정정\]", row["report_nm"])), "has_corrections": "정" in row.get("rm", "")})
            return {"items": [r for r in rows if not query or query.casefold() in r["report_name"].casefold() or query.casefold() in r["company_name"].casefold()], "total_count": None if query else int(data["total_count"]), "has_more": page < int(data["total_page"]), "next_page": page + 1}
        except (ValueError, TypeError, KeyError):
            raise OpenDartError("OPENDART_UNAVAILABLE") from None

    async def family(self, receipt_no: str) -> dict:
        try:
            # DART가 명시한 관련 본문만 사용하며 같은 제목의 별도 계약을 임의로 연결하지 않습니다.
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False, transport=self.client.transport) as client:
                async with client.stream("GET", "https://dart.fss.or.kr/dsaf001/main.do", params={"rcpNo": receipt_no}) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 4 * 1024 * 1024:
                            raise ValueError()
                        chunks.append(chunk)
            return parse_family(b"".join(chunks), receipt_no)
        except (httpx.HTTPError, ValueError, etree.LxmlError):
            raise OpenDartError("DISCLOSURE_FAMILY_UNAVAILABLE") from None


def parse_family(raw: bytes, receipt_no: str) -> dict:
    root = etree.fromstring(raw, etree.HTMLParser(no_network=True, encoding="utf-8"))
    rows = []
    for option in root.xpath('//select[@id="family"]/option'):
        match = re.fullmatch(r"rcpNo=([0-9]{14})(?:&dcmNo=[0-9]+)?", option.get("value", ""))
        if not match:
            continue
        text = " ".join("".join(option.itertext()).split())
        filed = re.search(r"\b([0-9]{4}\.[0-9]{2}\.[0-9]{2})\b", text)
        if filed is None:
            raise ValueError("Missing family date")
        rows.append({"receipt_no": match[1], "report_name": option.get("title", ""),
            "filed_at": datetime.strptime(filed[1], "%Y.%m.%d").date().isoformat(),
            "is_correction": "[정정]" in text or "[기재정정]" in text or "[첨부정정]" in text})
    if not any(row["receipt_no"] == receipt_no for row in rows):
        raise ValueError("Receipt is missing from DART family")
    return {"items": sorted(rows, key=lambda row: row["receipt_no"]), "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}"}
