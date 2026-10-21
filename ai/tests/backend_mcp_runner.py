"""기존 백엔드 MCP를 실행하되 외부 API와 RAG 저장소 및 임베딩만 테스트 입력으로 대체합니다."""

import argparse
import io
import uuid
import zipfile

import httpx
import uvicorn
from app.main import create_app


def external_transport():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "filing.xml",
            "<root><title>정정공시</title><table><tr><th>항목</th><th>정정전</th><th>정정후</th></tr><tr><td>계약금액</td><td>100</td><td>80</td></tr></table></root>",
        )

    def handler(request):
        if request.url.path.endswith("document.xml"):
            return httpx.Response(200, content=buffer.getvalue())
        return httpx.Response(
            200,
            json={
                "status": "000",
                "total_page": 1,
                "list": [
                    {
                        "rcept_no": "20261020000123",
                        "corp_code": "00126380",
                        "corp_name": "검증기업",
                        "report_nm": "정정공시",
                        "rcept_dt": "20261020",
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


class Embedding:
    async def embed(self, texts):
        return [[1.0] + [0.0] * 1535 for _ in texts]


class Store:
    def __init__(self):
        self.documents, self.manifests = [], {}

    def find_document(self, identity):
        return next((d for d in self.documents if d["identity"] == identity), None)

    def save_document(self, identity, source, chunks, vectors):
        document = {
            "id": uuid.uuid4(),
            "identity": identity,
            "source": source,
            "chunks": len(chunks),
            "rows": chunks,
        }
        self.documents.append(document)
        return document

    def link(self, task_id, organization_id, memo_id, disclosure_id):
        self.manifests[task_id] = (organization_id, {memo_id, disclosure_id})

    def search(
        self,
        task_id,
        organization_id,
        memo_id,
        version,
        receipt_no,
        fingerprint,
        vector,
        types,
        top_k,
        minimum,
    ):
        manifest = self.manifests.get(task_id)
        if not manifest or manifest[0] != organization_id:
            return None
        rows = []
        for doc in self.documents:
            if doc["id"] not in manifest[1] or doc["identity"]["document_type"] not in types:
                continue
            for index, chunk in enumerate(doc["rows"]):
                rows.append(
                    {
                        "document_type": doc["identity"]["document_type"],
                        "text": chunk.text,
                        "score": 1.0,
                        "source": {
                            **doc["source"],
                            **chunk.metadata,
                            "document_id": str(doc["id"]),
                            "chunk_index": index,
                        },
                    }
                )
        return rows[:top_k]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=["business", "external", "rag"])
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    if args.service == "external":
        app = create_app(transport=external_transport())
    elif args.service == "rag":
        app = create_app(embedding=Embedding(), store=Store())
    else:
        app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="error")
