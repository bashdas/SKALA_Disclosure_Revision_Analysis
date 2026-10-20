"""값 정규화 (docs/05 §7). 원문 셀 텍스트 → 기준 단위 숫자/날짜/기간/텍스트.

05 §3 시그니처 `parse_value(raw, unit_hint)`에 키워드 인자 `label`을 추가했습니다.
R-PCT-01(라벨의 (%)·비율·대비)과 R-PRC-01(라벨의 가액·가격)은 라벨 없이는 적용할 수 없기 때문입니다.
단위 우선순위: 셀 안 단위(R-UNIT-CELL) > 라벨의 괄호 단위 > 라벨 키워드 > 표 unit_hint.
"""

import re
from datetime import date
from decimal import Decimal

from dart_core.models import ParsedValue

NULL_TOKENS = {"", "-", "–", "—", "해당사항 없음", "해당사항없음", "해당없음", "삭제"}

# 단위 표기 → (unit, value_type, 배율)
UNITS: dict[str, tuple[str, str, Decimal]] = {
    "원/주": ("KRW_PER_SHARE", "price", Decimal(1)),
    "원": ("KRW", "amount", Decimal(1)),
    "천원": ("KRW", "amount", Decimal(10) ** 3),
    "백만원": ("KRW", "amount", Decimal(10) ** 6),
    "억원": ("KRW", "amount", Decimal(10) ** 8),
    "조원": ("KRW", "amount", Decimal(10) ** 12),
    "주": ("SHARES", "shares", Decimal(1)),
    "%": ("PERCENT", "ratio", Decimal(1)),
}
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))

_NUM = r"[(△▲\-]?\s*\d[\d,]*(?:\.\d+)?\)?"
NUMBER_ONLY_RE = re.compile(rf"^(?P<num>{_NUM})\s*(?P<unit>{_UNIT_ALT})?$")
ANY_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_DATE = r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?\.?"
DATE_RE = re.compile(rf"^{_DATE}$")
DATE_RANGE_RE = re.compile(rf"^{_DATE}\s*(?:~|∼|～|부터)\s*{_DATE}\s*(?:까지)?$")
LABEL_UNIT_RE = re.compile(rf"\(\s*(?:단위\s*[:：]\s*)?({_UNIT_ALT})\s*\)")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _to_date(y: str, m: str, d: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _to_number(token: str) -> Decimal:
    t = token.replace(" ", "")
    negative = t.startswith(("(", "△", "▲", "-")) or t.endswith(")")
    digits = t.strip("()△▲-").replace(",", "")
    n = Decimal(digits)
    return -n if negative else n


def _plain(n: Decimal) -> int | float:
    return int(n) if n == n.to_integral_value() else float(n)


def _hint_unit(unit_hint: str | None, label: str | None) -> tuple[str | None, str | None, bool]:
    """(단위 표기, 규칙 ID, 판정 실패 여부). 셀에 단위가 없을 때 쓸 단위를 정합니다."""
    if label:
        if m := LABEL_UNIT_RE.search(label):
            return m.group(1), None, False
        if re.search(r"가액|가격", label):
            return "원/주", "R-PRC-01", False
        if re.search(r"비율|대비", label):
            return "%", "R-PCT-01", False
    if unit_hint:
        found = [u for u in sorted(UNITS, key=len, reverse=True) if u in unit_hint]
        # '백만원'에는 '원'도 들어 있으므로 가장 긴 표기 하나만 남김
        found = [u for u in found if not any(u != o and u in o for o in found)]
        if len(found) == 1:
            return found[0], "R-AMT-02" if UNITS[found[0]][1] == "amount" else None, False
        return None, None, True  # '(단위 : 원, 주)'처럼 둘 이상이면 판정 불가
    return None, None, True


def parse_value(raw: str | None, unit_hint: str | None = None, *, label: str | None = None) -> ParsedValue:
    text = _clean(raw or "")

    if text in NULL_TOKENS:
        return ParsedValue(raw=raw, value=None, unit="NONE", value_type=None, rule_ids=["R-NULL-01"])

    if m := DATE_RANGE_RE.match(text):
        start, end = _to_date(*m.groups()[:3]), _to_date(*m.groups()[3:])
        if start and end:
            return ParsedValue(raw=raw, value=None, unit="DATE", start=start, end=end,
                               value_type="date_range", rule_ids=["R-DATE-RANGE-01"])

    if (m := DATE_RE.match(text)) and (d := _to_date(*m.groups())):
        return ParsedValue(raw=raw, value=d.isoformat(), unit="DATE", value_type="date", rule_ids=["R-DATE-01"])

    if m := NUMBER_ONLY_RE.match(text):
        n = _to_number(m.group("num"))
        rules: list[str] = []
        cell_unit = m.group("unit")
        if cell_unit:
            unit_txt, unknown = cell_unit, False
            rules.append("R-UNIT-CELL")
        else:
            unit_txt, rule, unknown = _hint_unit(unit_hint, label)
            if rule:
                rules.append(rule)
        if unknown or unit_txt is None:
            return ParsedValue(raw=raw, value=_plain(n), unit="NONE", value_type="number", unit_unknown=True)

        unit, value_type, scale = UNITS[unit_txt]
        family = {"amount": "R-AMT-01", "shares": "R-SHR-01", "ratio": "R-PCT-01", "price": "R-PRC-01"}[value_type]
        if value_type == "amount" and scale != 1:
            family = "R-AMT-03" if cell_unit else "R-AMT-02"
        if family not in rules:
            rules.insert(0, family)
        return ParsedValue(raw=raw, value=_plain(n * scale), unit=unit, raw_unit=unit_txt,
                           value_type=value_type, rule_ids=rules)

    multi = len(ANY_NUMBER_RE.findall(text)) > 1
    return ParsedValue(raw=raw, value=text, unit="NONE", value_type="text", rule_ids=["R-TEXT-01"], multi_value=multi)
