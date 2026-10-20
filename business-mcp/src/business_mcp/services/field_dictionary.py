"""정정 항목 라벨 → 표준 field_key 사전 (docs/04 §4-4). 사전에 없으면 None → 'raw:<라벨>'.

실제 원문 라벨(docs/spike_notes.md)에 맞춰 보강: '계약기간(종료일)', '2. 계약내역 / 계약금액(원)', '5. 사채만기일'.
'시작일'·'종료일' 단독은 전환청구기간 등 다른 문맥에도 쓰이므로 '계약기간' 문맥이 있을 때만 계약 날짜로 봅니다.
"""

import re

from dart_core.titles import DOTS

FIELDS: dict[str, list[str]] = {
    "contract_amount": ["계약금액", "확정계약금액"],
    "contract_period": ["계약기간"],
    "contract_start_date": ["계약기간시작일", "계약시작일"],
    "contract_end_date": ["계약기간종료일", "계약종료일"],
    "revenue_ratio": ["매출액대비", "최근매출액대비"],
    "counterparty": ["계약상대", "계약상대방"],
    "offering_amount": ["모집또는매출총액", "발행총액", "권면총액"],
    "conversion_price": ["전환가액"],
    "conversion_period": ["전환청구기간"],
    "subscription_date": ["청약일"],
    "payment_date": ["납입일"],
    "maturity_date": ["사채만기일"],
    "new_shares": ["신주의수", "발행할주식의수"],
    "issue_price": ["발행가액", "신주발행가액"],
    "board_resolution_date": ["이사회결의일"],
    "fund_purpose_facility": ["시설자금"],
    "fund_purpose_operating": ["운영자금"],
    "fund_purpose_debt_repayment": ["채무상환자금"],
    "fund_purpose_securities_acquisition": ["타법인증권취득자금"],
}


def normalize_label(label: str) -> str:
    """'raw:' 키용. 공백 제거, 가운뎃점 통일."""
    return re.sub(r"\s+", "", label.translate(DOTS))


def _best(key: str) -> str | None:
    best: tuple[int, int, str] | None = None
    for field_key, synonyms in FIELDS.items():
        for s in synonyms:
            pos = key.rfind(s)
            if pos >= 0:
                cand = (pos + len(s), len(s), field_key)
                if best is None or cand[:2] > best[:2]:
                    best = cand
    return best[2] if best else None


def lookup(label: str) -> str | None:
    """동의어 부분 일치. 여러 개면 가장 뒤에 나오는(더 구체적인) 것, 같으면 긴 것.

    괄호 안 글자를 살린 키('계약기간(종료일)' → 계약기간종료일)로 먼저 찾고,
    없으면 괄호 부분을 지운 키('권면(전자등록)총액' → 권면총액)로 찾습니다.
    """
    norm = normalize_label(label)
    kept = re.sub(r"[^\w%]", "", norm)
    removed = re.sub(r"[^\w%]", "", re.sub(r"\([^)]*\)", "", norm))
    return _best(kept) or _best(removed)
