import hashlib
import io
import json
import re
import zipfile
from datetime import date
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from defusedxml import ElementTree


def parse_filing(data: bytes, receipt: str) -> dict:
    """ZIP을 디스크에 풀지 않고 크기를 제한해 정정표와 위치를 보존합니다."""
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("공시 압축 파일 크기를 초과했습니다.")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        root = ElementTree.fromstring(data)
        status = root.findtext("status", "UNKNOWN")
        raise ValueError("OPENDART_" + status)
    documents, changes = [], []
    complete = True
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 100 or sum(n.file_size for n in infos) > 50 * 1024 * 1024:
            raise ValueError("공시 압축 해제 크기를 초과했습니다.")
        for info in infos:
            if not info.filename.lower().endswith((".xml", ".html", ".htm")):
                continue
            raw = archive.read(info)
            text = None
            for encoding in ("utf-8-sig", "cp949", "euc-kr"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                raise ValueError("공시 문자 인코딩을 해석하지 못했습니다.")
            # 외부 엔티티를 허용하지 않으며 HTML 표 구조는 별도로 읽습니다.
            if re.search(r"<!ENTITY", text, re.I):
                raise ValueError("외부 엔티티가 포함된 원문입니다.")
            # XML과 HTML 공시의 표 태그를 같은 경로로 읽기 위해 XML 선언을 제거합니다.
            markup = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, flags=re.I)
            soup = BeautifulSoup(markup, "html.parser")
            for item in soup(["script", "style"]):
                item.decompose()
            doc_id = receipt + ":" + info.filename
            body = soup.get_text("\n", strip=True)
            documents.append(
                {
                    "document_id": doc_id,
                    "text": body,
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
                }
            )
            for ti, table in enumerate(soup.find_all("table")):
                before_i = after_i = None
                if table.find(attrs={"rowspan": True}) or table.find(attrs={"colspan": True}):
                    complete = False
                for ri, row in enumerate(table.find_all("tr")):
                    cells = [
                        c.get_text(" ", strip=True)
                        for c in row.find_all(["td", "th"], recursive=False)
                    ]
                    normalized = [re.sub(r"\s", "", c) for c in cells]
                    if "정정전" in normalized and "정정후" in normalized:
                        before_i, after_i = normalized.index("정정전"), normalized.index("정정후")
                        continue
                    if before_i is None or max(before_i, after_i) >= len(cells):
                        continue
                    if cells[before_i] == cells[after_i]:
                        continue
                    changes.append(
                        {
                            "label": cells[0],
                            "before": cells[before_i],
                            "after": cells[after_i],
                            "document_id": doc_id,
                            "location": f"table:{ti}:row:{ri}",
                            "quote": " | ".join(cells),
                            "url": documents[-1]["url"],
                        }
                    )
    if not documents or not any(d["text"].strip() for d in documents):
        raise ValueError("공시 본문이 없습니다.")
    return {
        "documents": documents,
        "changes": changes,
        "complete_correction_table": bool(changes) and complete and len(documents) == 1,
    }


def typo_only(filing: dict) -> bool:
    changes = filing.get("changes", [])
    if not changes or not filing.get("complete_correction_table"):
        return False
    # 자동 생략은 공백 차이로 한정하며 계약 핵심 항목은 정상 분석합니다.
    protected = re.compile(r"금액|날짜|일자|회사|기업|계약|기간|조건|상호|수량|단가|부정")
    return all(
        not protected.search(c["label"])
        and re.sub(r"\s+", "", c["before"]) == re.sub(r"\s+", "", c["after"])
        for c in changes
    )


def search_documents(documents: list[dict], query: str, limit=8) -> list[dict]:
    terms = set(re.findall(r"[가-힣A-Za-z0-9]+", query.lower()))
    rows = []
    for doc in documents:
        for index, paragraph in enumerate(doc["text"].splitlines()):
            score = sum(t in paragraph.lower() for t in terms)
            if score:
                rows.append(
                    (
                        score,
                        {
                            "document_id": doc["document_id"],
                            "location": f"line:{index + 1}",
                            "quote": paragraph[:1200],
                            "url": doc.get("url"),
                        },
                    )
                )
    return [row for _, row in sorted(rows, key=lambda pair: -pair[0])[:limit]]


