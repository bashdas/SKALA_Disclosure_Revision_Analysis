from dataclasses import dataclass, field

from app.errors import RagError


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


class Chunker:
    def __init__(self, size=1000, overlap=100):
        self.size, self.overlap = size, overlap
        self.fingerprint = f"paragraph-table-v1:{size}:{overlap}"

    def _text(self, text, metadata):
        text = text.strip()
        while text:
            end = min(len(text), self.size)
            if len(text) > self.size:
                boundary = text.rfind("\n", self.size // 2, self.size)
                if boundary > 0:
                    end = boundary
            yield Chunk(text[:end], dict(metadata))
            if end == len(text):
                break
            text = text[max(1, end - self.overlap):]

    def split(self, text, document=None):
        document = document or {}
        blocks = document.get("blocks") or [{"type": "paragraph", "text": text}]
        tables = {t["table_id"]: t for t in document.get("tables", [])}
        chunks, pending, heading = [], [], ""
        current_file = None

        def flush():
            if pending:
                chunks.extend(self._text("\n\n".join(pending), {"heading": heading, "file": current_file}))
                pending.clear()

        for block in blocks:
            if block.get("file") != current_file:
                flush()
                current_file = block.get("file")
            kind = block.get("type")
            if kind == "table":
                flush()
                table = tables.get(block.get("table_id"))
                if not table:
                    raise RagError("CHUNKING_FAILED", "Table structure is missing")
                rows = [" | ".join(c.get("text", "") for c in row["cells"]) for row in table["rows"]]
                header = rows[0] if rows and any(c.get("header") for c in table["rows"][0]["cells"]) else ""
                group, first = [], 0
                for index, row in enumerate(rows):
                    if len(row) + len(header) + 1 > 2000:
                        raise RagError("CHUNK_TOO_LARGE", "A table row exceeds the embedding input limit")
                    if group and len("\n".join(group + [row])) > self.size:
                        chunks.append(Chunk("\n".join(group), {"table_id": table["table_id"], "row_start": first, "row_end": index - 1, "heading": heading, "file": current_file}))
                        group, first = ([header] if header else []), index
                    group.append(row)
                if group:
                    chunks.append(Chunk("\n".join(group), {"table_id": table["table_id"], "row_start": first, "row_end": len(rows) - 1, "heading": heading, "file": current_file}))
            elif block.get("text", "").strip():
                if kind in ("heading", "section"):
                    flush()
                    heading = block["text"].strip()
                pending.append(block["text"].strip())
        flush()
        if not chunks:
            raise RagError("EMPTY_DOCUMENT", "Source document has no text")
        return chunks
