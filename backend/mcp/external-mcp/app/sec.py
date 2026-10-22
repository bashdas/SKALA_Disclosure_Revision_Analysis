"""SEC의 기업 정보와 공시 본문 및 실적 첨부자료를 조회합니다."""
import io
import re
import zipfile
from datetime import datetime, timezone

import httpx
from lxml import etree

from app.errors import OpenDartError


async def download(client, url):
    # 공시 원문은 리디렉션 없이 SEC 호스트에서 크기를 제한해 읽습니다.
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > 20 * 1024 * 1024:
                raise ValueError("SEC document size exceeded")
        return bytes(data)


def client(settings, transport=None):
    return httpx.AsyncClient(headers={"User-Agent": settings.sec_user_agent}, timeout=30,
        follow_redirects=False, trust_env=False, transport=transport)


async def company(cik, settings, transport=None):
    if not re.fullmatch(r"[0-9]{1,10}", cik) or int(cik) == 0:
        raise OpenDartError("INVALID_RECEIPT_NO")
    async with client(settings, transport) as http:
        response = await http.get(f"https://data.sec.gov/submissions/CIK{int(cik):010}.json")
        response.raise_for_status()
        data = response.json()
    if int(data["cik"]) != int(cik):
        raise ValueError("SEC CIK mismatch")
    return data


async def search_company(identifier, settings, transport=None):
    data = await company(identifier.removeprefix("SEC:"), settings, transport)
    return {"items": [{"corp_code": f"SEC:{int(data['cik'])}", "company_name": data["name"],
        "stock_code": next(iter(data.get("tickers", [])), "")}], "total_count": 1, "has_more": False}


async def search_filings(identifier, start, end, page, query, settings, transport=None):
    data = await company(identifier.removeprefix("SEC:"), settings, transport)
    recent = data["filings"]["recent"]
    items = []
    for i, accession in enumerate(recent["accessionNumber"]):
        filed, form = recent["filingDate"][i], recent["form"][i]
        if form in {"8-K", "8-K/A"} and start.isoformat() <= filed <= end.isoformat() and query.lower() in form.lower():
            items.append({"receipt_no": f"SEC:{int(data['cik'])}:{accession}",
                "corp_code": identifier, "company_name": data["name"], "report_name": form,
                "filed_at": filed, "is_correction": form.endswith("/A"), "has_corrections": False})
    offset = (page - 1) * 20
    return {"items": items[offset:offset + 20], "total_count": len(items),
        "has_more": offset + 20 < len(items), "next_page": page + 1}


async def disclosure(identifier, parser, settings, transport=None):
    match = re.fullmatch(r"SEC:([0-9]{1,10}):([0-9]{10}-[0-9]{2}-[0-9]{6})", identifier)
    if not match or int(match[1]) == 0:
        raise OpenDartError("INVALID_RECEIPT_NO")
    cik, accession = str(int(match[1])), match[2]
    prefix = f"/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    url = f"https://www.sec.gov{prefix}{accession}-index.html"
    async with client(settings, transport) as http:
        root = etree.HTML(await download(http, url))
        filed = root.xpath('//div[normalize-space()="Filing Date"]/following-sibling::div[1]/text()')[0].strip()
        datetime.strptime(filed, "%Y-%m-%d")
        name = root.xpath('//span[@class="companyName"]/text()')[0].strip()
        name = re.sub(r"\s*\(Filer\).*", "", name)
        archive = io.BytesIO()
        selected = 0
        report_form = None
        with zipfile.ZipFile(archive, "w") as package:
            for row in root.xpath('//table[@class="tableFile"]//tr'):
                cells = row.findall('td')
                if len(cells) < 4:
                    continue
                form = ''.join(cells[3].itertext()).strip()
                if form not in {"8-K", "8-K/A", "EX-99.1"}:
                    continue
                if form in {"8-K", "8-K/A"}:
                    report_form = form
                hrefs = cells[2].xpath('.//a/@href')
                if not hrefs:
                    continue
                href = hrefs[0]
                if href.startswith('/ix?doc='):
                    href = href.removeprefix('/ix?doc=')
                filename = href.removeprefix(prefix)
                if not href.startswith(prefix) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.html?", filename):
                    raise ValueError("Invalid SEC document link")
                if selected >= 4:
                    raise ValueError("SEC attachment limit exceeded")
                package.writestr(filename, await download(http, 'https://www.sec.gov' + href))
                selected += 1
        if not selected or report_form is None:
            raise ValueError("No SEC 8-K documents")
    document = parser.parse(archive.getvalue())
    return {"receipt_no": identifier, "corp_code": None, "company_name": name,
        "report_name": f"{report_form} 실적 및 주요사항 보고서", "filed_at": filed,
        "document": document, "metadata_status": "FOUND",
        "source": {"provider": "SEC", "source_type": "REGULATORY_FILING", "identifier": identifier,
            "published_at": filed, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "original_location": url}}