def normalize_disclosure(result: dict, receipt: str) -> dict:
    """백엔드 get_disclosure의 원문 표를 AI의 정정 전후 문맥으로 연결합니다."""
    try:
        if result["receipt_no"] != receipt:
            raise ValueError()
        raw, source = result["document"], result["source"]
        text, digest = raw["text"], raw["content_hash"]
        if not isinstance(text, str) or not text.strip() or len(text) > 64 * 1024 * 1024:
            raise ValueError()
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError()
        # 공식 document_id가 없으므로 작업 내 원문 식별자로 내용 해시를 사용합니다.
        doc_id = f"opendart:{receipt}:{digest}"
        url = source["original_location"]
        if url != f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}":
            raise ValueError()
        document = {
            "document_id": doc_id,
            "text": text,
            "url": url,
            "published_at": source.get("published_at"),
        }
        changes, complete = [], True
        for table in raw["tables"]:
            before_i = after_i = None
            for index, row in enumerate(table["rows"]):
                cells = row["cells"]
                if any(c["rowspan"] != 1 or c["colspan"] != 1 for c in cells):
                    complete = False
                values = [c["text"] for c in cells]
                if not all(isinstance(v, str) for v in values):
                    raise ValueError()
                headers = [re.sub(r"\s", "", value) for value in values]
                if "정정전" in headers and "정정후" in headers:
                    before_i, after_i = headers.index("정정전"), headers.index("정정후")
                    continue
                if before_i is None or max(before_i, after_i) >= len(values):
                    continue
                if values[before_i] != values[after_i]:
                    changes.append(
                        {
                            "label": values[0],
                            "before": values[before_i],
                            "after": values[after_i],
                            "document_id": doc_id,
                            "location": f"{table['file']}:{table['table_id']}:row:{index}",
                            "quote": "\t".join(values),
                            "url": url,
                        }
                    )
        return {
            "documents": [document],
            "changes": changes,
            "complete_correction_table": bool(changes) and complete and len(raw["files"]) == 1,
            "tables": raw["tables"],
            "blocks": raw["blocks"],
            "files": raw["files"],
            "corp_code": result.get("corp_code"),
            "company_name": result.get("company_name"),
            "filed_at": result.get("filed_at"),
            "metadata_status": result.get("metadata_status"),
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"error": "INVALID_DISCLOSURE_RESPONSE"}


def validated_sources(sources: list[dict], documents: list[dict], fragments=()) -> list[dict]:
    known = {d["document_id"]: d for d in documents}
    accepted = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("quote"), str):
            continue
        doc = known.get(source.get("document_id"))
        quote = source["quote"]
        fragment = next(
            (
                f
                for f in fragments
                if f.get("document_id") == source.get("document_id") and f.get("quote") == quote
            ),
            None,
        )
        if doc and quote and (quote in doc["text"] or fragment):
            location = (
                fragment["location"]
                if fragment
                else f"line:{doc['text'][: doc['text'].index(quote)].count(chr(10)) + 1}"
            )
            accepted.append(
                {
                    "document_id": source["document_id"],
                    "quote": quote,
                    "location": location,
                    "url": doc.get("url"),
                    "published_at": doc.get("published_at"),
                }
            )
    return accepted


def normalize_evidence(result, kind, args):
    """백엔드 검색 요약과 재무 계정을 원문을 보존한 검색 문서로 변환합니다."""
    try:
        cutoff = date.fromisoformat(args["as_of"])
        documents, sources, limitations = [], [], []
        if kind == "financial":
            if any(
                str(result.get(k)) != str(args[k])
                for k in ("corp_code", "bsns_year", "reprt_code", "fs_div")
            ):
                raise ValueError()
            metadata = {s["identifier"]: s for s in result["sources"]}
            rows = result["accounts"]
        else:
            if result.get("query") != args["query"]:
                raise ValueError()
            rows = result["results"]
            limitations.append(
                "학술 자료는 검색 요약이며 논문 전문과 정확한 발행일을 확인하지 못했습니다."
            )
        if not isinstance(rows, list):
            raise ValueError()
        for row in rows:
            if kind == "financial":
                source = metadata[row["rcept_no"]]
                published = source.get("published_at")
                if not published or date.fromisoformat(published[:10]) > cutoff:
                    limitations.append(
                        "기준일까지 공개됐음을 확인하지 못한 재무자료를 제외했습니다."
                    )
                    continue
                text = json.dumps(
                    {**row, "fs_div": args["fs_div"]}, ensure_ascii=False, sort_keys=True
                )
                location = "account:" + str(row.get("account_id") or row.get("account_nm"))
            else:
                source = row["source"]
                title, snippet = row["title"], row.get("snippet")
                if (
                    not isinstance(title, str)
                    or not isinstance(snippet, str)
                    or not snippet.strip()
                ):
                    limitations.append("검색 요약이 없는 논문은 분석 근거에서 제외했습니다.")
                    continue
                published = source.get("published_at")
                if published and date.fromisoformat(published[:10]) > cutoff:
                    continue
                text = title + "\n" + snippet
                location = "scholar:search-snippet"
            url = source.get("original_location")
            parsed = urlsplit(url or "")
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or "api_key=" in (url or "").lower()
            ):
                raise ValueError()
            digest = hashlib.sha256((url + text).encode()).hexdigest()
            doc_id = kind + ":" + digest
            documents.append(
                {
                    "document_id": doc_id,
                    "text": text,
                    "url": url,
                    "published_at": published,
                    "evidence_scope": "background" if kind == "academic" else "financial",
                }
            )
            sources.append(
                {
                    "document_id": doc_id,
                    "location": location,
                    "quote": text,
                    "url": url,
                    "published_at": published,
                }
            )
        return {
            "documents": documents,
            "sources": sources,
            "limitations": list(dict.fromkeys(limitations)),
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"error": "INVALID_EVIDENCE_RESPONSE"}
