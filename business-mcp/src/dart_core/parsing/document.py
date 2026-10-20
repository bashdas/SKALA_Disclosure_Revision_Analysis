"""원문 ZIP → ParsedDocument (섹션·표·본문, 결정적 ID).

지원 근거 (docs/spike_notes.md):
- dart4.xsd 계열 XML: 태그 이름(DOCUMENT, BODY, LIBRARY, CORRECTION, SECTION-n, TITLE, P, TABLE, THEAD/TBODY,
  TR, TD/TH/TE/TU, SPAN, A …)과 원문 결함(cp949인데 utf-8 선언, `&cr;`, 비이스케이프 `&`, 본문의 `<…>`)은
  공개 프로젝트의 원문 관찰 기록과 DART 뷰어 HTML(같은 태그 구조)로 확인했습니다. API ZIP 자체는 키가 없어 미관찰.
- HTML 계열(뷰어 dtd=HTML인 거래소 수시공시): 대소문자 구분 없이 같은 규칙으로 처리합니다.

ID 규칙(05 §3): ZIP 엔트리 이름순 파일순번 i, 문서 등장 순서 j(0부터)로 section_id=f{i}.s{j}, table_id=f{i}.t{j}.
"""

import html.entities
import io
import re
import zipfile
from dataclasses import dataclass, field

from lxml import etree
from lxml import html as lxml_html

from dart_core.models import Cell, ParsedDocument, Section, Table
from dart_core.status import DocumentParseError

PARSER_VERSION = "parser-0.1.1"  # 0.1.1: KIND(거래소) 링크를 DART 접수번호로 쓰지 않음
MARKUP_EXT = (".xml", ".htm", ".html")
MAX_ENTRIES = 100
MAX_ENTRY_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
LINE = " "  # 원문 줄바꿈(&cr;, BR, 블록 경계) 표식. 서식용 공백·개행과 구분하려고 씀

# 관찰된 dart4 태그 (spike_notes 출처 참고) + HTML 서식 태그 일부. 목록 밖의 `<`는 본문 텍스트로 봅니다.
KNOWN_TAGS = frozenset({
    "A", "APPENDIX", "B", "BODY", "BR", "CAPTION", "COL", "COLGROUP", "COMMENT", "COMPANY-NAME", "CORRECTION", "COVER",
    "COVER-TITLE", "DIV", "DOCUMENT", "DOCUMENT-HEADER", "DOCUMENT-NAME", "EXTRACTION", "FILENAME", "FONT",
    "FORMULA-VERSION", "HEAD", "HTML", "I", "IMAGE", "IMG", "IMG-CAPTION", "INSERTION", "LIBRARY", "LIBRARYLIST",
    "META", "P", "PGBRK", "SECTION-1", "SECTION-2", "SECTION-3", "SPAN", "STRONG", "STYLE", "SUMMARY", "TABLE",
    "TABLE-GROUP", "TBODY", "TD", "TE", "TFOOT", "TH", "THEAD", "TITLE", "TOC", "TR", "TU", "U", "WARNING",
})
SECTION_LEVEL = {"CORRECTION": 1, "SECTION-1": 1, "SECTION-2": 2, "SECTION-3": 3}
CELL_TAGS = {"TD", "TH", "TE", "TU"}
BLOCK_TAGS = {"P", "DIV", "TITLE", "BR", "PGBRK", "TR", "CAPTION", "DOCUMENT-NAME", "COMPANY-NAME", "COVER-TITLE"}
SKIP_TAGS = {"STYLE", "SCRIPT", "HEAD", "META", "COLGROUP", "COL", "IMG", "IMAGE", "FORMULA-VERSION"}
UNIT_RE = re.compile(r"단위\s*[:：]\s*([^)\]\n ]+)")
DART_LINK_RE = re.compile(r"(?:dart\.fss\.or\.kr|^/dsaf001)[^\s\"']*[?&]rcpNo=(\d{14})", re.IGNORECASE)
KIND_LINK_RE = re.compile(r"kind\.krx\.co\.kr[^\s\"']*[?&]acptno=(\d{14})", re.IGNORECASE)


