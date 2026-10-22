import re


def validated_sources(sources: list[dict], documents: list[dict], fragments=()) -> list[dict]:
    known = {d["document_id"]: d for d in documents}
    accepted = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("quote"), str):
            continue
        doc = known.get(source.get("document_id"))
        quote = source["quote"]
        if not quote:
            located = [
                f
                for f in fragments
                if f.get("document_id") == source.get("document_id")
                and f.get("location") == source.get("location")
                and f.get("quote")
            ]
            if len({f["quote"] for f in located}) != 1:
                continue
            quote = located[0]["quote"]
        normalized = re.sub(r"\s+", "", quote)
        matches = [
            f
            for f in fragments
            if f.get("document_id") == source.get("document_id")
            and normalized
            and normalized in re.sub(r"\s+", "", f.get("quote", ""))
        ]
        # 줄바꿈만 바뀐 인용은 검증된 원문 조각으로 복원하고 원문 위치를 유지합니다.
        fragment = next((f for f in matches if f.get("location") == source.get("location")), None)
        if fragment is None:
            fragment = next(
                (f for f in matches if f.get("quote") == quote),
                matches[0] if len(matches) == 1 else None,
            )
        if fragment:
            quote = fragment["quote"]
        if doc and quote and (quote in doc["text"] or fragment):
            location = (
                fragment["location"]
                if fragment
                else f"line:{doc['text'][: doc['text'].index(quote)].count(chr(10)) + 1}"
            )
            accepted.append(
                {
                    "document_id": source["document_id"],
                    "quote": quote,
                    "location": location,
                    "url": doc.get("url"),
                    "published_at": doc.get("published_at"),
                }
            )
    return list({(s["document_id"], s["location"], s["quote"]): s for s in accepted}.values())
