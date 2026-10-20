"""정정 머리말·정정사항 표·각주 → CorrectionBlock (docs/07 §5-2를 실제 원문 관찰로 보정).

관찰한 형식 (docs/spike_notes.md):
- 주요사항보고서(dart4): '1. 정정대상 공시서류 :' / '2. 정정대상 공시서류의 최초제출일 :' + 4열 표
  (항 목 | 정정사유 | 정 정 전 | 정 정 후). 07 문서 예시는 '정정요구ㆍ명령 관련 여부'가 더해진 5열.
- 거래소 수시공시(HTML): '1. 정정관련 공시서류' / '2. 정정관련 공시서류제출일'(앞 버전 날짜) / '3. 정정사유'(전체 공통)
  + 같은 표 안의 3열 머리글 (정정항목 | 정정전 | 정정후), 본문 끝 '※ 관련공시' 행.
열 위치는 머리글 텍스트로 찾습니다. 표를 못 찾거나 행을 해석하지 못하면 parse_warnings에 남깁니다.
"""

import re
from datetime import date

from dart_core.models import CorrectionBlock, CorrectionItem, ParsedDocument, Table
from dart_core.parsing.document import expand_grid

DETECT_RE = re.compile(r"정\s*정\s*신\s*고|정정\s*(대상|관련)\s*공시\s*서류")
DATE_RE = re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")
NUM_PREFIX = re.compile(r"^\s*\d+\s*[.)]\s*")
FOOTNOTE_MARK = re.compile(r"\(\s*주\s*(\d+)\s*\)\s*정\s*정\s*(전|후)\s*[:：]?")
FOOTNOTE_REF = re.compile(r"\(\s*주\s*(\d+)\s*\)")
MAX_FOOTNOTE = 2000


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", NUM_PREFIX.sub("", s or "")).rstrip(":：")


def _date(s: str | None) -> date | None:
    if s and (m := DATE_RE.search(s)):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _role(cell: str) -> str | None:
    k = _norm(cell)
    if k in ("항목", "정정항목", "정정대상항목"):
        return "item"
    if k in ("정정전", "변경전"):
        return "before"
    if k in ("정정후", "변경후"):
        return "after"
    if k == "정정사유":
        return "reason"
    if "정정요구" in k or "명령" in k:
        return "regulator"
    return None


def _header(grid: list[list[str]]) -> tuple[int, int, dict[str, int]] | None:
    """(머리글 시작 행, 머리글 행 수, {역할: 열}) — 머리글이 2행으로 나뉜 경우 열별로 이어 붙여 판정."""
    for h in range(len(grid)):
        for span in (1, 2):
            if h + span > len(grid):
                continue
            width = max(len(r) for r in grid[h:h + span])
            cols: dict[str, int] = {}
            for c in range(width):
                texts = [grid[r][c] for r in range(h, h + span) if c < len(grid[r])]
                role = next((x for x in (_role(t) for t in texts) if x), None) or _role("".join(texts))
                if role and role not in cols:
                    cols[role] = c
            if {"item", "before", "after"} <= cols.keys():
                return h, span, cols
    return None


def _kv_pairs(doc: ParsedDocument, file_prefix: str) -> list[tuple[str, str]]:
    pairs = []
    for t in doc.tables:
        if not t.table_id.startswith(file_prefix):
            continue
        for row in expand_grid(t):
            vals = [v for i, v in enumerate(row) if i == 0 or v != row[i - 1]]  # colspan 반복 제거
            if len(vals) >= 2:
                pairs.append((vals[0], vals[1]))
    for s in doc.sections:
        if s.section_id.startswith(file_prefix):
            for ln in s.text.split("\n"):
                if m := re.match(r"^(.{2,40}?)\s*[:：]\s*(.+)$", ln):
                    pairs.append((m.group(1), m.group(2)))
    return pairs


def _regulator(v: str) -> bool | None:
    k = _norm(v)
    if k in ("해당", "예", "O", "Y", "유"):
        return True
    if k in ("미해당", "아니오", "아니요", "-", "N", "X", "무", "해당없음", "해당사항없음"):
        return False
    return None


def _footnotes(doc: ParsedDocument, file_prefix: str, table_texts: list[str], warnings: list[str]) -> dict:
    notes: dict[str, dict] = {}
    for s in doc.sections:
        if not s.section_id.startswith(file_prefix):
            continue
        text = s.text
        for tt in table_texts:  # 정정사항 표 안의 '(주1) 정정 전 참조'는 각주 본문이 아님
            text = text.replace(tt, "")
        marks = list(FOOTNOTE_MARK.finditer(text))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            body = text[m.end():end].strip()
            if len(body) > MAX_FOOTNOTE:
                warnings.append(f"각주 주{m.group(1)} 정정{m.group(2)} 본문 경계가 불확실해 {MAX_FOOTNOTE}자에서 자름")
                body = body[:MAX_FOOTNOTE]
            side = "before" if m.group(2) == "전" else "after"
            notes.setdefault(f"주{m.group(1)}", {"before": None, "after": None})[side] = body or None
    return notes


