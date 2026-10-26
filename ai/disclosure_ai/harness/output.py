import json
import re

from disclosure_ai.schemas import OutputReview
from disclosure_ai.services.business import RunCancelled


def mask(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[인증정보]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[이메일]", text)
    return re.sub(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[전화번호]", text)


def masked_json(value) -> str:
    # Mask text before serialization so patterns cannot consume JSON escape sequences
    # or mistake a numeric value for a phone number. Leave the caller's input intact.
    def visit(item):
        if isinstance(item, str):
            return mask(item)
        if isinstance(item, dict):
            return {mask(key) if isinstance(key, str) else key: visit(child)
                    for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [visit(child) for child in item]
        return item

    return json.dumps(visit(value), ensure_ascii=False)


def sentences(text):
    # 항목 번호와 날짜의 마침표는 문장 경계로 나누지 않습니다.
    return re.split(r"(?<=[!?。])\s+|(?<=[가-힣A-Za-z]\.)\s+|\n", text)


def safe_text(text: str) -> str:
    # 분석 의미의 적절성은 검사 모델이 판단하며 인증 정보만 마스킹합니다.
    return (
        mask(text)
        .replace("·", ", ")
        .replace("—", ", ")
        .replace("–", ", ")
        .replace("―", ", ")
        .strip()
    )


async def review_output(
    harness, payload: dict, *, grounding=False, corrections=(), advisory=False,
    current_document_ids=(),
) -> tuple[dict, list[str]]:
    # 식별 정보와 대조된 원문 인용은 서술 판별 대상에서 분리합니다.
    fixed = {
        "request",
        "analysis_type",
        "market_as_of",
        "news_retrieval",
        "news_queries",
        "news_snapshots",
        "disclosure_type",
        "document_id",
        "report_document_id",
        "report_location",
        "memo_id",
        "base_memo_version",
        "research_reports",
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
        "receipt_no",
        "subject",
        "view_type",
    }
    candidates = []
    contexts = []
    identities = []
    units = {}

    def identity(text, key, evidence, strict=False, condition=None):
        kind = (
            "review_" + key if strict else
            "selection" if key in {"selection_reason", "no_additional_analysis_reason"} else
            "scenario" if key == "scenario" else "analysis"
        )
        return (
            text, kind,
            tuple((s.get("document_id"), s.get("quote")) for s in evidence) if grounding else (),
            condition if strict else None,
        )

    filtered = False
    disclosure_review = any(
        point.get("view_type") == "DISCLOSURE_REVIEW"
        for point in payload.get("base", {}).get("review_points", [])
    )

    def collect(value, key="", evidence=(), strict=False, condition=None, unit=None):
        nonlocal filtered
        strict = strict or (disclosure_review and key in {"summary_claims", "results"})
        if key in fixed and not (strict and key == "question"):
            return
        if isinstance(value, str):
            for sentence in [value] if key == "scenario" else sentences(value):
                if not sentence.strip():
                    continue
                checked = safe_text(sentence)
                filtered |= checked != sentence.strip()
                token = identity(checked, key, evidence, strict, condition)
                if checked and token not in identities:
                    identities.append(token)
                    candidates.append(checked)
                    contexts.append({"evidence": list(evidence), "kind": token[1],
                                     **({"view_type": "DISCLOSURE_REVIEW",
                                         "condition": condition} if strict else {})})
                if checked:
                    index = identities.index(token)
                    units.setdefault(unit or (4, index), set()).add(index)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                item_unit = (0, i) if key == "summary_claims" else unit
                collect(item, key, evidence, strict, condition, item_unit)
        elif isinstance(value, dict):
            evidence = value.get("evidence", value.get("sources", evidence))
            strict = strict or value.get("view_type") == "DISCLOSURE_REVIEW"
            condition = value.get("condition", condition)
            if value.get("view_type") == "DISCLOSURE_REVIEW":
                unit = (1, len(units))
            elif "past_fact" in value and "current_fact" in value:
                unit = (2, len(units))
            elif key == "results":
                # 한 담당의 문장 일부만 남겨 조건과 결론이 분리되지 않게 합니다.
                for i, (name, item) in enumerate(value.items()):
                    collect(item, name, evidence, strict, condition, (3, i))
                return
            for name, item in value.items():
                collect(item, name, evidence, strict, condition, unit)

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
                    "current_disclosure": source.get("document_id") in current_document_ids,
                }
            change = changes.get((source.get("document_id"), source.get("location")))
            if change:
                pool[reference_ids[token]]["correction"] = {
                    key: " ".join(change[key].split()) for key in ("label", "before", "after")
                }
            refs.append(reference_ids[token])
        context["evidence_ids"] = refs
    def check_context(indices):
        refs = {ref for i in indices for ref in contexts[i]["evidence_ids"]}
        return {
            "require_grounding": grounding,
            "advisory": advisory,
            "evidence": {ref: source for ref, source in pool.items() if ref in refs} if grounding else {},
            "sentences": [
                {"index": i, "text": candidates[i], **(contexts[i] if grounding else {})}
                for i in sorted(indices)
            ],
        }

    # 한 번의 기존 검사 호출 안에서 완전한 항목만 검증합니다. 원문을 자르지 않습니다.
    indices = set(range(len(candidates)))
    fits = getattr(harness, "fits_model_input", None)
    omitted = set()
    if len(indices) > 128 or (fits and not fits("output_check", check_context(indices), OutputReview)):
        indices = set()
        for _, group in sorted(units.items()):
            proposed = indices | group
            if len(proposed) <= 128 and (
                not fits or fits("output_check", check_context(proposed), OutputReview)
            ):
                indices = proposed
        omitted = set(range(len(candidates))) - indices
    accepted = set()
    warnings = []
    if omitted:
        warnings.append(
            "OUTPUT_CHECK_PARTIAL: 출력 검사 입력 한도에 맞춰 요약과 핵심 관점을 우선 검증했습니다. 한도 밖의 미검증 새 관점과 해석은 제외했습니다."
        )
    if indices:
        try:
            review = await harness.model(
                "output_check",
                check_context(indices),
                OutputReview,
                report=True,
            )
            reviewed = review.safe_indices
            if len(reviewed) != len(set(reviewed)) or not set(reviewed) <= indices:
                raise ValueError("INVALID_REVIEW_INDICES")
            accepted = {identities[i] for i in reviewed}
        except RunCancelled:
            raise
        except Exception as error:
            harness.ledger.event(harness.task_id, "OUTPUT_CHECK_FAILED", error=type(error).__name__)
            warnings.append(
                "OUTPUT_CHECK_FAILED: 출력 검사 가이드를 완료하지 못했습니다. 분석 내용의 추가 확인이 필요합니다."
                if advisory
                else "출력 검사를 완료하지 못해 자유 서술을 제외하고 원문 근거와 처리 상태를 보존했습니다."
            )
    if filtered or len(accepted) < len(candidates):
        warnings.append(
            "출력 검사 가이드에서 추가 검토가 필요한 문장을 확인했습니다."
            if advisory
            else "근거 또는 출력 안전성을 확인하지 못한 문장은 작성하지 않았습니다."
        )
    grounded = accepted.copy()
    if advisory:
        accepted = set(identities)

    def apply(value, key="", evidence=(), strict=False, condition=None):
        strict = strict or (disclosure_review and key in {"summary_claims", "results"})
        if key in fixed and not (strict and key == "question"):
            return value
        if isinstance(value, str):
            # 새 과거 비교 항목의 사실·해석은 기존 분석의 advisory 모드와 별개로 검사합니다.
            allowed = grounded if strict or key in {"past_fact", "current_fact", "interpretation"} else accepted
            return "\n".join(
                checked
                for sentence in ([value] if key == "scenario" else sentences(value))
                if (checked := safe_text(sentence)) and identity(checked, key, evidence, strict, condition) in allowed
            )
        if isinstance(value, list):
            return [result for item in value if (result := apply(item, key, evidence, strict, condition)) is not None]
        if isinstance(value, dict):
            evidence = value.get("evidence", value.get("sources", evidence))
            strict = strict or value.get("view_type") == "DISCLOSURE_REVIEW"
            condition = value.get("condition", condition)
            result = {name: apply(item, name, evidence, strict, condition) for name, item in value.items()}
            if value.get("view_type") == "DISCLOSURE_REVIEW":
                # 조건 일부를 삭제해 무조건적인 결론으로 바꾸지 않고 항목 전체를 제외합니다.
                fields = ("title", "disclosure_fact", "condition", "reason", "question", "check_items")
                def normalized(item):
                    if isinstance(item, list):
                        return [normalized(part) for part in item]
                    if isinstance(item, str):
                        return "\n".join(safe_text(s) for s in sentences(item) if s.strip())
                    return item
                if any(result.get(name) != normalized(value.get(name)) for name in fields):
                    warnings.append("DISCLOSURE_REVIEW_EXCLUDED: 출력 검사에서 새 검토 관점을 확인하지 못해 제외했습니다. 공시 사실과 처리 한계는 별도로 보존합니다.")
                    return None
            return result
        return value

    harness.ledger.event(
        harness.task_id, "OUTPUT_CHECK_END", candidates=len(candidates),
        checked=len(indices), grounded=len(grounded), accepted=len(accepted)
    )
    return apply(payload), warnings
