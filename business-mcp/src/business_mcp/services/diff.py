"""get_filing_diff: 정정사항 표 → 변경 항목 조립·분류·점수·근거 (docs/04 §4, docs/07 §5-4).

변경값의 원천은 **정정 공시 안 정정사항 표에 회사가 적은 정정 전·후 값**입니다. 원본 문서 전체와의 비교가 아닙니다.
2차 이상 정정의 '정정 전'은 최초 원본이 아니라 바로 앞 버전 기준입니다(실제 원문으로 확인, docs/spike_notes.md).
변경값 추출과 수치 비교는 모두 결정적 규칙이며, 변경의 의미·영향 판단은 LangGraph가 맡습니다.
"""

import re

from business_mcp.errors import FilingNotFound, InvalidArgument, NotACorrection
from business_mcp.schemas import (
    Change,
    CorrectionHeader,
    CorrectionRef,
    Delta,
    DiffSummary,
    Evidence,
    Extraction,
    FilingDiff,
    Meta,
    Value,
    dart_url,
)
from business_mcp.services import field_dictionary
from business_mcp.services.matching import NUMERIC_TYPES, match_original
from dart_core.interface import DartCore
from dart_core.models import CorrectionItem, ParsedDocument, ParsedValue
from dart_core.normalize import NULL_TOKENS, parse_value