def _link_ref(href: str) -> str | None:
    """DART 뷰어 링크 → 접수번호, 거래소(KIND) 뷰어 링크 → 'kind:<KIND 접수번호>'.

    실제 API 원문(수시공시)의 '※ 관련공시'는 KIND 링크이고 acptno는 DART 접수번호와 다릅니다(9번째 자리 차이 관찰,
    공식 대응 규칙이 없어 변환하지 않음).
    """
    if m := DART_LINK_RE.search(href):
        return m.group(1)
    if m := KIND_LINK_RE.search(href):
        return f"kind:{m.group(1)}"
    return None


# ── ZIP ──────────────────────────────────────────────────────────────────


def read_zip(data: bytes, *, max_entries: int = MAX_ENTRIES, max_entry_bytes: int = MAX_ENTRY_BYTES,
             max_total_bytes: int = MAX_TOTAL_BYTES) -> list[tuple[str, bytes]]:
    """ZIP의 파일 엔트리를 (파일명, 바이트)로 이름순 반환. 제한을 넘으면 일부만 읽지 않고 전체를 실패시킵니다.

    엔트리 경로(`/a/b.xml`, `..\\x`)는 파일명만 남기고, 같은 이름이 둘이면 실패합니다. 디스크에 풀지 않습니다.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as e:
        raise DocumentParseError(None, f"ZIP을 열 수 없습니다: {type(e).__name__}") from None
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if not infos:
            raise DocumentParseError(None, "ZIP에 파일이 없습니다.")
        if len(infos) > max_entries:
            raise DocumentParseError(None, f"ZIP 엔트리가 너무 많습니다 ({len(infos)} > {max_entries}).")
        if sum(i.file_size for i in infos) > max_total_bytes:
            raise DocumentParseError(None, "ZIP 해제 크기가 상한을 넘습니다.")
        out: dict[str, bytes] = {}
        total = 0
        for info in infos:
            name = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
            if not name or name in (".", "..") or "\x00" in name:
                raise DocumentParseError(None, "ZIP 엔트리 이름이 올바르지 않습니다.")
            if name in out:
                raise DocumentParseError(None, f"ZIP에 같은 파일명이 여러 번 있습니다: {name}")
            if info.flag_bits & 0x1:
                raise DocumentParseError(None, "암호화된 ZIP 엔트리는 지원하지 않습니다.")
            if info.file_size > max_entry_bytes:
                raise DocumentParseError(None, f"ZIP 엔트리가 너무 큽니다: {name}")
            try:
                with zf.open(info) as f:
                    body = f.read(max_entry_bytes + 1)  # 헤더의 크기 값이 거짓이어도 상한 이상은 읽지 않음
            except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as e:
                raise DocumentParseError(None, f"ZIP 엔트리를 읽을 수 없습니다: {name} ({type(e).__name__})") from None
            total += len(body)
            if len(body) > max_entry_bytes or total > max_total_bytes:
                raise DocumentParseError(None, "ZIP 해제 크기가 상한을 넘습니다.")
            out[name] = body
    return sorted(out.items())


# ── 인코딩·보정 ──────────────────────────────────────────────────────────


def decode_markup(raw: bytes) -> tuple[str, str]:
    """BOM → utf-8 → cp949 순서. 선언된 encoding은 믿지 않습니다(cp949인데 utf-8로 선언된 원문이 있음)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="strict"), "utf-8"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise DocumentParseError(None, "원문 인코딩을 판별할 수 없습니다 (utf-8, cp949 실패).")


_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
_DOCTYPE = re.compile(r"<!DOCTYPE[^>\[]*(\[[^\]]*\])?\s*>", re.IGNORECASE)
_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")
_TAG_START = re.compile(r"<(?!(?:/?(?:" + "|".join(sorted(map(re.escape, KNOWN_TAGS), key=len, reverse=True))
                        + r")(?=[\s>/]))|[!?])", re.IGNORECASE)
_UNKNOWN_NAME = re.compile(r"/?([A-Za-z][A-Za-z0-9_.-]*)")
_OPEN_TAG = re.compile(r"<([A-Za-z][A-Za-z0-9-]*)(\s[^<>]*?)?(/?)>")
_ATTR = re.compile(r"""([A-Za-z_][\w.:-]*)\s*=\s*("[^"]*"|'[^']*')""")
_ATTRS_OK = re.compile(r"""(?:\s+[A-Za-z_][\w.:-]*\s*=\s*(?:"[^"<]*"|'[^'<]*'))*\s*""")
XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


