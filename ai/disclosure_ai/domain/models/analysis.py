from typing import TypedDict

from disclosure_ai.domain.models.proposal import Proposal


class BaseAnalysisResult(TypedDict):
    summary: str
    proposals: list[Proposal]
    selected: list[dict]
    no_additional_analysis_reason: str | None
    limitations: list[str]
