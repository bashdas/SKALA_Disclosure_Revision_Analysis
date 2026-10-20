# 공시체크 Business MCP

정정 공시 검색, 원본·직전본 매칭, 정정사항 표 기반 변경값 비교, 메모 조회를 제공하는 FastMCP 서버입니다.
계약(Tool 입출력, 오류 코드)은 `docs/05_API_AND_DATA_CONTRACTS.md`, 코드상 원천은 `src/business_mcp/schemas.py`입니다.
구현 보고서는 `docs/08_LIVE_IMPLEMENTATION_REPORT.md`, 실제 원문 관찰은 `docs/spike_notes.md`에 있습니다.

> `.gitignore`에 `docs/`가 있어 위 문서들은 Git에 올라가지 않습니다. 팀과 공유하려면 이 항목을 빼거나 따로 전달해야 합니다.

## 실행

```bash
uv sync
uv run pytest                                   # 네트워크·DB 없이 실행 (실제 OpenDART 테스트 5개는 skip)
uv run python -m business_mcp.server            # http://127.0.0.1:8100/mcp, GET /health
```

### Mock (기본)

`DATA_BACKEND=mock`(기본값)이면 `src/business_mcp/mock/data/`의 **가상 데이터**를 씁니다. 키가 필요 없습니다.
응답의 `meta.source="mock"`, `meta.warnings[0]`이 `MOCK_DATA: …`입니다.

### Live (OpenDART 실조회)

```bash
cp .env.example .env        # DATA_BACKEND=live, OPENDART_API_KEY=<발급받은 40자 키> 를 직접 입력
uv run python -m business_mcp.server
```

- 키는 프로젝트 `.env`(또는 환경변수)에만 두세요. 채팅·커밋·로그에 남기지 마세요.
- `DART_DATA_DIR`(기본 `./data/dart`)에 원문 ZIP·파싱 결과·공시 메타·고유번호를 파일로 캐시합니다. **PostgreSQL 저장소가 아닙니다**(아래 '제한').
- 키가 없거나 형식이 틀리면 Tool은 `UPSTREAM_AUTH` 오류, `/health`는 503 `misconfigured`를 돌려줍니다. mock으로 조용히 바꾸지 않습니다.
- `/health`는 프로세스 생존과 설정만 확인합니다(`upstream_checked: false`). OpenDART 연결은 확인하지 않습니다(호출 한도 보호).

### 검증 스크립트

```bash
uv run python scripts/e2e_http.py --mode replay   # live 서버 프로세스 ↔ 로컬 가짜 OpenDART(실제 공시 fixture)를 HTTP로 검증
uv run python scripts/e2e_http.py --mode nokey    # live인데 키 없음: /health 503, Tool UPSTREAM_AUTH
uv run python scripts/e2e_http.py --mode real     # 실제 OpenDART (.env 키 필요)
RUN_LIVE_OPENDART=1 uv run pytest tests/test_live_network.py -v   # 실제 OpenDART 테스트 (opt-in)
uv run python scripts/golden.py api --out tests/fixtures/real/api --rcept 20261019800110 20261019000366  # 실제 ZIP fixture 수집
```

## Tool 지원 상태

| Tool | mock | live |
|---|---|---|
| `search_filings` | 동작 | 동작 (corpCode.xml 회사 해석 + list.json) |
| `get_filing_diff` | 동작 | 동작 (document.xml ZIP → 파싱 → 정정사항 표 → 매칭·diff). 실제 ZIP으로 검증 |
| `get_analysis_memo` | 동작 (가상 메모) | `NOT_IMPLEMENTED` (PostgreSQL 메모 저장소 미구현, 가상 메모를 섞지 않음) |
| `get_filing_document` | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` (내부 파서는 있지만 공개 Tool은 미구현) |
| `save_review_decision` | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` (태그 `no_llm_binding`, LLM에 바인딩 금지) |

오류는 `isError=true` + 본문 JSON `{"error": {code, message, retryable, details}}` (`schemas.ErrorResponse`로 검증).

## diff가 비교하는 것

`get_filing_diff`의 변경값은 **정정 공시 안 '정정사항' 표에 회사가 적은 정정 전·정정 후 값**입니다. 원본과 정정본 문서 전체를
비교해 모든 변경을 찾는 기능이 아닙니다. 2차 이상 정정의 '정정 전'은 최초 원본이 아니라 바로 앞 버전 기준입니다.
원본을 연결이 확인되지 않은 채 추정하지 않으며, 확실하지 않으면 `match.status != "matched"` 또는 `needs_review=true`로 돌려줍니다.

## 검증 수준

| 수준 | 내용 | 상태 (2026-10-20) |
|---|---|---|
| 1. 합성 fixture 단위 테스트 | `tests/test_client.py`, `test_parsing.py`, `test_live.py`의 [합성], 기존 mock 테스트 | 통과 |
| 2. 실제 공시 오프라인 재생 | `tests/fixtures/real`: DART 뷰어 HTML 11건 + **실제 document.xml ZIP 15건**·list.json 3건 | 통과 (in-memory MCP + HTTP 프로세스) |
| 3. 실제 OpenDART 네트워크 호출 | `RUN_LIVE_OPENDART=1 uv run pytest tests/test_live_network.py` | 통과 (5개) |
| 4. 실제 OpenDART로 HTTP `/mcp` | `scripts/e2e_http.py --mode real` | 통과 |

`(주N)` 각주와 5열 정정사항 표는 실제 사례를 못 찾아 합성 fixture로만 확인했습니다.
기본 `pytest`는 프로젝트 `.env`를 읽지 않습니다(`tests/conftest.py`). 실제 키는 opt-in 테스트와 스크립트만 씁니다.

## 실데이터로 바꿀 곳

| 무엇 | 위치 |
|---|---|
| mock ↔ live 선택 | `src/business_mcp/providers.py` |
| OpenDART HTTP·상태코드 | `src/dart_core/client.py`, `status.py` |
| 회사 해석·고유번호 캐시 | `src/dart_core/corp_codes.py` |
| 원문 파서·정정 파서 | `src/dart_core/parsing/document.py`, `parsing/correction.py` |
| live 공급원·파일 캐시 | `src/dart_core/live.py`, `store.py` (→ 후속: `filings`, `filing_documents`, `companies` 테이블) |
| 메모 저장소 | `TODO(live-memo)`: `business_mcp/db/repository.py` (PostgreSQL) |
| diff 결과 캐시·`force_recompute` | `services/diff.py` (→ 후속: `filing_links`, `filing_changes`) |
