"""원문 파서: ZIP 제한, 인코딩·XML 결함 보정, 병합 셀, 중첩 표, 결정적 ID, 정정 표·각주.

[합성] 표시는 테스트용으로 직접 만든 입력, [실제] 표시는 tests/fixtures/real의 DART 공개 뷰어 원문입니다.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest

from dart_core.models import Cell, Table
from dart_core.parsing.correction import parse_correction
from dart_core.parsing.document import build_document, decode_markup, expand_grid, parse_zip, read_zip, repair_xml
from dart_core.status import DocumentParseError

REAL = Path(__file__).parent / "fixtures" / "real"
GOLDEN = {c["correction"]: c for c in json.loads((REAL / "golden.json").read_text(encoding="utf-8"))["cases"]}


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def xml_doc(body: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?><DOCUMENT><DOCUMENT-NAME ACODE="11">[합성] 문서</DOCUMENT-NAME>'
            f"<BODY>{body}</BODY></DOCUMENT>").encode()


# ── ZIP ──────────────────────────────────────────────────────────────────


def test_zip_entries_sorted_and_paths_flattened():
    data = make_zip({"dir/b.xml": b"b", "/a.xml": b"a", "../c.jpg": b"c"})
    assert [n for n, _ in read_zip(data)] == ["a.xml", "b.xml", "c.jpg"]


@pytest.mark.parametrize("entries, kwargs, message", [
    ({f"{i}.xml": b"x" for i in range(5)}, {"max_entries": 4}, "엔트리가 너무 많"),
    ({"a.xml": b"x" * 2000}, {"max_entry_bytes": 1000}, "너무 큽니다"),
    ({"a.xml": b"x" * 600, "b.xml": b"x" * 600}, {"max_total_bytes": 1000}, "상한"),
    ({"x/a.xml": b"1", "y/a.xml": b"2"}, {}, "같은 파일명"),
])
def test_zip_limits_fail_whole_archive(entries, kwargs, message):
    with pytest.raises(DocumentParseError) as e:
        read_zip(make_zip(entries), **kwargs)
    assert message in str(e.value)


def test_bad_or_empty_zip():
    with pytest.raises(DocumentParseError):
        read_zip(b"PK\x03\x04 not really")
    with pytest.raises(DocumentParseError):
        read_zip(make_zip({}))
    with pytest.raises(DocumentParseError, match="XML/HTML"):
        parse_zip("1" * 14, make_zip({"image.jpg": b"\xff\xd8"}))


# ── 인코딩·보정 ──────────────────────────────────────────────────────────


def test_cp949_declared_as_utf8():
    raw = '<?xml version="1.0" encoding="utf-8"?><DOCUMENT><BODY><P>계약금액</P></BODY></DOCUMENT>'.encode("cp949")
    text, enc = decode_markup(raw)
    assert enc == "cp949" and "계약금액" in text
    doc = build_document("1" * 14, [("a.xml", raw)])
    assert "계약금액" in doc.sections[0].text and doc.parse_warnings == []


def test_repair_dart_xml_defects():
    fixed, _ = repair_xml("<P>R&D <기후변화> 1&cr;2 &nbsp;x</P>")
    assert fixed == "<P>R&amp;D &lt;기후변화> 1&#8232;2 &#160;x</P>"
    doc = build_document("1" * 14, [("a.xml", xml_doc("<P>R&D <시장 동향> 증가</P>"))])
    assert "R&D <시장 동향> 증가" in doc.sections[0].text and doc.parse_warnings == []


def test_external_entity_and_dtd_are_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    raw = (f'<?xml version="1.0"?><!DOCTYPE DOCUMENT [<!ENTITY x SYSTEM "file://{secret}">]>'
           "<DOCUMENT><BODY><P>&x;</P></BODY></DOCUMENT>").encode()
    doc = build_document("1" * 14, [("a.xml", raw)])
    assert "TOP-SECRET" not in doc.sections[0].text
    assert any("DOCTYPE" in w for w in doc.parse_warnings)


def test_broken_xml_is_flagged_not_hidden():
    doc = build_document("1" * 14, [("a.xml", xml_doc("<SECTION-1><TITLE>제목</TITLE><P>열린 문단</SECTION-1>"))])
    assert any("XML 복구 파싱" in w for w in doc.parse_warnings)


# ── 표·섹션 ──────────────────────────────────────────────────────────────


def test_expand_grid_colspan_rowspan():
    t = Table(table_id="f0.t0", section_id="f0.s0", rows=[
        [Cell(text="A", rowspan=2), Cell(text="B", colspan=2)],
        [Cell(text="C"), Cell(text="D")],
    ])
    assert expand_grid(t) == [["A", "B", "B"], ["A", "C", "D"]]


def test_sections_tables_nested_and_deterministic_ids():
    body = ("<SECTION-1><TITLE>1. 개요</TITLE><P>(단위 : 백만원)</P>"
            "<TABLE BORDER='1'><TBODY><TR><TD>항목</TD><TD>값<BR/>둘째 줄</TD></TR>"
            "<TR><TD>표안표</TD><TD><TABLE><TR><TE>1차</TE><TU AUNIT='x'>100</TU></TR></TABLE></TD></TR></TBODY></TABLE>"
            "<SECTION-2><TITLE>1-1. 세부</TITLE><P>세부 내용</P></SECTION-2></SECTION-1>")
    entries = [("b.xml", xml_doc("<P>두번째 파일</P>")), ("a.xml", xml_doc(body))]
    doc1 = build_document("1" * 14, sorted(entries))
    doc2 = build_document("1" * 14, sorted(entries))
    assert doc1 == doc2
    assert [f["file_name"] for f in doc1.files] == ["a.xml", "b.xml"]
    sec = {s.section_id: s for s in doc1.sections}
    assert sec["f0.s1"].title == "1. 개요" and sec["f0.s1"].level == 1
    assert sec["f0.s2"].title == "1-1. 세부" and sec["f0.s2"].level == 2 and "세부 내용" not in sec["f0.s1"].text
    outer, nested = doc1.tables[0], doc1.tables[1]
    assert (outer.table_id, nested.table_id) == ("f0.t0", "f0.t1") and outer.unit_hint == "백만원"
    assert len(outer.rows) == 2 and outer.rows[0][1].text == "값\n둘째 줄"
    assert outer.rows[1][1].text == "1차 | 100" and nested.rows == [[Cell(text="1차"), Cell(text="100")]]
    assert sec["f0.s1"].text.count("1차 | 100") == 1  # 중첩 표 텍스트 중복 없음
    assert doc1.sections[-1].section_id == "f1.s0"


def test_html_markup_case_insensitive():
    html = ("<html><head><meta charset='euc-kr'></head><body><table><tr><td colspan='2'>합계</td></tr>"
            "<tr><td>a</td><td>b</td></tr></table></body></html>").encode("cp949")
    doc = build_document("1" * 14, [("a.html", html)])
    assert doc.tables[0].rows[0][0].colspan == 2 and doc.tables[0].rows[1][1].text == "b"


# ── 정정 파서 [합성] ─────────────────────────────────────────────────────


def correction_xml(table: str, extra: str = "") -> bytes:
    return xml_doc(
        "<LIBRARY><CORRECTION><TITLE>정 정 신 고 (보고)</TITLE>"
        "<TABLE><TR><TD>1. 정정대상 공시서류 :</TD><TD>주요사항보고서(유상증자결정)</TD></TR></TABLE>"
        "<TABLE><TR><TD>2. 정정대상 공시서류의 최초제출일 :</TD><TD>2026년 03월 05일</TD></TR></TABLE>"
        f"<P>3. 정정사항</P>{table}{extra}</CORRECTION></LIBRARY><SECTION-1><TITLE>본문</TITLE><P>내용</P></SECTION-1>")


def test_five_column_table_with_footnotes():
    table = ("<TABLE BORDER='1'><THEAD><TR><TH>항 목</TH><TH>정정요구ㆍ명령 관련 여부</TH><TH>정정사유</TH>"
             "<TH>정 정 전</TH><TH>정 정 후</TH></TR></THEAD><TBODY>"
             "<TR><TD>신주의 수</TD><TD>미해당</TD><TD>수량 조정</TD><TD>1,000,000</TD><TD>1,200,000</TD></TR>"
             "<TR><TD>자금조달 목적</TD><TD>해당</TD><TD>정정요구</TD><TD>(주1) 정정 전 참조</TD><TD>(주1) 정정 후 참조</TD></TR>"
             "<TR><TD></TD><TD>미해당</TD><TD>기재 보완</TD><TD>(주2) 정정 전 참조</TD><TD>-</TD></TR>"
             "</TBODY></TABLE>")
    notes = "<P>(주1) 정정 전</P><P>시설자금 100억원</P><P>(주1) 정정 후</P><P>시설자금 120억원</P>"
    doc = parse_correction(build_document("1" * 14, [("a.xml", correction_xml(table, notes))]))
    b = doc.correction
    assert b.target_document_name == "주요사항보고서(유상증자결정)" and str(b.first_submitted_date) == "2026-03-05"
    assert [i.item_label for i in b.items] == ["신주의 수", "자금조달 목적", "자금조달 목적"]  # 빈 항목은 윗행 승계
    assert [i.regulator_ordered for i in b.items] == [False, True, False]
    assert b.items[1].before_footnote == "시설자금 100억원" and b.items[1].after_footnote == "시설자금 120억원"
    assert b.unresolved_refs == ["주2"] and b.parse_warnings == []
    assert doc.sections[0].title == "[합성] 문서"  # DOCUMENT-NAME 등 섹션 밖 머리 → 앞 섹션
    assert doc.sections[1].title == "정 정 신 고 (보고)" and doc.sections[1].section_id == "f0.s1"


def test_two_row_header_and_multiple_tables_keep_ids_unique():
    t1 = ("<TABLE BORDER='1'><TR><TH ROWSPAN='2'>항목</TH><TH COLSPAN='2'>정정내용</TH></TR>"
          "<TR><TH>정정 전</TH><TH>정정 후</TH></TR><TR><TD>납입일</TD><TD>2026-04-20</TD><TD>2026-05-04</TD></TR></TABLE>")
    t2 = ("<TABLE BORDER='1'><TR><TH>항목</TH><TH>정정 전</TH><TH>정정 후</TH></TR>"
          "<TR><TD>청약일</TD><TD>2026-04-10</TD><TD>2026-04-24</TD></TR></TABLE>")
    b = parse_correction(build_document("1" * 14, [("a.xml", correction_xml(t1 + t2))])).correction
    assert [(i.row_index, i.table_row_index, i.table_id) for i in b.items] == [(1, 1, "f0.t2"), (2, 1, "f0.t3")]
    assert b.items[0].before_raw == "2026-04-20" and b.items[0].reason is None


def test_header_without_correction_table_is_flagged():
    b = parse_correction(build_document("1" * 14, [("a.xml", correction_xml("<P>표 없음</P>"))])).correction
    assert b.items == [] and "정정사항 표" in b.parse_warnings[0]


def test_non_correction_document_has_no_block():
    doc = parse_correction(build_document("1" * 14, [("a.xml", xml_doc("<P>단일판매ㆍ공급계약체결</P>"))]))
    assert doc.correction is None


# ── 정정 파서 [실제] DART 공개 뷰어 원문 ─────────────────────────────────


def real_doc(rcept_no: str):
    raw = (REAL / "viewer" / f"{rcept_no}.html").read_bytes()
    return parse_correction(build_document(rcept_no, [(f"{rcept_no}.html", raw)]))


def test_real_kind_disclosure_header_and_related_link():  # 수시공시(HTML, 3열)
    b = real_doc("20261019800110").correction
    assert b.target_document_name == "단일판매ㆍ공급계약 체결"
    assert b.first_submitted_date is None and str(b.previous_filing_date) == "2026-10-19"
    assert b.related_disclosures == [{"date": "2025-12-23", "document_name": "단일판매ㆍ공급계약체결",
                                      "rcept_no": "20251223800740"}]
    assert [(i.item_label, i.before_raw, i.after_raw) for i in b.items[:2]] == [
        ("2. 계약내역 / 계약금액(원)", "943,000,000,000", "1,284,544,500,098"),
        ("2. 계약내역 / 매출액대비(%)", "2.6", "3.5")]
    assert b.items[0].reason == "공급 실적 확정에 따른 계약금액 변경"  # 머리말 '3. 정정사유'를 행에 적용


def test_real_major_report_four_columns():  # 주요사항보고서(dart4 → 뷰어 HTML, 4열)
    b = real_doc("20261019000366").correction
    assert str(b.first_submitted_date) == "2026-10-14" and b.previous_filing_date is None
    assert b.items[0].item_label == "5. 사채만기일" and b.items[0].before_raw == "2031년 10월 26일"
    assert b.items[2].before_raw == "-주식 수 : 3,385,240\n-주식 총수 대비 비율(%): 11.18"
    assert b.items[0].reason == "발행 대상자 변경으로 인한 정정" and len(b.items) == 11
    assert "1차 | 2028-08-27" in b.items[7].before_raw  # 셀 안 중첩 표 보존


def test_real_original_is_not_a_correction():
    assert real_doc("20251223800740").correction is None


# ── 정정 파서 [실제-API] document.xml ZIP 원문 ──────────────────────────


def api_doc(rcept_no: str):
    return parse_zip(rcept_no, (REAL / "api" / "zip" / f"{rcept_no}.zip").read_bytes())


def test_api_kind_disclosure_is_html_in_xml_file_with_kind_link():
    doc = api_doc("20261019800110")
    assert doc.files == [{"file_name": "20261019800110.xml",
                          "doc_title": "S-Oil/단일판매ㆍ공급계약체결/(2026.10.19)단일판매ㆍ공급계약체결"}]
    b = doc.correction
    assert doc.parse_warnings == [] and str(b.previous_filing_date) == "2026-10-19"
    # API 원문의 관련공시는 거래소(KIND) 링크: acptno는 DART 접수번호(20251223800740)와 달라 rcept_no로 쓰지 않음
    assert b.related_disclosures == [{"date": "2025-12-23", "document_name": "단일판매ㆍ공급계약체결",
                                      "rcept_no": None, "kind_acptno": "20251223000740"}]
    assert [(i.before_raw, i.after_raw) for i in b.items[:2]] == [("943,000,000,000", "1,284,544,500,098"),
                                                                    ("2.6", "3.5")]


def test_api_dart4_xml_correction_block():
    doc = api_doc("20261019000366")
    assert doc.parse_warnings == [] and any(s.title.replace(" ", "") == "정정신고(보고)" for s in doc.sections)
    b = doc.correction
    assert str(b.first_submitted_date) == "2026-10-14" and len(b.items) == 11
    assert b.items[2].before_raw == "-주식 수 : 3,385,240-주식 총수 대비 비율(%): 11.18"  # 원문은 줄바꿈 없음


def test_api_original_has_no_correction_block():
    assert api_doc("20251223800740").correction is None and api_doc("20261014000424").correction is None
