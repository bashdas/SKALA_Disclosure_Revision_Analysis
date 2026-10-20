"""정정 공시 → 원본·직전본 매칭 (docs/03 §3 Q2, docs/07 §5-3). 결정적 규칙만 씁니다.

실제 원문으로 확인해 보강한 부분 (docs/spike_notes.md):
- 거래소 수시공시 머리말의 '정정관련 공시서류제출일'과 '※ 관련공시'는 최초 원본이 아니라 **바로 앞 버전**을 가리킵니다.
  이 경우 앞 버전을 한 단계씩 거슬러 올라가며(_walk_back) 각 단계를 '정정 전 값이 앞 버전 원문에 있는지'로 검증합니다.
- 같은 회사·같은 제목의 정정이라도 다른 사건일 수 있어, chain에는 연결이 확인된 정정만 넣습니다.
- 목록이 페이지 상한으로 잘렸으면 후보가 빠졌을 수 있으므로 단일 후보여도 matched로 확정하지 않습니다.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from business_mcp.errors import FilingNotFound, InvalidArgument
from business_mcp.schemas import FilingRef, Match, MatchCandidate, MatchSignal
from dart_core.interface import DartCore
from dart_core.models import CorrectionBlock, FilingMeta, ParsedDocument
from dart_core.normalize import NULL_TOKENS, parse_value
from dart_core.status import DartError
from dart_core.titles import compare_key, split_tags

W = {"S4_first_submit_date": 0.45, "S5_rm_flag": 0.15, "S6_target_name": 0.10, "S7_before_value_found": 0.20,
     "S8_unique": 0.10}
NUMERIC_TYPES = {"amount", "shares", "ratio", "price", "number"}
WINDOW = timedelta(days=365)
MAX_HOPS = 5  # 앞 버전 추적 상한 (단계마다 원문 1~N건 조회)
MAX_INTERMEDIATE_CHECKS = 5
NUM_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")
DATE_ANY = re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?")


def _sig(id_: str, passed: bool | None, detail: str | None = None) -> MatchSignal:
    return MatchSignal(id=id_, passed=passed, weight=W.get(id_, 0), detail=detail)


def _ref(f: FilingMeta) -> FilingRef:
    return FilingRef(rcept_no=f.rcept_no, report_nm=f.report_nm, rcept_dt=f.rcept_dt)


def _confidence(signals: list[MatchSignal]) -> float:
    return round(min(1.0, sum(s.weight for s in signals if s.passed)), 3)


def _target_name_matches(block: CorrectionBlock | None, key: str) -> bool:
    return bool(block and block.target_document_name and compare_key(split_tags(block.target_document_name)[1]) == key)


# ── 정정 전 값 대조 (S7, 앞 버전 검증) ────────────────────────────────────


def _has_number(text: str, token: str) -> bool:
    """숫자 경계를 지킨 일치: '5,000,000,000'은 '15,000,000,000'이나 '5,000,000,0001'에 맞지 않음."""
    pattern = rf"(?<![\d,.]){re.escape(token)}(?![\d]|[,.]\d)"
    return re.search(pattern, text) is not None


def _iso_dates(text: str) -> str:
    def iso(m: re.Match) -> str:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return m.group(0)
    return DATE_ANY.sub(iso, text)


def _doc_text(doc: ParsedDocument) -> str:
    return "\n".join([s.text for s in doc.sections] + [c.text for t in doc.tables for r in t.rows for c in r])


def _number_tokens(text: str) -> list[str]:
    return [t for t in NUM_TOKEN.findall(text) if len(t.replace(",", "").replace(".", "")) >= 3]


def _before_number_tokens(block: CorrectionBlock) -> set[str]:
    """정정 전 값 중 숫자형 셀의 숫자 원문 토큰 (S7). 1~2자리 숫자는 우연히 겹치기 쉬워 제외."""
    tokens: set[str] = set()
    for item in block.items:
        text = item.before_footnote or item.before_raw
        if parse_value(text, label=item.item_label).value_type in NUMERIC_TYPES:
            tokens.update(_number_tokens(text))
    return tokens


def _contains_number(text: str, token: str) -> bool:
    return _has_number(text, token) or ("," in token and _has_number(text, token.replace(",", "")))


def _strong(token: str) -> bool:
    """우연히 겹치기 어려운 숫자: 콤마가 있거나 5자리 이상 (연도 '2023' 같은 4자리는 약함)."""
    return "," in token or len(token.replace(".", "")) >= 5


def _before_hits(doc: ParsedDocument, block: CorrectionBlock) -> tuple[int, int]:
    """(일치 항목 수, 대조 가능 항목 수) — 정정 전 값이 앞 버전 원문에 있는지.

    - 숫자·날짜형 값: 3자리 이상 숫자와 날짜가 모두 원문에 있으면 일치(숫자 경계 유지)
    - 문장형 값: 공백을 뺀 앞 30자가 원문에 있으면 일치. 없을 때는 강한 숫자(콤마·5자리 이상)가 있고
      모두 원문에 있을 때만 일치 — 실제 원문에서 연도 숫자만으로 다른 사건 정정이 일치한 사례가 있었음
    """
    text = _doc_text(doc)
    iso_text = _iso_dates(text)
    compact = re.sub(r"\s+", "", text)
    hits = checkable = 0
    for item in block.items:
        before = (item.before_footnote or item.before_raw or "").strip()
        if before in NULL_TOKENS:
            continue
        iso_before = _iso_dates(before)
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", iso_before)
        numbers = _number_tokens(re.sub(r"\d{4}-\d{2}-\d{2}", " ", iso_before))
        tokens_ok = all(d in iso_text for d in dates) and all(_contains_number(text, n) for n in numbers)
        if parse_value(before, label=item.item_label).value_type != "text":
            if dates or numbers:
                checkable += 1
                hits += tokens_ok
            continue
        snippet = re.sub(r"\s+", "", before)[:30]
        strong = [n for n in numbers if _strong(n)]
        if len(snippet) >= 10:
            checkable += 1
            hits += snippet in compact or (bool(strong) and tokens_ok)
        elif strong or dates:
            checkable += 1
            hits += tokens_ok
    return hits, checkable


async def _filter_by_before_values(
    dart: DartCore, cands: list[FilingMeta], block: CorrectionBlock
) -> tuple[list[FilingMeta] | None, str]:
    """S7: 정정 전 숫자값이 후보 원문에 실제로 있는 후보만. 계산 불가면 (None, 사유)."""
    tokens = _before_number_tokens(block)
    if not tokens:
        return None, "정정 전 숫자값 없음"
    passed = []
    for c in cands:
        try:
            doc = await dart.ingest_filing(c.rcept_no)
        except DartError:
            return None, f"후보 원문 조회 실패: {c.rcept_no}"
        text = _doc_text(doc)
        if any(_contains_number(text, tok) for tok in tokens):
            passed.append(c)
    return passed, f"후보 {len(cands)}건 중 {len(passed)}건에서 정정 전 값 발견"


# ── 앞 버전 추적 (수시공시) ──────────────────────────────────────────────


@dataclass
class _Walk:
    chain: list[FilingMeta]  # 오래된 순, 마지막이 입력 정정
    original: FilingMeta | None = None
    steps: list[str] = field(default_factory=list)
    all_verified: bool = True  # 모든 단계가 정정 전 값 또는 명시 링크로 확인됨
    first_hop_values: bool | None = None  # 첫 단계에서 정정 전 값이 앞 버전 원문에 있었는가


def _pointers(block: CorrectionBlock) -> list[tuple[str, str | date]]:
    out: list[tuple[str, str | date]] = []
    for r in block.related_disclosures:
        if r.get("rcept_no"):
            out.append(("link", r["rcept_no"]))
    if block.previous_filing_date:
        out.append(("header_date", block.previous_filing_date))
    for r in block.related_disclosures:
        if r.get("date"):
            d = date.fromisoformat(r["date"])
            if ("header_date", d) not in out:
                out.append(("related_date", d))
    return out


async def _find_previous(dart: DartCore, cur: FilingMeta, block: CorrectionBlock, key: str,
                         ) -> tuple[FilingMeta | None, str, bool, bool | None]:
    """(앞 버전, 설명, 검증됨, 정정 전 값 일치 여부)."""
    tried: list[str] = []
    for kind, ptr in _pointers(block):
        if kind == "link":
            f = await dart.find_filing(ptr, cur.corp_code)
            cands = [f] if f and f.corp_code == cur.corp_code and compare_key(f.base_report_nm) == key \
                and f.rcept_no < cur.rcept_no else []
        else:
            rows, total = await dart.list_filings(cur.corp_code, ptr, ptr, last_reprt_at="N", max_pages=3)
            if len(rows) < total:
                tried.append(f"{ptr} 목록 잘림")
                continue
            cands = [f for f in rows if compare_key(f.base_report_nm) == key and f.rcept_no < cur.rcept_no
                     and not f.is_withdrawn]
        label = {"link": "관련공시 링크", "header_date": "머리말 정정관련 공시서류제출일",
                 "related_date": "관련공시 일자"}[kind]
        if not cands:
            tried.append(f"{label} {ptr}: 후보 없음")
            continue
        scored = []
        for c in cands:
            try:
                hits, checkable = _before_hits(await dart.ingest_filing(c.rcept_no), block)
            except DartError:
                hits, checkable = -1, -1
            scored.append((c, hits, checkable))
        full = [s for s in scored if s[2] > 0 and s[1] == s[2]]
        if len(full) == 1:
            c, hits, checkable = full[0]
            return c, f"{label} {ptr} → {c.rcept_no} (정정 전 값 {hits}/{checkable} 일치)", True, True
        if not full and len(scored) == 1 and scored[0][2] == 0:
            c = scored[0][0]
            verified = kind == "link"
            return c, f"{label} {ptr} → {c.rcept_no} (대조할 정정 전 값 없음, 단일 후보)", verified, None
        tried.append(f"{label} {ptr}: 후보 {len(cands)}건 중 정정 전 값 완전 일치 {len(full)}건")
    return None, "; ".join(tried) or "앞 버전 단서 없음", False, None


async def _walk_back(dart: DartCore, corr: FilingMeta, block: CorrectionBlock, key: str) -> _Walk:
    walk = _Walk(chain=[corr])
    cur, cur_block = corr, block
    for hop in range(MAX_HOPS):
        prev, how, verified, values = await _find_previous(dart, cur, cur_block, key)
        walk.steps.append(how)
        if hop == 0:
            walk.first_hop_values = values
        if prev is None:
            walk.all_verified = False
            return walk
        walk.all_verified = walk.all_verified and verified
        walk.chain.insert(0, prev)
        if not prev.is_correction:
            walk.original = prev
            return walk
        try:
            prev_block = (await dart.ingest_filing(prev.rcept_no)).correction
        except DartError:
            prev_block = None
        if prev_block is None:
            walk.steps.append(f"{prev.rcept_no}: 정정 머리말 해석 불가")
            walk.all_verified = False
            return walk
        if prev_block.first_submitted_date:  # 앞 버전이 '최초제출일'을 적은 형식이면 원본으로 바로 이동
            rows, total = await dart.list_filings(cur.corp_code, prev_block.first_submitted_date,
                                                  prev_block.first_submitted_date, max_pages=3)
            origs = [f for f in rows if compare_key(f.base_report_nm) == key and not f.is_correction
                     and not f.is_withdrawn and f.rcept_no < prev.rcept_no]
            if len(origs) == 1 and len(rows) == total:
                walk.chain.insert(0, origs[0])
                walk.original = origs[0]
                walk.steps.append(f"{prev.rcept_no} 머리말 최초제출일 → {origs[0].rcept_no}")
                return walk
        cur, cur_block = prev, prev_block
    walk.steps.append(f"앞 버전 추적 상한 {MAX_HOPS}단계 도달")
    walk.all_verified = False
    return walk


async def _verified_intermediates(dart: DartCore, original: FilingMeta, same: list[FilingMeta],
                                  block: CorrectionBlock | None, warnings: list[str]) -> list[FilingMeta]:
    """원본과 입력 정정 사이의 같은 제목 정정 중 같은 사건임이 확인된 것만 (정정 연혁 일자 또는 같은 최초제출일)."""
    later = sorted((f for f in same if f.is_correction and f.rcept_no > original.rcept_no), key=lambda f: f.rcept_no)
    if not later:
        return []
    history_dates = {str(h.get("date")) for h in (block.history if block else [])}
    first_date = block.first_submitted_date if block else None
    kept, dropped, checks = [], [], 0
    for f in later:
        if f.rcept_dt.isoformat() in history_dates:
            kept.append(f)
            continue
        if first_date and checks < MAX_INTERMEDIATE_CHECKS:
            checks += 1
            try:
                fb = (await dart.ingest_filing(f.rcept_no)).correction
            except DartError:
                fb = None
            if fb and fb.first_submitted_date == first_date:
                kept.append(f)
                continue
        dropped.append(f.rcept_no)
    if dropped:
        warnings.append(f"같은 제목이지만 같은 사건임을 확인하지 못한 정정은 chain에서 제외: {', '.join(dropped)}")
    return kept


class _DocMemo:
    """한 번의 매칭 안에서 같은 원문을 다시 내려받지 않도록 결과(성공·실패)를 기억하는 DartCore 래퍼."""

    def __init__(self, dart: DartCore):
        self._dart = dart
        self._docs: dict[str, ParsedDocument | DartError] = {}
        self.source = dart.source

    async def ingest_filing(self, rcept_no: str) -> ParsedDocument:
        if rcept_no not in self._docs:
            try:
                self._docs[rcept_no] = await self._dart.ingest_filing(rcept_no)
            except DartError as e:
                self._docs[rcept_no] = e
        result = self._docs[rcept_no]
        if isinstance(result, DartError):
            raise result
        return result

    def __getattr__(self, name):
        return getattr(self._dart, name)


# ── 진입점 ───────────────────────────────────────────────────────────────


async def match_original(
    dart: DartCore, corr: FilingMeta, block: CorrectionBlock | None, user_original: str | None = None
) -> tuple[Match, list[str]]:
    warnings: list[str] = []
    dart = _DocMemo(dart)
    first_date = block.first_submitted_date if block else None
    start = corr.rcept_dt - WINDOW
    if first_date and first_date <= corr.rcept_dt:
        start = min(start, first_date)
    rows, total = await dart.list_filings(corr.corp_code, start, corr.rcept_dt, last_reprt_at="N", max_pages=3)
    truncated = len(rows) < total
    if truncated:
        warnings.append(f"원본 후보 목록이 잘렸습니다 ({len(rows)}/{total}건). 후보가 빠졌을 수 있어 확정하지 않습니다.")

    key = compare_key(corr.base_report_nm)
    same = [
        f for f in rows
        if f.corp_code == corr.corp_code  # S1
        and compare_key(f.base_report_nm) == key  # S2
        and f.rcept_no < corr.rcept_no and not f.is_withdrawn  # S3
    ]
    base_signals = [_sig("S1_corp", True), _sig("S2_title", True, corr.base_report_nm), _sig("S3_order", True)]
    s6 = _sig("S6_target_name", _target_name_matches(block, key), block.target_document_name if block else None)

    if user_original:
        return await _user_specified(dart, corr, block, user_original, same, key, s6, warnings), warnings

    walk: _Walk | None = None
    if block and not first_date and _pointers(block):
        walk = await _walk_back(dart, corr, block, key)
        if walk.original:
            return _walk_match(walk, base_signals, s6, warnings), warnings
        warnings.append("앞 버전 추적으로 원본에 닿지 못했습니다: " + " / ".join(walk.steps))

    upper = walk.chain[0].rcept_no if walk else corr.rcept_no
    cands = [f for f in same if not f.is_correction and f.rcept_no < upper]
    signals = list(base_signals)
    if first_date:
        narrowed = [f for f in cands if f.rcept_dt == first_date]
        signals.append(_sig("S4_first_submit_date", bool(narrowed), f"머리말 최초제출일 {first_date.isoformat()}"))
        if narrowed:
            cands = narrowed
        else:
            warnings.append("머리말 최초제출일과 접수일이 일치하는 원본 후보가 없습니다.")
    else:
        signals.append(_sig("S4_first_submit_date", None, "정정 머리말에서 최초제출일을 찾지 못함"))
        warnings.append("정정 머리말에 최초제출일이 없어 최초제출일 신호(S4)를 계산하지 못했습니다.")

    s7_by_rcept: dict[str, bool] = {}
    if len(cands) > 1 and block:
        passed, detail = await _filter_by_before_values(dart, cands, block)
        if passed is None:
            s7 = _sig("S7_before_value_found", None, detail)
        else:
            s7_by_rcept = {c.rcept_no: c in passed for c in cands}
            distinguishes = 0 < len(passed) < len(cands)
            s7 = _sig("S7_before_value_found", distinguishes, detail)
            if passed:
                cands = passed
    else:
        s7 = _sig("S7_before_value_found", None, "후보 1건이라 미계산" if len(cands) == 1 else "후보 없음")

    # 목록이 잘렸거나, 앞 버전 추적이 원본에 닿지 못한 경우에는 연결이 확인되지 않은 단일 후보를 확정하지 않음
    one = cands[0] if len(cands) == 1 and not truncated and walk is None else None
    signals += [
        _sig("S5_rm_flag", one is not None and one.has_later_correction, f"rm='{one.rm or ''}'" if one else None),
        s6,
        s7,
        _sig("S8_unique", one is not None, f"원본 후보 {len(cands)}건" + (" (목록 잘림)" if truncated else "")
             + (" (앞 버전 추적 미완료로 확정 보류)" if walk else "")),
    ]
    signals.sort(key=lambda s: s.id)
    confidence = _confidence(signals)
    status = "matched" if one else ("ambiguous" if cands else "not_found")

    candidates: list[MatchCandidate] = []
    if not one:
        for c in sorted(cands, key=lambda f: f.rcept_no):
            score = (W["S4_first_submit_date"] if first_date and c.rcept_dt == first_date else 0) \
                + (W["S5_rm_flag"] if c.has_later_correction else 0) \
                + (W["S6_target_name"] if s6.passed else 0) \
                + (W["S7_before_value_found"] if s7_by_rcept.get(c.rcept_no) and s7.passed else 0)
            candidates.append(MatchCandidate(**_ref(c).model_dump(), score=round(score, 3)))
    if status == "not_found":
        warnings.append("조회 기간 안에서 원본 후보를 찾지 못했습니다 (기간 밖이거나 원본 철회 가능).")

    needs_review = status != "matched" or confidence < 0.8
    if walk:  # 앞 버전 추적이 중간에 멈춤: 확인된 구간만 chain에 넣고 원본과의 연결은 미확인으로 표시
        chain_metas = ([one] if one else []) + walk.chain
        previous = walk.chain[-2] if len(walk.chain) > 1 else one
        needs_review = True
    else:
        middle = await _verified_intermediates(dart, one, same, block, warnings) if one else []
        chain_metas = ([one] if one else []) + middle + [corr]
        previous = chain_metas[-2] if one else None
    match = Match(
        status=status,
        original_rcept_no=one.rcept_no if one else None,
        previous_rcept_no=previous.rcept_no if previous else None,
        chain=[_ref(f) for f in sorted(chain_metas, key=lambda f: f.rcept_no)],
        confidence=confidence,
        needs_review=needs_review,
        signals=signals,
        candidates=candidates,
    )
    return match, warnings


def _walk_match(walk: _Walk, base_signals: list[MatchSignal], s6: MatchSignal, warnings: list[str]) -> Match:
    original = walk.original
    signals = [
        *base_signals,
        _sig("S4_first_submit_date", walk.all_verified, "앞 버전 추적: " + " → ".join(walk.steps)),
        _sig("S5_rm_flag", original.has_later_correction, f"rm='{original.rm or ''}'"),
        s6,
        _sig("S7_before_value_found", walk.first_hop_values,
             "첫 단계 앞 버전 원문에서 정정 전 값 대조" if walk.first_hop_values is not None else "대조할 정정 전 값 없음"),
        _sig("S8_unique", True, "단계마다 앞 버전 1건"),
    ]
    signals.sort(key=lambda s: s.id)
    confidence = _confidence(signals)
    if not walk.all_verified:
        warnings.append("앞 버전 추적 중 정정 전 값으로 확인하지 못한 단계가 있습니다.")
    return Match(
        status="matched",
        original_rcept_no=original.rcept_no,
        previous_rcept_no=walk.chain[-2].rcept_no,
        chain=[_ref(f) for f in walk.chain],
        confidence=confidence,
        needs_review=confidence < 0.8 or not walk.all_verified,
        signals=signals,
        candidates=[],
    )


async def _user_specified(dart, corr, block, user_original, same, key, s6, warnings) -> Match:
    """사용자가 원본을 직접 지정: S1~S3만 검증하고 status=user_specified."""
    f = next((x for x in same if x.rcept_no == user_original), None) or await dart.find_filing(
        user_original, corr.corp_code
    )
    if f is None:
        raise FilingNotFound(f"원본으로 지정한 접수번호 {user_original}을 찾을 수 없습니다.", rcept_no=user_original)
    failed = [
        name for name, ok in [
            ("S1_corp", f.corp_code == corr.corp_code),
            ("S2_title", compare_key(f.base_report_nm) == key),
            ("S3_order", f.rcept_no < corr.rcept_no and not f.is_withdrawn),
        ] if not ok
    ]
    if failed:
        raise InvalidArgument(
            "지정한 원본이 이 정정 공시의 원본 조건(같은 회사, 같은 제목, 더 이른 접수, 미철회)을 만족하지 않습니다.",
            original_rcept_no=user_original, failed_signals=failed,
        )
    first_date = block.first_submitted_date if block else None
    signals = [
        _sig("S1_corp", True), _sig("S2_title", True, corr.base_report_nm), _sig("S3_order", True),
        _sig("S4_first_submit_date", (f.rcept_dt == first_date) if first_date else None),
        _sig("S5_rm_flag", f.has_later_correction, f"rm='{f.rm or ''}'"),
        s6,
        _sig("S7_before_value_found", None, "사용자 지정이라 미계산"),
        _sig("S8_unique", None, "사용자 지정이라 미계산"),
    ]
    middle = await _verified_intermediates(dart, f, same, block, warnings)
    chain = [_ref(x) for x in [f, *middle, corr]]
    return Match(
        status="user_specified",
        original_rcept_no=f.rcept_no,
        previous_rcept_no=chain[-2].rcept_no,
        chain=chain,
        confidence=_confidence(signals),
        needs_review=True,  # status != matched (03 §3 Q2 규칙 5)
        signals=signals,
        candidates=[],
    )
