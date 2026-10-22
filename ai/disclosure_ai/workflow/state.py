from typing import Annotated, TypedDict

from disclosure_ai.domain.models.analysis import BaseAnalysisResult
from disclosure_ai.domain.models.evidence import Evidence
from disclosure_ai.domain.models.perspective import PerspectiveAnalysis
from disclosure_ai.domain.models.report import AnalysisReport
from disclosure_ai.workflow.reducers import merge_mapping, merge_warnings


class State(TypedDict, total=False):
    request: dict
    scope: str
    filing: dict
    memo: dict
    documents: list
    context: list[Evidence]
    base: BaseAnalysisResult
    results: Annotated[dict[str, PerspectiveAnalysis], merge_mapping]
    warnings: Annotated[list, merge_warnings]
    report: AnalysisReport
    output: dict
    selection: dict
    stage_failed: bool
    rag_ready: bool
    jobs: Annotated[dict, merge_mapping]
    lookups: list
    lookup_results: list


AnalysisState = State
