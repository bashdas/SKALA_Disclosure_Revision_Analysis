import re

from disclosure_ai.business import RunCancelled
from disclosure_ai.errors import LimitReached
from disclosure_ai.schemas import OutputReview


def mask(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[인증정보]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[이메일]", text)
    return re.sub(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[전화번호]", text)


def safe_text(text: str) -> str:
    # 투자 행동이나 가격 목표를 포함한 문장은 불명확한 경우까지 제외합니다.
    parts = re.split(r"(?<=[.!?。])\s+|\n", mask(text))
    risk = re.compile(
        r"(?:검증|검사|시스템|관리자|개발자).{0,20}(?:지시|명령)|매수|매도|보유|추천|목표\s*주가|매매|매집|포트폴리오|주식.{0,20}(사세요|사두|담아|구매)|비중.{0,10}(늘|줄)|투자\s*비중|수익.{0,10}보장|buy|sell|hold|target\s*price|should\s+invest",
        re.I,
    )
    return "\n".join(s for s in parts if not risk.search(s)).strip()


async def review_output(harness, payload: dict) -> tuple[dict, list[str]]:
    # 식별 정보와 대조된 원문 인용은 서술 판별 대상에서 분리합니다.
    fixed = {
        "request",
        "document_id",
        "location",
        "url",
        "published_at",
        "quote",
        "claim_id",
        "impact_type",
        "perspective_type",
        "status",
    }
    candidates = []
    filtered = False

    def collect(value, key=""):
        nonlocal filtered
        if key in fixed:
            return
        if isinstance(value, str):
            for sentence in re.split(r"(?<=[.!?。])\s+|\n", value):
                if not sentence.strip():
                    continue
                checked = safe_text(sentence)
                filtered |= checked != sentence.strip()
                if checked and checked not in candidates:
                    candidates.append(checked)
        elif isinstance(value, list):
            for item in value:
                collect(item, key)
        elif isinstance(value, dict):
            for name, item in value.items():
                collect(item, name)

    collect(payload)
    accepted = set()
    warnings = []
    if candidates:
        try:
            if len(candidates) > 128:
                raise LimitReached("출력 검사 문장 수를 초과했습니다.")
            review = await harness.model(
                "output_check",
                {"sentences": [{"index": i, "text": text} for i, text in enumerate(candidates)]},
                OutputReview,
                report=True,
            )
            indices = review.safe_indices
            if len(indices) != len(set(indices)) or any(
                i < 0 or i >= len(candidates) for i in indices
            ):
                raise ValueError("INVALID_REVIEW_INDICES")
            accepted = {candidates[i] for i in indices}
        except RunCancelled:
            raise
        except Exception as error:
            harness.ledger.event(harness.task_id, "OUTPUT_CHECK_FAILED", error=type(error).__name__)
            warnings.append(
                "출력 검사를 완료하지 못해 자유 서술을 제외하고 원문 근거와 처리 상태를 보존했습니다."
            )
    if filtered or len(accepted) < len(candidates):
        warnings.append("투자 권유 여부를 확정하지 못했거나 제한된 문장은 보고서에서 제외했습니다.")

    def apply(value, key=""):
        if key in fixed:
            return value
        if isinstance(value, str):
            return "\n".join(
                checked
                for sentence in re.split(r"(?<=[.!?。])\s+|\n", value)
                if (checked := safe_text(sentence)) and checked in accepted
            )
        if isinstance(value, list):
            return [apply(item, key) for item in value]
        if isinstance(value, dict):
            return {name: apply(item, name) for name, item in value.items()}
        return value

    harness.ledger.event(
        harness.task_id, "OUTPUT_CHECK_END", candidates=len(candidates), accepted=len(accepted)
    )
    return apply(payload), warnings