def _table_text(t: Table) -> list[str]:
    """섹션 본문에 렌더링된 표 행과 같은 형태 (document._FileWalker._table_text + 공백 정리)."""
    return [re.sub(r"\s+", " ", " | ".join(c.text.replace("\n", " ") for c in row)).strip() for row in t.rows]


def parse_correction(doc: ParsedDocument) -> ParsedDocument:
    """정정 공시면 doc.correction을 채운 사본을, 아니면 doc을 그대로 반환합니다."""
    if not doc.sections:
        return doc
    prefix = doc.sections[0].section_id.split(".")[0] + "."  # 본문 파일(이름순 첫 파일)
    first = [s for s in doc.sections if s.section_id.startswith(prefix)]
    head = "\n".join(s.text for s in first[:3])[:5000]
    if not DETECT_RE.search(head):
        return doc

    warnings: list[str] = []
    target = first_date = prev_date = header_reason = None
    for label, value in _kv_pairs(doc, prefix):
        k = _norm(label)
        if re.fullmatch(r"정정(대상|관련)공시서류", k) and target is None:
            target = value.strip()
        elif "최초제출일" in k and first_date is None:
            first_date = _date(value)
        elif re.fullmatch(r"정정(대상|관련)공시서류(의)?제출일", k) and prev_date is None:
            prev_date = _date(value)
        elif k == "정정사유" and header_reason is None:
            header_reason = value.strip() or None

    items: list[CorrectionItem] = []
    table_texts: list[str] = []
    related: list[dict] = []
    for t in doc.tables:
        if not t.table_id.startswith(prefix):
            continue
        grid = expand_grid(t)
        for g_i, row in enumerate(grid):  # '※ 관련공시' 행 ('정정관련 공시서류'와 구분하려고 전체 일치)
            if row and re.fullmatch(r"※?관련공시", _norm(row[0])):
                cell_links = [ln for c in (t.rows[g_i] if g_i < len(t.rows) else []) for ln in c.links]
                for v in dict.fromkeys(row[1:]):
                    for ln in v.split("\n"):
                        if d := _date(ln):
                            name = DATE_RE.sub("", ln, count=1).strip() or None
                            related.append({"date": d.isoformat(), "document_name": name, "rcept_no": None})
                for i, ref in enumerate(cell_links):  # DART 링크 → rcept_no, KIND 링크 → kind_acptno(매칭에 쓰지 않음)
                    key, val = ("kind_acptno", ref[5:]) if ref.startswith("kind:") else ("rcept_no", ref)
                    if i < len(related):
                        related[i][key] = val
                    else:
                        related.append({"date": None, "document_name": None, "rcept_no": None, key: val})
        found = _header(grid)
        if not found:
            continue
        h, span, cols = found
        table_texts.extend(_table_text(t))
        need = max(cols["item"], cols["before"], cols["after"])
        last_label = None
        table_row = 0
        for r_i, row in enumerate(grid[h + span:], start=h + span):
            if not any(v.strip() for v in row) or len(set(row)) == 1:
                continue  # 빈 행, 전체 병합 행
            if len(row) <= need:
                warnings.append(f"{t.table_id} 행 {r_i}: 열이 부족해 해석하지 못함")
                continue
            label = row[cols["item"]].strip() or last_label
            if not label:
                warnings.append(f"{t.table_id} 행 {r_i}: 항목 라벨이 없음")
                continue
            last_label = label
            table_row += 1
            items.append(CorrectionItem(
                row_index=len(items) + 1, table_row_index=table_row, item_label=label,
                regulator_ordered=_regulator(row[cols["regulator"]]) if "regulator" in cols else None,
                reason=(row[cols["reason"]].strip() or None) if "reason" in cols else header_reason,
                before_raw=row[cols["before"]], after_raw=row[cols["after"]], table_id=t.table_id,
            ))
    if not table_texts:
        warnings.append("정정 머리말은 있으나 정정사항 표(항목·정정 전·정정 후)를 찾지 못함")
    elif not items:
        warnings.append("정정사항 표에 해석 가능한 항목 행이 없음")

    footnotes = _footnotes(doc, prefix, table_texts, warnings)
    unresolved: list[str] = []
    for item in items:
        for side, raw in (("before", item.before_raw), ("after", item.after_raw)):
            for m in FOOTNOTE_REF.finditer(raw):
                key = f"주{m.group(1)}"
                body = footnotes.get(key, {}).get(side)
                if body is None:
                    if key not in unresolved:
                        unresolved.append(key)
                elif side == "before":
                    item.before_footnote = body
                else:
                    item.after_footnote = body

    block = CorrectionBlock(
        target_document_name=target, first_submitted_date=first_date, history=[], items=items,
        footnotes=footnotes, unresolved_refs=unresolved, previous_filing_date=prev_date,
        related_disclosures=related, parse_warnings=warnings,
    )
    return doc.model_copy(update={"correction": block})
