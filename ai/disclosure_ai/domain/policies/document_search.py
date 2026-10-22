import re


def search_documents(documents: list[dict], query: str, limit=8) -> list[dict]:
    terms = set(re.findall(r"[가-힣A-Za-z0-9]+", query.lower()))
    rows = []
    for doc in documents:
        seen = set()
        for index, paragraph in enumerate(doc["text"].splitlines()):
            normalized = " ".join(paragraph.split())
            # 반복되는 회사명과 표 머리글이 검색 문맥을 채우지 않도록 첫 원문 위치만 유지합니다.
            if normalized in seen:
                continue
            seen.add(normalized)
            score = sum(t in paragraph.lower() for t in terms)
            if score:
                rows.append(
                    (
                        score,
                        {
                            "document_id": doc["document_id"],
                            "location": f"line:{index + 1}",
                            "quote": paragraph[:1200],
                            "url": doc.get("url"),
                        },
                    )
                )
    return [row for _, row in sorted(rows, key=lambda pair: -pair[0])[:limit]]
