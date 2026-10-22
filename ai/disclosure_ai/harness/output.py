import re

from disclosure_ai.errors import LimitReached
from disclosure_ai.schemas import OutputReview
from disclosure_ai.services.business import RunCancelled


def mask(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[인증정보]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[이메일]", text)
    return re.sub(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[전화번호]", text)


def sentences(text):
    # 항목 번호와 날짜의 마침표는 문장 경계로 나누지 않습니다.
    return re.split(r"(?<=[!?。])\s+|(?<=[가-힣A-Za-z]\.)\s+|\n", text)


def safe_text(text: str) -> str:
    # 분석 의미의 적절성은 검사 모델이 판단하며 인증 정보만 마스킹합니다.
    return mask(text).replace("·", ", ").replace("—", ", ").replace("–", ", ").replace("―", ", ").strip()


async def review_output(
    harness, payload: dict, *, grounding=False, corrections=(), advisory=False
) -> tuple[dict, list[str]]:
    # 식별 정보와 대조된 원문 인용은 서술 판별 대상에서 분리합니다.
    fixed = {
        "request",
        "analysis_type",
        "disclosure_type",
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
        "question",
        "calculation_basis",
    }
    candidates = []
    contexts = []
    identities = []

    def identity(text, key, evidence):
        return (
            text,
            "selection"
            if key in {"selection_reason", "no_additional_analysis_reason"}
            else "scenario"
            if key == "scenario"
            else "analysis",
            tuple((s.get("document_id"), s.get("quote")) for s in evidence) if grounding else (),
        )

    filtered = False

    def collect(value, key="", evidence=()):
        nonlocal filtered
        if key in fixed:
            return
        if isinstance(value, str):
            for sentence in [value] if key == "scenario" else sentences(value):
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
    # 같은 출처를 문장마다 반복하면 검사 예산이 소진되므로 원문은 한 번만 보냅니다.
    pool, reference_ids = {}, {}
    changes = {(c["source"]["document_id"], c["source"]["location"]): c for c in corrections}
    for context in contexts:
        refs = []
        for source in context.pop("evidence"):
            token = (source.get("document_id"), source.get("quote"))
            if token not in reference_ids:
                reference_ids[token] = "E" + str(len(pool) + 1)
                pool[reference_ids[token]] = {
                    **source,
                    "quote": " ".join(source.get("quote", "").split()),
                }
            change = changes.get((source.get("document_id"), source.get("location")))
            if change:
                pool[reference_ids[token]]["correction"] = {
                    key: " ".join(change[key].split()) for key in ("label", "before", "after")
                }
            refs.append(reference_ids[token])
        context["evidence_ids"] = refs
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
                    "advisory": advisory,
                    "evidence": pool if grounding else {},
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
                "출력 검사 가이드를 완료하지 못했습니다. 분석 내용의 추가 확인이 필요합니다."
                if advisory else
                "출력 검사를 완료하지 못해 자유 서술을 제외하고 원문 근거와 처리 상태를 보존했습니다."
            )
    if filtered or len(accepted) < len(candidates):
        warnings.append(
            "출력 검사 가이드에서 추가 검토가 필요한 문장을 확인했습니다."
            if advisory else "근거 또는 출력 안전성을 확인하지 못한 문장은 작성하지 않았습니다."
        )
    if advisory:
        accepted = set(identities)

    def apply(value, key="", evidence=()):
        if key in fixed:
            return value
        if isinstance(value, str):
            return "\n".join(
                checked
                for sentence in ([value] if key == "scenario" else sentences(value))
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
