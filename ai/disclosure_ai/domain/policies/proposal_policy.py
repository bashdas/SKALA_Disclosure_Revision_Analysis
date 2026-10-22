from disclosure_ai.domain.policies.evidence_policy import validated_sources


def validate_proposals(proposals, memo_text, documents, fragments):
    limitations = []
    for proposal in proposals:
        proposal["evidence"] = validated_sources(proposal["evidence"], documents, fragments)
        if (
            not proposal["before_text"].strip()
            or proposal["before_text"] not in memo_text
            or not proposal["evidence"]
            or proposal["impact_type"] == "HOLD"
        ):
            proposal["impact_type"] = "HOLD"
            proposal["after_text"] = None
            proposal["before_text"] = ""
            proposal["reason"] = "메모 문장 또는 출처를 확인하지 못해 작성하지 않았습니다."
            proposal["evidence"] = []
            limitations.append("메모 문장 또는 출처를 확인하지 못한 제안은 보류했습니다.")
    return limitations
