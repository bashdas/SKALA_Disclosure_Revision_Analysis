from disclosure_ai.infrastructure.mcp.client import mcp_call


class RagMcpAdapter:
    async def call(self, name: str, args: dict) -> dict:
        if name in {"ensure_analysis_index", "search_evidence"}:
            result = await mcp_call("RAG", name, args)
            if name != "search_evidence" or result.get("error"):
                return result
            try:
                documents, sources = [], []
                for row in result["results"]:
                    source = row["source"]
                    text = row["text"]
                    if not isinstance(text, str) or not text:
                        raise ValueError()
                    doc_id = f"rag:{source['document_id']}:chunk:{source['chunk_index']}"
                    location = ":".join(
                        str(source[k])
                        for k in ("file", "table_id", "row_start", "row_end", "chunk_index")
                        if source.get(k) is not None
                    )
                    document = {
                        "document_id": doc_id,
                        "text": text,
                        "url": source.get("original_location"),
                        "published_at": source.get("published_at"),
                    }
                    documents.append(document)
                    sources.append(
                        {
                            "document_id": doc_id,
                            "location": location,
                            "quote": text,
                            "url": document["url"],
                            "published_at": document["published_at"],
                        }
                    )
                return {"documents": documents, "sources": sources}
            except (KeyError, TypeError, ValueError):
                return {"error": "INVALID_EVIDENCE_RESPONSE"}

        return {"error": "TOOL_NOT_AVAILABLE", "tool": name}
