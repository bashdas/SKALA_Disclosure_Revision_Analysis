"""고유번호(corpCode.xml) 캐시와 회사 해석.

- 해석 규칙(resolve): 8자리 → corp_code, 6자리 → 종목코드, 그 밖에는 이름 정확 > 접두 > 부분 일치,
  같은 단계에서는 상장사(종목코드 있음) 우선. 정확 일치 1건이거나 전체 1건이면 확정, 아니면 후보 최대 10건.
- 캐시(CorpCodeIndex): 첫 조회 때 지연 로드, TTL이 지나면 갱신. 갱신은 asyncio.Lock으로 한 번만 실행.
  갱신 실패 시 기존 캐시(메모리 또는 디스크)가 있으면 그대로 쓰고(stale) 경고 로그를 남기며,
  retry_backoff 동안은 다시 내려받지 않습니다. 기존 캐시가 없으면 오류를 그대로 올립니다.
"""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from lxml import etree

from dart_core.models import CompanyHit
from dart_core.parsing.document import read_zip
from dart_core.status import DartError, DocumentParseError
from dart_core.store import atomic_write

logger = logging.getLogger(__name__)
CORP_ZIP_LIMIT = 300 * 1024 * 1024


def resolve(companies: list[dict], query: str) -> tuple[CompanyHit | None, list[CompanyHit]]:
    q = query.strip()

    def hit(c: dict, match_type: str) -> CompanyHit:
        return CompanyHit(corp_code=c["corp_code"], corp_name=c["corp_name"], stock_code=c.get("stock_code"),
                          match_type=match_type)

    if q.isdigit() and len(q) in (6, 8):
        key, match_type = ("corp_code", "corp_code") if len(q) == 8 else ("stock_code", "stock_code")
        found = [c for c in companies if c.get(key) == q]
        if len(found) == 1:
            return hit(found[0], match_type), []
        return None, [hit(c, match_type) for c in found[:10]]

    key = "".join(q.split()).lower()
    if not key:
        return None, []
    tiers: dict[str, list[dict]] = {"exact": [], "prefix": [], "substring": []}
    for c in companies:
        name = "".join(c["corp_name"].split()).lower()
        if name == key:
            tiers["exact"].append(c)
        elif name.startswith(key):
            tiers["prefix"].append(c)
        elif key in name:
            tiers["substring"].append(c)
    ranked = [hit(c, t) for t, cs in tiers.items() for c in sorted(cs, key=lambda c: c.get("stock_code") is None)]
    if len(tiers["exact"]) == 1 or len(ranked) == 1:
        return ranked[0], []
    return None, ranked[:10]


def parse_corp_code_zip(data: bytes) -> list[dict]:
    """corpCode.xml ZIP → [{corp_code, corp_name, stock_code, modify_date}]. 형식이 다르면 DocumentParseError."""
    entries = [(n, b) for n, b in read_zip(data, max_entries=5, max_entry_bytes=CORP_ZIP_LIMIT,
                                         max_total_bytes=CORP_ZIP_LIMIT) if n.lower().endswith(".xml")]
    if len(entries) != 1:
        raise DocumentParseError(None, f"고유번호 ZIP의 XML 파일 수가 1이 아닙니다 ({len(entries)}).")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
    try:
        root = etree.fromstring(entries[0][1], parser)
    except etree.XMLSyntaxError:
        raise DocumentParseError(None, "고유번호 XML을 해석할 수 없습니다.") from None
    out = []
    for el in root.iter("list"):
        code = (el.findtext("corp_code") or "").strip()
        name = (el.findtext("corp_name") or "").strip()
        if len(code) == 8 and code.isdigit() and name:
            stock = (el.findtext("stock_code") or "").strip() or None
            out.append({"corp_code": code, "corp_name": name, "stock_code": stock,
                        "modify_date": (el.findtext("modify_date") or "").strip() or None})
    if not out:
        raise DocumentParseError(None, "고유번호 XML에 회사 행이 없습니다.")
    return out


class CorpCodeIndex:
    def __init__(self, client, cache_file: Path, *, ttl_seconds: float = 24 * 3600, retry_backoff: float = 600,
                 clock=time.time):
        self._client = client
        self._file = cache_file
        self._ttl = ttl_seconds
        self._backoff = retry_backoff
        self._clock = clock
        self._lock = asyncio.Lock()
        self._items: list[dict] | None = None
        self._fetched_at = 0.0
        self._next_attempt = 0.0
        self.stale = False  # 갱신 실패로 TTL이 지난 캐시를 쓰는 중
        self.last_error: str | None = None

    def _load_disk(self) -> None:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            self._items = data["items"]
            self._fetched_at = datetime.fromisoformat(data["fetched_at"]).timestamp()
        except (OSError, ValueError, KeyError, TypeError):
            if self._file.exists():
                logger.warning("고유번호 캐시 파일이 손상되어 무시합니다: %s", self._file)

    async def companies(self) -> list[dict]:
        if self._items is not None and self._clock() - self._fetched_at < self._ttl:
            return self._items
        async with self._lock:
            if self._items is None:
                self._load_disk()
            now = self._clock()
            if self._items is not None and now - self._fetched_at < self._ttl:
                self.stale = False
                return self._items
            if self._items is not None and now < self._next_attempt:
                return self._items  # 직전 갱신 실패 후 대기 중 → stale 사용
            try:
                items = parse_corp_code_zip(await self._client.get_zip("/api/corpCode.xml", {}))
            except DartError as e:
                self.last_error = f"{e.code}: {e}"
                self._next_attempt = now + self._backoff
                if self._items is None:
                    raise
                self.stale = True
                logger.warning("고유번호 갱신 실패, 기존 캐시(%d건)를 사용합니다: %s", len(self._items), e.code)
                return self._items
            self._items, self._fetched_at, self.stale, self.last_error = items, now, False, None
            payload = {"fetched_at": datetime.fromtimestamp(now, UTC).isoformat(), "items": items}
            atomic_write(self._file, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return items

    async def resolve(self, query: str) -> tuple[CompanyHit | None, list[CompanyHit]]:
        return resolve(await self.companies(), query)