def repair_xml(text: str) -> tuple[str, list[str]]:
    """DART XML 원문 결함을 보정합니다. 각 규칙은 결정적이며, 보정 사실은 notes로 남깁니다."""
    notes: list[str] = []
    text = _XML_DECL.sub("", text, count=1)
    text, n = _DOCTYPE.subn("", text)
    if n:
        notes.append("DOCTYPE 제거(외부 DTD·엔티티 차단)")

    def entity(m: re.Match) -> str:
        name = m.group(1)
        if name.lower() == "cr":
            return "&#8232;"  # LINE
        if name in XML_ENTITIES:
            return m.group(0)
        cp = html.entities.name2codepoint.get(name)
        return f"&#{cp};" if cp else f"&amp;{name};"

    text = _ENTITY.sub(entity, text)
    text, n = _BARE_AMP.subn("&amp;", text)
    if n:
        notes.append(f"비이스케이프 & {n}건 보정")
    unknown: dict[str, list[int]] = {}

    def escape_lt(m: re.Match) -> str:
        if nm := _UNKNOWN_NAME.match(text, m.end()):
            pair = unknown.setdefault(nm.group(1).upper(), [0, 0])
            pair[1 if nm.group(0).startswith("/") else 0] += 1
        return "&lt;"

    text, n = _TAG_START.subn(escape_lt, text)
    if n:
        notes.append(f"본문의 '<' {n}건 텍스트로 보정")
    paired = sorted(k for k, (o, c) in unknown.items() if o and c)
    if paired:
        notes.append(f"알 수 없는 태그 쌍을 텍스트로 처리: {', '.join(paired[:5])}")

    def attrs(m: re.Match) -> str:
        a = m.group(2)
        if not a or _ATTRS_OK.fullmatch(a):
            return m.group(0)
        pairs: dict[str, str] = {}
        for k, v in _ATTR.findall(a):
            pairs.setdefault(k, v)
        return f"<{m.group(1)}{''.join(f' {k}={v}' for k, v in pairs.items())}{m.group(3)}>"

    text = _OPEN_TAG.sub(attrs, text)
    return text, notes


# ── 트리 → 섹션·표 ──────────────────────────────────────────────────────


def _tag(el) -> str | None:
    return el.tag.upper() if isinstance(el.tag, str) else None


def _clean_lines(text: str) -> str:
    lines = (re.sub(r"\s+", " ", ln).strip() for ln in text.replace("\r", "").split(LINE))
    return "\n".join(ln for ln in lines if ln)


def _span(el, name: str) -> int:
    v = el.get(name) or el.get(name.lower()) or el.get(name.upper())
    try:
        return min(max(int(v), 1), 200) if v else 1
    except ValueError:
        return 1


def _rows_of(table_el) -> list:
    rows = []
    for child in table_el:
        t = _tag(child)
        if t == "TR":
            rows.append(child)
        elif t in ("THEAD", "TBODY", "TFOOT"):
            rows.extend(c for c in child if _tag(c) == "TR")
    return rows


