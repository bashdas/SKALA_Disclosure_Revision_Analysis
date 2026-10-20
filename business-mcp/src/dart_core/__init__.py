"""dart_core — OpenDART 데이터 파이프라인 라이브러리 (F 소유).

- models, interface, status: Business MCP와 맞춘 계약
- titles, normalize: 결정적 순수 함수
- client: OpenDART HTTP (list.json, corpCode.xml, document.xml), corp_codes: 고유번호 캐시·회사 해석
- parsing.document / parsing.correction: 원문 ZIP → ParsedDocument → CorrectionBlock
- live: DartCore Protocol 구현(OpenDART + store 파일 캐시). PostgreSQL ingest·pipeline CLI는 아직 없음
"""
