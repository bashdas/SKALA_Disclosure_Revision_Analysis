from datetime import date

from disclosure_ai.infrastructure.documents.parser import normalize_disclosure, normalize_evidence
from disclosure_ai.infrastructure.mcp.client import (
    mcp_call,
)


class ExternalMcpAdapter:
    async def call(self, name: str, args: dict) -> dict:
        if name == "disclosure_get_document":
            result = await mcp_call(
                "EXTERNAL", "get_disclosure", {"receipt_no": args["receipt_no"]}
            )
            if result.get("error"):
                return result
            return normalize_disclosure(result, args["receipt_no"])

        if name in {"financial", "academic"}:
            try:
                cutoff = date.fromisoformat(args["as_of"])
                if name == "financial":
                    from disclosure_ai.infrastructure.mcp.schemas import FinancialQuery

                    request = FinancialQuery.model_validate(
                        {k: args[k] for k in FinancialQuery.model_fields}
                    ).model_dump()
                    tool = "get_financial_statements"
                else:
                    query = args["query"]
                    if not isinstance(query, str) or not query.strip() or len(query) > 500:
                        raise ValueError()
                    # 날짜 단위 공개 시점을 알 수 없어 기준 연도 이전의 검색 결과만 요청합니다.
                    request = {"query": query, "limit": 5, "year_to": cutoff.year - 1}
                    tool = "search_academic_papers"
            except (ValueError, TypeError, KeyError):
                return {"error": "INVALID_TOOL_INPUT"}
            result = await mcp_call("EXTERNAL", tool, request)
            return result if result.get("error") else normalize_evidence(result, name, args)

        return {"error": "TOOL_NOT_AVAILABLE", "tool": name}
