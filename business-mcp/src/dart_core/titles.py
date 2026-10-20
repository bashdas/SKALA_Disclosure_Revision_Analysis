"""report_nm 태그 파싱, base_report_nm 정규화, rm 해석 (docs/07 §5-1)."""

import re
from datetime import datetime

from dart_core.models import FilingMeta

TAG_RE = re.compile(r"^\s*\[([^\]]+)\]")
DOTS = str.maketrans({"·": "ㆍ", "•": "ㆍ", "・": "ㆍ", "‧": "ㆍ"})
KIND = {
    "기재정정": "content",
    "첨부정정": "attachment",
    "첨부추가": "attachment",
    "발행조건확정": "terms_fixed",
    "변경등록": "other",
    "연장결정": "other",
}
KIND_PRIORITY = ["content", "terms_fixed", "attachment", "other"]
# 정정명령부과/정정제출요구는 원본 공시에 붙는 표시라 정정 공시로 보지 않음


def split_tags(report_nm: str) -> tuple[list[str], str]:
    tags, rest = [], report_nm
    while m := TAG_RE.match(rest):
        tags.append(m.group(1).strip())
        rest = rest[m.end() :]
    base = re.sub(r"\s+", " ", rest.translate(DOTS)).strip()
    return tags, base


def compare_key(base: str) -> str:
    return re.sub(r"\s+", "", base.translate(DOTS))


def correction_kind(tags: list[str]) -> str | None:
    kinds = {KIND[t] for t in tags if t in KIND}
    return next((k for k in KIND_PRIORITY if k in kinds), None)


def to_filing_meta(row: dict) -> FilingMeta:
    """list.json의 list[] 1행(OpenDART 원본 필드) → FilingMeta."""
    tags, base = split_tags(row["report_nm"])
    kind = correction_kind(tags)
    rm = row.get("rm") or None
    return FilingMeta(
        rcept_no=row["rcept_no"],
        corp_code=row["corp_code"],
        corp_name=row["corp_name"],
        stock_code=(row.get("stock_code") or "").strip() or None,
        corp_cls=row.get("corp_cls") or None,
        report_nm=row["report_nm"],
        base_report_nm=base,
        correction_tags=tags,
        is_correction=kind is not None,
        correction_kind=kind,
        has_later_correction="정" in (rm or ""),
        is_withdrawn="철" in (rm or ""),
        rcept_dt=datetime.strptime(row["rcept_dt"], "%Y%m%d").date(),
        flr_nm=row.get("flr_nm") or None,
        rm=rm,
        pblntf_ty=row.get("pblntf_ty") or None,
    )
