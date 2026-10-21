import hashlib
import io
import json
import re
import zipfile
from datetime import date
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from defusedxml import ElementTree


def correction_rows(rows):
    """병합된 항목명을 다음 행에 이어 붙여 정정 전후의 열 위치를 복원합니다."""
    if not any(
        {"정정전", "정정후"} <= {re.sub(r"\s", "", c["text"]) for c in row["cells"]} for row in rows
    ):
        return [], True
    changes, spans = [], {}
    before = after = None
    complete = True
    try:
        for index, row in enumerate(rows):
            grid = {column: cell for column, (cell, _) in spans.items()}
            spans = {
                column: (cell, remaining - 1)
                for column, (cell, remaining) in spans.items()
                if remaining > 1
            }
            column = 0
            for cell in row["cells"]:
                while column in grid:
                    column += 1
                width, height = int(cell.get("colspan", 1)), int(cell.get("rowspan", 1))
                # 외부 표의 비정상적인 병합 크기가 메모리를 과도하게 쓰지 않도록 제한합니다.
                if (
                    not 1 <= width <= 64
                    or not 1 <= height <= len(rows) - index
                    or column + width > 64
                ):
                    raise ValueError()
                for offset in range(width):
                    position = column + offset
                    if position in grid:
                        raise ValueError()
                    grid[position] = cell
                    if height > 1:
                        spans[position] = (cell, height - 1)
                column += width
            values = [grid.get(i, {}).get("text", "") for i in range(max(grid, default=-1) + 1)]
            headers = [re.sub(r"\s", "", value) for value in values]
            if "정정전" in headers and "정정후" in headers:
                if headers.count("정정전") != 1 or headers.count("정정후") != 1:
                    raise ValueError()
                before, after = headers.index("정정전"), headers.index("정정후")
                continue
            if before is None:
                continue
            if before not in grid or after not in grid or grid[before] is grid[after]:
                complete = False
                continue
            if values[before] != values[after]:
                changes.append(
                    (
                        index,
                        {
                            "label": values[0],
                            "before": values[before],
                            "after": values[after],
                            "quote": "\t".join(values),
                        },
                    )
                )
    except (TypeError, ValueError, KeyError):
        complete = False
    return changes, complete


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
                rows = [
                    {
                        "cells": [
                            {
                                "text": c.get_text(" ", strip=True),
                                "rowspan": c.get("rowspan", 1),
                                "colspan": c.get("colspan", 1),
                            }
                            for c in row.find_all(["td", "th"], recursive=False)
                        ]
                    }
                    for row in table.find_all("tr")
                ]
                extracted, valid = correction_rows(rows)
                complete &= valid
                changes.extend(
                    {
                        **change,
                        "document_id": doc_id,
                        "location": f"table:{ti}:row:{index}",
                        "url": documents[-1]["url"],
                    }
                    for index, change in extracted
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
            extracted, valid = correction_rows(table["rows"])
            complete &= valid
            changes.extend(
                {
                    **change,
                    "document_id": doc_id,
                    "location": f"{table['file']}:{table['table_id']}:row:{index}",
                    "url": url,
                }
                for index, change in extracted
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


def analysis_context(filing, fragments):
    """모델에는 정정 전후를 구분해 전달하고 검증용 원문은 그대로 보존합니다."""
    changes = {(c["document_id"], c["location"]): c for c in filing.get("changes", [])}
    result = []
    for source in fragments:
        change = changes.get((source["document_id"], source["location"]))
        if change:
            result.append(
                {
                    "document_id": source["document_id"],
                    "location": source["location"],
                    **{key: " ".join(change[key].split()) for key in ("label", "before", "after")},
                }
            )
        else:
            result.append({**source, "quote": " ".join(source["quote"].split())})
    return result


def validated_sources(sources: list[dict], documents: list[dict], fragments=()) -> list[dict]:
    known = {d["document_id"]: d for d in documents}
    accepted = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("quote"), str):
            continue
        doc = known.get(source.get("document_id"))
        quote = source["quote"]
        if not quote:
            located = [
                f
                for f in fragments
                if f.get("document_id") == source.get("document_id")
                and f.get("location") == source.get("location")
                and f.get("quote")
            ]
            if len({f["quote"] for f in located}) != 1:
                continue
            quote = located[0]["quote"]
        normalized = re.sub(r"\s+", "", quote)
        matches = [
            f
            for f in fragments
            if f.get("document_id") == source.get("document_id")
            and normalized
            and normalized in re.sub(r"\s+", "", f.get("quote", ""))
        ]
        # 줄바꿈만 바뀐 인용은 검증된 원문 조각으로 복원하고 원문 위치를 유지합니다.
        fragment = next((f for f in matches if f.get("location") == source.get("location")), None)
        if fragment is None:
            fragment = next(
                (f for f in matches if f.get("quote") == quote),
                matches[0] if len(matches) == 1 else None,
            )
        if fragment:
            quote = fragment["quote"]
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
    return list({(s["document_id"], s["location"], s["quote"]): s for s in accepted}.values())


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
