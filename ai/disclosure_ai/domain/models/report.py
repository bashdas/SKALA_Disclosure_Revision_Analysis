from typing import TypedDict


class AnalysisReport(TypedDict):
    content: str
    report_json: dict
    has_warnings: bool
    no_additional_analysis_reason: str | None
    generated_at: str
