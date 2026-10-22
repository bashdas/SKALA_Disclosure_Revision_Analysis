from disclosure_ai.domain.models.analysis import BaseAnalysisResult
from disclosure_ai.domain.models.perspective import PerspectiveCandidate


def analysis_context(filing, fragments):
    """모델에는 정정 전후를 구분해 전달하고 검증용 원문은 그대로 보존합니다."""
    changes = {(c["document_id"], c["location"]): c for c in filing.get("changes", [])}
    result = []
    for source in fragments:
        change = changes.get((source["document_id"], source["location"]))
        if change:
            result.append(
                {
                    "document_id": source["document_id"],
                    "location": source["location"],
                    **{key: " ".join(change[key].split()) for key in ("label", "before", "after")},
                }
            )
        else:
            result.append({**source, "quote": " ".join(source["quote"].split())})
    return result


def base_result(output) -> BaseAnalysisResult:
    """Copy provider output before domain validation mutates proposal candidates."""
    return output.model_dump()


def perspective_result(output) -> PerspectiveCandidate:
    """A candidate result; service must validate evidence before publishing it."""
    return output.model_dump()
