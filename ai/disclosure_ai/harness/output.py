import re

from disclosure_ai.errors import LimitReached
from disclosure_ai.schemas import OutputReview
from disclosure_ai.services.business import RunCancelled


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


async def review_output(harness, payload: dict, *, grounding=False) -> tuple[dict, list[str]]:
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
        "evidence_ids",
        "before_text",
    }
    candidates = []
    contexts = []
    identities = []

    def identity(text, key, evidence):
        return (
            text,
            "selection"
            if key in {"selection_reason", "no_additional_analysis_reason"}
            else "analysis",
            tuple((s.get("document_id"), s.get("quote")) for s in evidence) if grounding else (),
        )

    filtered = False

    def collect(value, key="", evidence=()):
        nonlocal filtered
        if key in fixed:
            return
        if isinstance(value, str):
            for sentence in re.split(r"(?<=[.!?。])\s+|\n", value):
                if not sentence.strip():
                    continue
                checked = safe_text(sentence)
                filtered |= checked != sentence.strip()
                token = identity(checked, key, evidence)
                if checked and token not in identities:
                    identities.append(token)
                    candidates.append(checked)
                    contexts.append({"evidence": list(evidence), "kind": token[1]})
        elif isinstance(value, list):
            for item in value:
                collect(item, key, evidence)
        elif isinstance(value, dict):
            evidence = value.get("evidence", value.get("sources", evidence))
            for name, item in value.items():
                collect(item, name, evidence)

    collect(payload)
    accepted = set()
    warnings = []
    if candidates:
        try:
            if len(candidates) > 128:
                raise LimitReached("출력 검사 문장 수를 초과했습니다.")
            review = await harness.model(
                "output_check",
                {
                    "require_grounding": grounding,
                    "sentences": [
                        {"index": i, "text": text, **(contexts[i] if grounding else {})}
                        for i, text in enumerate(candidates)
                    ],
                },
                OutputReview,
                report=True,
            )
            indices = review.safe_indices
            if len(indices) != len(set(indices)) or any(
                i < 0 or i >= len(candidates) for i in indices
            ):
                raise ValueError("INVALID_REVIEW_INDICES")
            accepted = {identities[i] for i in indices}
        except RunCancelled:
            raise
        except Exception as error:
            harness.ledger.event(harness.task_id, "OUTPUT_CHECK_FAILED", error=type(error).__name__)
            warnings.append(
                "출력 검사를 완료하지 못해 자유 서술을 제외하고 원문 근거와 처리 상태를 보존했습니다."
            )
    if filtered or len(accepted) < len(candidates):
        warnings.append("근거 또는 출력 안전성을 확인하지 못한 문장은 작성하지 않았습니다.")

    def apply(value, key="", evidence=()):
        if key in fixed:
            return value
        if isinstance(value, str):
            return "\n".join(
                checked
                for sentence in re.split(r"(?<=[.!?。])\s+|\n", value)
                if (checked := safe_text(sentence)) and identity(checked, key, evidence) in accepted
            )
        if isinstance(value, list):
            return [apply(item, key, evidence) for item in value]
        if isinstance(value, dict):
            evidence = value.get("evidence", value.get("sources", evidence))
            return {name: apply(item, name, evidence) for name, item in value.items()}
        return value

    harness.ledger.event(
        harness.task_id, "OUTPUT_CHECK_END", candidates=len(candidates), accepted=len(accepted)
    )
    return apply(payload), warnings
