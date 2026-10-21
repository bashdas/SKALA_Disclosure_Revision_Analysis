"""Bounded, deterministic ZIP/XML/HTML parsing without filesystem extraction."""
from hashlib import sha256
from html.entities import name2codepoint
from io import BytesIO
import re
import zipfile
import zlib

from lxml import etree

from app.errors import OpenDartError

HEADINGS = {"title", "subtitle", "document-name", "h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = HEADINGS | {"p", "li", "table", "section", "section-1", "section-2", "section-3"}


def tag(node):
    return node.tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower() if isinstance(node.tag, str) else ""


def normalized(value):
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[^\S\n]+", " ", value)).strip()


def text_of(node):
    parts = []
    def visit(item):
        if tag(item) in ("script", "style", "head") or not isinstance(item.tag, str):
            return
        if item.text:
            parts.append(item.text)
        for child in item:
            if tag(child) == "br":
                parts.append("\n")
            else:
                visit(child)
                if tag(child) in {"p", "div", "li", "tr"}:
                    parts.append("\n")
            if child.tail:
                parts.append(child.tail)
    visit(node)
    return normalized("".join(parts))


class OpenDartDocumentParser:
    MAX_UNCOMPRESSED = 64 * 1024 * 1024
    MAX_MEMBER = 32 * 1024 * 1024

    def parse(self, raw: bytes) -> dict:
        try:
            return self._parse(raw)
        except (zipfile.BadZipFile, zlib.error, RuntimeError, OSError, ValueError, LookupError, etree.LxmlError, RecursionError):
            raise OpenDartError("DISCLOSURE_PARSE_FAILED") from None

    def _parse(self, raw):
        blocks, tables, files = [], [], []
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 1000 or sum(item.file_size for item in members) > self.MAX_UNCOMPRESSED:
                raise ValueError("Archive limits")
            for member in members:
                if member.is_dir() or not member.filename.lower().endswith((".xml", ".html", ".htm")):
                    continue
                if member.file_size > self.MAX_MEMBER or member.flag_bits & 1:
                    raise ValueError("Member limits")
                with archive.open(member) as stream:
                    data = stream.read(self.MAX_MEMBER + 1)
                if len(data) > self.MAX_MEMBER:
                    raise ValueError("Member limits")
                root, content_type = self._root(data, member.filename)
                files.append({"filename": member.filename, "content_type": content_type})
                self._walk(root, member.filename, blocks, tables)
        text = "\n\n".join(block["text"] for block in blocks if block.get("text"))
        if not files or not text.strip():
            raise ValueError("No extractable document")
        return {"document_id": None, "content_type": "text/plain", "text": text,
                "tables": tables, "blocks": blocks, "files": files, "content_hash": sha256(raw).hexdigest()}

    def _root(self, data, filename):
        match = re.search(br'(?:encoding\s*=\s*["\']|charset\s*=\s*["\']?)([A-Za-z0-9_-]+)', data[:2048], re.I)
        encoding = match.group(1).decode("ascii") if match else "utf-8-sig"
        # No lossy replacement/guessing. Honor explicit XML/HTML encodings.
        try:
            source = data.decode(encoding)
        except UnicodeDecodeError:
            # 일부 DART 문서는 EUC-KR 선언에 UTF-8 본문을 제공하므로 손실 없는 UTF-8만 재확인합니다.
            if encoding.lower().replace("_", "-") not in {"euc-kr", "euckr"}:
                raise
            source = data.decode("utf-8-sig")
        if re.search(r"<!ENTITY\b", source, re.I):
            raise ValueError("Entity declarations prohibited")
        source = re.sub(r'^\s*<\?xml[^?]*\?>', '', source, count=1, flags=re.I)
        is_html = filename.lower().endswith((".html", ".htm")) or bool(re.match(r"\s*(?:<!DOCTYPE\s+html[^>]*>\s*)?<html\b", source, re.I))
        if is_html:
            if not re.search(r"<(?:html|body|table)\b", source, re.I):
                raise ValueError("Not HTML")
            parser = etree.HTMLParser(encoding="utf-8", no_network=True)
        else:
            # DART XML may contain HTML named whitespace/entities. Convert only known
            # non-XML names to numeric references, never expand arbitrary DTD entities.
            source = re.sub(r'&([A-Za-z][A-Za-z0-9]+);', lambda m: f'&#{name2codepoint[m[1]]};' if m[1] in name2codepoint and m[1] not in {"amp", "lt", "gt", "quot", "apos"} else m[0], source)
            # 일부 DART 표의 한글 꺾쇠 문구를 본문으로 보존합니다. XML 복구 모드는 사용하지 않습니다.
            source = re.sub(r"<([가-힣][^<>]*[ \t][^<>]*)>", r"&lt;\1&gt;", source)
            parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, recover=False)
        root = etree.fromstring(source.encode("utf-8"), parser=parser)
        if root is not None and any(isinstance(item, etree._Entity) for item in root.iter()):
            raise ValueError("Unresolved entity")
        if root is None:
            raise ValueError("Missing root")
        # SEC의 숨겨진 iXBRL 메타데이터를 본문과 재무 표에서 제외합니다.
        for item in list(root.iter()):
            if item.tag == "ix:header" and item.getparent() is not None:
                item.getparent().remove(item)
        return root, "text/html" if is_html else "application/xml"

    def _walk(self, node, filename, blocks, tables):
        name = tag(node)
        if name in ("script", "style", "head") or not name:
            return
        if name == "table":
            rows = []
            for row in node.iter():
                if tag(row) != "tr" or next((parent for parent in row.iterancestors() if tag(parent) == "table"), None) is not node:
                    continue
                cells = []
                for cell in row:
                    if tag(cell) not in ("td", "th"):
                        continue
                    attrs = {key.lower(): value for key, value in cell.attrib.items()}
                    cells.append({"text": text_of(cell), "header": tag(cell) == "th",
                        "rowspan": max(1, int(attrs.get("rowspan", "1"))),
                        "colspan": max(1, int(attrs.get("colspan", "1")))})
                rows.append({"cells": cells})
            table_id = f"table-{len(tables) + 1}"
            tables.append({"table_id": table_id, "file": filename, "rows": rows})
            value = "\n".join("\t".join(cell["text"] for cell in row["cells"]) for row in rows)
            blocks.append({"type": "table", "table_id": table_id, "file": filename, "text": value})
            return
        if name.startswith("section"):
            blocks.append({"type": "section", "tag": name, "file": filename})
        has_nested_block = any(tag(child) in BLOCK_TAGS for child in node.iterdescendants())
        if name in HEADINGS or not has_nested_block:
            value = text_of(node)
            if value:
                blocks.append({"type": "heading" if name in HEADINGS else "paragraph", "file": filename, "text": value})
            return
        if node.text and node.text.strip():
            blocks.append({"type": "paragraph", "file": filename, "text": normalized(node.text)})
        for child in node:
            self._walk(child, filename, blocks, tables)
            if child.tail and child.tail.strip():
                blocks.append({"type": "paragraph", "file": filename, "text": normalized(child.tail)})