ENGINE_VERSION = "diff-0.1.0"
RCEPT_RE = re.compile(r"^\d{14}$")
FOOTNOTE_REF_RE = re.compile(r"\(\s*주\s*(\d+)\s*\)")
SUB_LABEL_RE = re.compile(r"^(?P<label>[^:：\d][^:：]{0,39})\s*[:：]\s*(?P<value>.+)$")
BULLET_RE = re.compile(r"^\s*[-–·•※▶]\s*")
PENALTY = {"FOOTNOTE_UNRESOLVED": 0.5, "UNIT_UNKNOWN": 0.3, "TYPE_MISMATCH": 0.3, "FREE_TEXT": 0.2,
           "MULTI_VALUE_CELL": 0.2, "MATCH_UNCERTAIN": 0.2, "LARGE_DELTA": 0.1}


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _split_item_label(item_label: str) -> tuple[str, str]:
    """'2. 계약내역 - 계약금액(원)'·'2. 계약내역 / 계약금액(원)' → ('2. 계약내역', '계약금액(원)'),
    '5. 계약기간' → ('5. 계약기간', '계약기간')."""
    label = _one_line(item_label)
    parts = [p.strip() for p in re.split(r"\s+[-/]\s+", label) if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return label, re.sub(r"^\s*\d+\s*[.)]\s*", "", label).strip()


def _strip_bullet(text: str) -> str:
    """'-2026년 10월 26일' → '2026년 10월 26일'. '-1,000'(음수)은 그대로 둡니다."""
    m = BULLET_RE.match(text)
    if not m or text.strip() in NULL_TOKENS:
        return text
    rest = text[m.end():]
    if rest[:1].isdigit() and parse_value(rest).value_type not in ("date", "date_range"):
        return text
    return rest


def _strip_label(text: str) -> tuple[str | None, str]:
    """'모집 또는 매출총액: 300,000,000,000원' → ('모집 또는 매출총액', '300,000,000,000원'). 한 줄 셀에만 적용."""
    t = _strip_bullet(text.strip())
    if "\n" not in t and (m := SUB_LABEL_RE.match(t)):
        return m.group("label").strip(), m.group("value").strip()
    return None, (t if "\n" not in t else text)


INLINE_ITEM_RE = re.compile(r"\s*(?=-\s*[^\d\s:：\-][^:：\n]{0,39}?\s*[:：])")


def _split_inline_items(text: str) -> str:
    """실제 dart4 원문은 셀 안 하위 항목 사이에 줄바꿈이 없음: '-주식 수 : 3,385,240-주식 총수 대비 비율(%): 11.18'.
    글머리 '-'로 시작하는 한 줄 셀에서 '-라벨:' 경계마다 줄을 나눕니다. '-' 뒤에 숫자가 오면(음수·날짜) 나누지 않고,
    나눈 조각이 모두 '라벨: 값' 형태일 때만 적용합니다."""
    t = text.strip()
    if "\n" in t or not t.startswith("-"):
        return text
    parts = [p.strip() for p in INLINE_ITEM_RE.split(t) if p.strip()]
    if len(parts) > 1 and all(SUB_LABEL_RE.match(_strip_bullet(p)) for p in parts):
        return "\n".join(parts)
    return text


def _labeled_lines(text: str) -> dict[str, str] | None:
    """여러 줄 셀이 모두 '-라벨: 값' 형태면 {라벨: 값}. 빈 셀은 {}. 아니면 None."""
    if text.strip() in NULL_TOKENS:
        return {}
    lines = [ln for ln in text.split("\n") if ln.strip()]
    out: dict[str, str] = {}
    for ln in lines:
        m = SUB_LABEL_RE.match(_strip_bullet(ln.strip()))
        if not m or m.group("label").strip() in out:
            return None
        out[m.group("label").strip()] = m.group("value").strip()
    return out


def _value(pv: ParsedValue) -> Value:
    raw = pv.raw if pv.raw is None or len(pv.raw) <= 2000 else pv.raw[:2000]
    return Value(raw=raw, value=pv.value, unit=pv.unit, raw_unit=pv.raw_unit, start=pv.start, end=pv.end)


def _quote(*parts: str | None) -> str:
    q = " | ".join(_one_line(p) for p in parts if p)
    return q if len(q) <= 300 else q[:299] + "…"


def _evidence(doc: ParsedDocument, rcept_no: str, item: CorrectionItem, used_footnote: list[str]) -> list[Evidence]:
    table = next((t for t in doc.tables if t.table_id == item.table_id), None)
    section = next((s for s in doc.sections if table and s.section_id == table.section_id), None)
    file_name = section.file_name if section else (doc.files[0]["file_name"] if doc.files else None)
    url = dart_url(rcept_no)
    ev = [Evidence(
        rcept_no=rcept_no, role="correction_table", file_name=file_name,
        section_id=section.section_id if section else None, section_title=section.title if section else None,
        table_id=item.table_id, row_index=item.table_row_index or item.row_index,
        quote=_quote(item.item_label, item.reason, item.before_raw, item.after_raw), dart_url=url,
    )]
    for text in used_footnote:
        ev.append(Evidence(rcept_no=rcept_no, role="correction_footnote", file_name=file_name, quote=_quote(text),
                           dart_url=url))
    return ev


def _classify(b: ParsedValue, a: ParsedValue, reasons: list[str], long_text: bool) -> tuple[str, str, Delta | None]:
    if b.value_type and a.value_type and b.value_type != a.value_type:
        value_type = "text"
        reasons.append("TYPE_MISMATCH")
    else:
        value_type = b.value_type or a.value_type or "text"
    if b.unit_unknown or a.unit_unknown:
        reasons.append("UNIT_UNKNOWN")
    if (b.multi_value or a.multi_value) and not long_text:
        reasons.append("MULTI_VALUE_CELL")
    if value_type == "text" and not reasons:
        reasons.append("FREE_TEXT")

    def same(x: ParsedValue, y: ParsedValue) -> bool:
        return (x.value, x.start, x.end) == (y.value, y.start, y.end)

    if b.value_type is None and a.value_type is not None:
        change_type = "added"
    elif a.value_type is None and b.value_type is not None:
        change_type = "removed"
    elif same(b, a):
        change_type = "reformatted"
    elif value_type == "text":
        change_type = "text_changed"
    else:
        change_type = "modified"

    delta = None
    if change_type == "modified" and value_type in NUMERIC_TYPES \
            and isinstance(b.value, int | float) and isinstance(a.value, int | float):
        diff = a.value - b.value
        pct = round(diff / b.value * 100, 4) if b.value else None
        delta = Delta(abs=round(diff, 6) if isinstance(diff, float) else diff, pct=pct)
        if pct is not None and abs(pct) >= 50:
            reasons.append("LARGE_DELTA")
    return value_type, change_type, delta


def _change(doc, rcept_no, item, change_id, field_label, field_key, section_label, b_txt, a_txt, unit_hint,
            reasons, used_footnote, match_status) -> Change:
    b = parse_value(b_txt, unit_hint, label=field_label)
    a = parse_value(a_txt, unit_hint, label=field_label)
    long_text = any(len(t) > 80 or "\n" in t.strip() for t in (b_txt, a_txt))
    value_type, change_type, delta = _classify(b, a, reasons, long_text)
    if match_status != "matched":
        reasons.append("MATCH_UNCERTAIN")
    confidence = round(max(0.0, 1.0 - sum(PENALTY[r] for r in reasons)), 3)
    return Change(
        change_id=change_id, field_key=field_key, field_label=field_label, section_label=section_label,
        change_type=change_type, value_type=value_type, before=_value(b), after=_value(a), delta=delta,
        reason=item.reason, regulator_ordered=item.regulator_ordered,
        evidence=_evidence(doc, rcept_no, item, used_footnote),
        extraction=Extraction(method="correction_footnote" if used_footnote else "correction_table",
                              rule_ids=sorted(set(b.rule_ids) | set(a.rule_ids))),
        confidence=confidence, needs_review=confidence < 0.7 or "FOOTNOTE_UNRESOLVED" in reasons,
        review_reasons=reasons,
    )


def build_changes(
    doc: ParsedDocument, rcept_no: str, item: CorrectionItem, unit_hint: str | None, match_status: str
) -> list[Change]:
    """정정사항 표 1행 → Change 1건. 셀이 '-라벨: 값' 여러 줄이면 라벨별 하위 Change(c{행}.{k})로 나눕니다."""
    base_reasons: list[str] = []
    used_footnote: list[str] = []
    texts = {}
    for side, raw, footnote in (("before", item.before_raw, item.before_footnote),
                                ("after", item.after_raw, item.after_footnote)):
        if footnote is not None:
            used_footnote.append(footnote)
        elif FOOTNOTE_REF_RE.search(raw) and "FOOTNOTE_UNRESOLVED" not in base_reasons:
            base_reasons.append("FOOTNOTE_UNRESOLVED")
        texts[side] = _split_inline_items(footnote if footnote is not None else raw)

    section_label, field_label = _split_item_label(item.item_label)
    change_id = f"{rcept_no}:c{item.row_index}"

    lb, la = _labeled_lines(texts["before"]), _labeled_lines(texts["after"])
    if lb is not None and la is not None and len(set(lb) | set(la)) > 1:
        labels = list(dict.fromkeys([*la, *lb]))
        parent = _one_line(item.item_label)
        return [
            _change(doc, rcept_no, item, f"{change_id}.{k}", sub,
                    field_dictionary.lookup(sub) or "raw:" + field_dictionary.normalize_label(f"{field_label}.{sub}"),
                    parent, lb.get(sub, "-"), la.get(sub, "-"), unit_hint, list(base_reasons), used_footnote,
                    match_status)
            for k, sub in enumerate(labels, start=1)
        ]

    sub_b, before_txt = _strip_label(texts["before"])
    sub_a, after_txt = _strip_label(texts["after"])
    if sub_a or sub_b:
        field_label = sub_a or sub_b
    field_key = field_dictionary.lookup(field_label) or "raw:" + field_dictionary.normalize_label(field_label)
    return [_change(doc, rcept_no, item, change_id, field_label, field_key, section_label, before_txt, after_txt,
                    unit_hint, base_reasons, used_footnote, match_status)]


async def get_filing_diff(
    dart: DartCore, correction_rcept_no: str, original_rcept_no: str | None = None, force_recompute: bool = False
) -> FilingDiff:
    # force_recompute: diff 결과 캐시(filing_changes, PostgreSQL)가 없어 지금은 항상 다시 계산합니다.
    # 원문 ZIP·파싱 캐시는 무효화하지 않습니다(접수번호별 원문은 불변, parser_version이 바뀌면 자동 재파싱).
    for name, v in (("correction_rcept_no", correction_rcept_no), ("original_rcept_no", original_rcept_no)):
        if v is not None and not RCEPT_RE.match(v):
            raise InvalidArgument(f"{name}는 14자리 숫자여야 합니다.", **{name: v})
    if original_rcept_no == correction_rcept_no:
        raise InvalidArgument("original_rcept_no가 correction_rcept_no와 같습니다.", original_rcept_no=original_rcept_no)

    corr = await dart.find_filing(correction_rcept_no)
    if corr is None:
        raise FilingNotFound(f"접수번호 {correction_rcept_no}의 공시를 찾을 수 없습니다.", rcept_no=correction_rcept_no)
    if not corr.is_correction:
        raise NotACorrection(
            f"접수번호 {correction_rcept_no}는 정정 공시가 아닙니다. 정정 공시 접수번호를 넣어 주세요.",
            rcept_no=corr.rcept_no, report_nm=corr.report_nm, has_later_correction=corr.has_later_correction,
        )

    doc = await dart.ingest_filing(correction_rcept_no)
    block = doc.correction
    match, warnings = await match_original(dart, corr, block, original_rcept_no)
    warnings.extend(doc.parse_warnings)
    incomplete = bool(doc.parse_warnings)

    changes: list[Change] = []
    if block:
        hints = {t.table_id: t.unit_hint for t in doc.tables}
        for item in sorted(block.items, key=lambda i: i.row_index):
            changes.extend(build_changes(doc, corr.rcept_no, item, hints.get(item.table_id), match.status))
        if block.unresolved_refs:
            warnings.append(f"해석하지 못한 각주: {', '.join(block.unresolved_refs)}")
        warnings.extend(block.parse_warnings)
        incomplete = incomplete or bool(block.parse_warnings)
        if not block.items and corr.correction_kind != "attachment":
            incomplete = True  # 표 미탐지·행 해석 실패를 '변경 없음'으로 확정하지 않음
            if not block.parse_warnings:
                warnings.append("정정사항 표에서 변경 항목을 추출하지 못했습니다.")
    elif corr.correction_kind != "attachment":
        incomplete = True
        warnings.append("정정 머리말 또는 정정사항 표를 찾지 못해 변경 항목을 추출하지 못했습니다.")
    if corr.correction_kind == "attachment" and not changes:
        warnings.append("첨부 정정: 본문 변경 없음")
    if len({c.change_id for c in changes}) != len(changes):
        incomplete = True
        warnings.append("change_id가 중복되었습니다 (정정사항 표 행 번호 확인 필요).")

    needs_review_count = sum(c.needs_review for c in changes)
    return FilingDiff(
        diff_id=f"{corr.rcept_no}:{ENGINE_VERSION}",
        correction=CorrectionRef(rcept_no=corr.rcept_no, report_nm=corr.report_nm, rcept_dt=corr.rcept_dt,
                                 correction_tags=corr.correction_tags, correction_kind=corr.correction_kind),
        match=match,
        correction_header=CorrectionHeader(target_document_name=block.target_document_name,
                                           first_submitted_date=block.first_submitted_date,
                                           history=block.history,
                                           previous_filing_date=block.previous_filing_date,
                                           related_disclosures=block.related_disclosures) if block else None,
        changes=changes,
        summary=DiffSummary(
            total=len(changes),
            numeric_changes=sum(c.value_type in NUMERIC_TYPES for c in changes),
            needs_review_count=needs_review_count,
            field_keys=list(dict.fromkeys(c.field_key for c in changes)),
        ),
        needs_review=match.needs_review or needs_review_count > 0 or incomplete,
        meta=Meta.build(dart.source, warnings, engine_version=ENGINE_VERSION, parser_version=doc.parser_version),
    )
