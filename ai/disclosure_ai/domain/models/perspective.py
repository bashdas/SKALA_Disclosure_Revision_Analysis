from dataclasses import dataclass
from typing import TypedDict

from disclosure_ai.domain.models.evidence import Evidence


@dataclass(frozen=True)
class PerspectiveDefinition:
    key: str
    title: str
    academic_query: str
    allowed_tools: frozenset[str] = frozenset({"local_search", "financial", "academic"})


class PerspectiveCandidate(TypedDict):
    status: str
    findings: str
    sources: list[Evidence]
    requests: list[dict]
    limitations: list[str]


class PerspectiveAnalysis(PerspectiveCandidate, total=False):
    perspective_type: str
    selection_reason: str
    question: str
