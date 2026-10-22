import re


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
