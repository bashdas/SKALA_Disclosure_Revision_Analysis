from pydantic import Field

from disclosure_ai.domain.models.base import Model


class ReportText(Model):
    summary: str
    correction: str
    memo_impact: str
    suggestions: str
    perspectives: str
    future_impacts: str = ""
    limitations: str


class SavedReport(Model):
    content: str = Field(min_length=1, max_length=100000)
    report_json: dict
    has_warnings: bool
    no_additional_analysis_reason: str | None
    generated_at: str
