from typing import TypedDict

from disclosure_ai.domain.enums import Impact
from disclosure_ai.domain.models.evidence import Evidence


class Proposal(TypedDict):
    claim_id: str
    impact_type: Impact
    before_text: str
    after_text: str | None
    reason: str
    evidence: list[Evidence]