@dataclass
class _FileWalker:
    file_index: int
    file_name: str
    sections: list[Section] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    _buffers: dict[str, list[str]] = field(default_factory=dict)
    _stack: list[str] = field(default_factory=list)

    def _new_section(self, title: str, level: int) -> str:
        sid = f"f{self.file_index}.s{len(self.sections)}"
        self.sections.append(Section(section_id=sid, file_name=self.file_name, title=title, level=level, text="",
                                     table_ids=[]))
        self._buffers[sid] = []
        return sid

    def _current(self, default_title: str) -> str:
        if not self._stack:
            self._stack.append(self._new_section(default_title, 1))
        return self._stack[-1]

    def walk(self, root, default_title: str, has_sections: bool) -> None:
        self.default_title = default_title
        if not has_sections:
            self._stack.append(self._new_section(default_title, 1))
        self._walk(root)
        for s in self.sections:
            s.text = _clean_lines("".join(self._buffers[s.section_id]))
            if not s.title:
                s.title = next((ln for ln in s.text.split("\n") if ln), default_title)[:200]

    def _emit(self, text: str) -> None:
        if text and (text.strip() or LINE in text):
            self._buffers[self._current(self.default_title)].append(text)

    def _walk(self, el) -> None:
        t = _tag(el)
        if t is None:  # 주석·처리 명령
            self._emit(el.tail or "")
            return
        if t in SKIP_TAGS:
            self._emit(el.tail or "")
            return
        if t in SECTION_LEVEL:
            title_el = next((c for c in el if _tag(c) == "TITLE"), None)
            title = _clean_lines(self._inline_text(title_el)) if title_el is not None else ""
            self._stack.append(self._new_section(title.replace("\n", " "), SECTION_LEVEL[t]))
            self._emit(el.text or "")
            for c in el:
                self._walk(c)
            self._stack.pop()
            self._emit(el.tail or "")
            return
        if t == "TABLE":
            sid = self._current(self.default_title)
            text = self._register_table(el, sid)
            self._emit(LINE + text + LINE)
            self._emit(el.tail or "")
            return
        if t in BLOCK_TAGS:
            self._emit(LINE)
        self._emit(el.text or "")
        for c in el:
            self._walk(c)
        if t in BLOCK_TAGS:
            self._emit(LINE)
        self._emit(el.tail or "")

    def _inline_text(self, el) -> str:
        """셀·제목 텍스트. 중첩 표는 행 단위 'a | b'로 펼쳐 넣고, BR·P 경계는 줄바꿈으로."""
        if el is None:
            return ""
        parts: list[str] = []

        def rec(e) -> None:
            t = _tag(e)
            if t is None or t in SKIP_TAGS:
                parts.append(e.tail or "")
                return
            if t == "TABLE":
                parts.append(LINE + self._table_text(e) + LINE)
                parts.append(e.tail or "")
                return
            if t in BLOCK_TAGS:
                parts.append(LINE)
            parts.append(e.text or "")
            for c in e:
                rec(c)
            if t in BLOCK_TAGS:
                parts.append(LINE)
            parts.append(e.tail or "")

        parts.append(el.text or "")
        for c in el:
            rec(c)
        return "".join(parts)

    def _cells(self, tr) -> list[Cell]:
        cells = []
        for c in tr:
            if _tag(c) in CELL_TAGS:
                links = sorted({ref for a in c.iter() if _tag(a) == "A"
                                for ref in [_link_ref(a.get("href") or a.get("HREF") or "")] if ref})
                cells.append(Cell(text=_clean_lines(self._inline_text(c)), colspan=_span(c, "colspan"),
                                  rowspan=_span(c, "rowspan"), links=links))
        return cells

    def _table_text(self, table_el) -> str:
        return LINE.join(" | ".join(c.text.replace("\n", " ") for c in self._cells(tr)) for tr in _rows_of(table_el))

    def _register_table(self, el, section_id: str) -> str:
        tid = f"f{self.file_index}.t{len(self.tables)}"
        table = Table(table_id=tid, section_id=section_id, caption=None, unit_hint=None, rows=[])
        self.tables.append(table)  # 바깥 표가 먼저 번호를 받음(등장 순서)
        section = next(s for s in self.sections if s.section_id == section_id)
        section.table_ids.append(tid)
        for c in el.iter():  # 중첩 표 등록 (같은 섹션)
            if c is not el and _tag(c) == "TABLE":
                self._register_nested(c, section)
        table.rows = [self._cells(tr) for tr in _rows_of(el)]
        caption = next((c for c in el if _tag(c) == "CAPTION"), None)
        table.caption = _clean_lines(self._inline_text(caption)) or None if caption is not None else None
        before = [ln for ln in "".join(self._buffers[section_id])[-300:].split(LINE) if ln.strip()]
        single_first_row = table.rows[0][0].text if table.rows and len(table.rows[0]) == 1 else ""
        for source in (table.caption or "", single_first_row, before[-1] if before else ""):
            if m := UNIT_RE.search(source):
                table.unit_hint = m.group(1).strip()
                break
        return self._table_text(el)

    def _register_nested(self, el, section: Section) -> None:
        tid = f"f{self.file_index}.t{len(self.tables)}"
        self.tables.append(Table(table_id=tid, section_id=section.section_id, rows=[self._cells(tr)
                                                                                 for tr in _rows_of(el)]))
        section.table_ids.append(tid)


