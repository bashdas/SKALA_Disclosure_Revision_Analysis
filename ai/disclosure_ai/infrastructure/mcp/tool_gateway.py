from disclosure_ai.infrastructure.mcp.business_mcp_adapter import BusinessMcpAdapter
from disclosure_ai.infrastructure.mcp.external_mcp_adapter import ExternalMcpAdapter
from disclosure_ai.infrastructure.mcp.rag_mcp_adapter import RagMcpAdapter
from disclosure_ai.ports.disclosure_gateway import DisclosureGateway
from disclosure_ai.ports.evidence_gateway import EvidenceGateway


class Tools(BusinessMcpAdapter):
    """Compatibility tool dispatch; concrete service boundaries live in the adapters."""

    def __init__(
        self,
        authorization: str,
        *,
        external: DisclosureGateway | None = None,
        rag: EvidenceGateway | None = None,
    ):
        super().__init__(authorization)
        self.external = external if external is not None else ExternalMcpAdapter()
        self.rag = rag if rag is not None else RagMcpAdapter()

    async def call(self, name: str, args: dict) -> dict:
        if name in {"disclosure_get_document", "financial", "academic"}:
            return await self.external.call(name, args)
        if name in {"ensure_analysis_index", "search_evidence"}:
            return await self.rag.call(name, args)
        return await super().call(name, args)