def _parse_tree(text: str, warnings: list[str], file_name: str):
    head = text[:5000]
    is_html = not re.search(r"<DOCUMENT[\s>]", head) and re.search(r"<(html|body|table)[\s>]", head, re.IGNORECASE)
    if is_html:
        try:
            return lxml_html.document_fromstring(text), True
        except (etree.ParserError, ValueError) as e:
            raise DocumentParseError(None, f"{file_name}: HTML을 해석할 수 없습니다 ({type(e).__name__})") from None
    fixed, notes = repair_xml(text)
    warnings_local = [f"{file_name}: {n}" for n in notes]
    strict = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
                             remove_comments=True)
    try:
        root = etree.fromstring(fixed, strict)
    except etree.XMLSyntaxError as e:
        recover = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, load_dtd=False,
                                  huge_tree=False, remove_comments=True)
        root = etree.fromstring(fixed, recover)
        if root is None:
            raise DocumentParseError(None, f"{file_name}: XML을 해석할 수 없습니다 (line {e.lineno}).") from None
        # recover는 텍스트를 조용히 버릴 수 있으므로 반드시 표시해 검토 대상으로 만듦
        warnings.append(f"{file_name}: XML 복구 파싱 사용(line {e.lineno}: {e.msg[:80]}) — 일부 내용 누락 가능")
    warnings.extend(w for w in warnings_local if "DOCTYPE" in w or "태그 쌍" in w)
    return root, False


def parse_markup_file(file_index: int, file_name: str, raw: bytes, warnings: list[str]) -> tuple[dict, _FileWalker]:
    text, _encoding = decode_markup(raw)
    root, is_html = _parse_tree(text, warnings, file_name)
    doc_title = None
    for el in root.iter():
        t = _tag(el)
        if t == "DOCUMENT-NAME" or (is_html and t == "TITLE"):
            doc_title = _clean_lines("".join(el.itertext())).replace("\n", " ") or None
            break
    body = root
    if is_html:
        body = root.find(".//body") if root.find(".//body") is not None else root
    has_sections = any(_tag(el) in SECTION_LEVEL for el in body.iter())
    walker = _FileWalker(file_index, file_name)
    walker.walk(body, doc_title or file_name, has_sections)
    return {"file_name": file_name, "doc_title": doc_title}, walker


def parse_zip(rcept_no: str, data: bytes) -> ParsedDocument:
    """원문 ZIP → ParsedDocument. 정정 블록(correction)은 parsing.correction이 채웁니다."""
    from dart_core.parsing.correction import parse_correction  # 순환 import 방지

    entries = [(n, b) for n, b in read_zip(data) if n.lower().endswith(MARKUP_EXT)]
    if not entries:
        raise DocumentParseError(None, "ZIP에 XML/HTML 문서가 없습니다.")
    return parse_correction(build_document(rcept_no, entries))


def build_document(rcept_no: str, entries: list[tuple[str, bytes]]) -> ParsedDocument:
    files, sections, tables, warnings = [], [], [], []
    for i, (name, raw) in enumerate(entries):
        info, walker = parse_markup_file(i, name, raw, warnings)
        files.append(info)
        sections.extend(walker.sections)
        tables.extend(walker.tables)
    return ParsedDocument(rcept_no=rcept_no, parser_version=PARSER_VERSION, files=files, sections=sections,
                          tables=tables, parse_warnings=warnings)


def expand_grid(table: Table) -> list[list[str]]:
    """colspan/rowspan을 값 반복으로 펼친 격자 (05 §2-2 content.tables[].rows 표현)."""
    grid: list[list[str]] = []
    pending: dict[tuple[int, int], str] = {}
    for r, row in enumerate(table.rows):
        out: list[str] = []
        col = 0
        cells = iter(row)
        while True:
            while (r, col) in pending:
                out.append(pending.pop((r, col)))
                col += 1
            cell = next(cells, None)
            if cell is None:
                break
            for dc in range(cell.colspan):
                out.append(cell.text)
                for dr in range(1, cell.rowspan):
                    pending[(r + dr, col + dc)] = cell.text
            col += cell.colspan
        while (r, col) in pending:
            out.append(pending.pop((r, col)))
            col += 1
        grid.append(out)
    return grid
