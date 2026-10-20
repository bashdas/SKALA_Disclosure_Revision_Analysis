# RAG MCP MVP

담당: 박다솔

Streamable HTTP `/mcp`, process health `/health`. Agent/LLM 판단·상태 변경은 없습니다.

## 실행

저장소 루트에서 `backend/.env.example`을 참고해 로컬 `backend/.env`를 준비합니다.
`DATABASE_URL`은 기존 sync SQLAlchemy 규칙인 `postgresql+psycopg://...`을 사용합니다.
`OPENAI_API_KEY`는 실제 로컬 secret을 설정하며 저장소에 기록하지 않습니다.

```bash
cd backend
docker compose build rag-mcp
docker compose up -d postgres
docker compose run --rm --no-deps rag-mcp alembic upgrade head
docker compose up -d rag-mcp
```

Compose가 Business MCP / External MCP와 그 의존성을 함께 시작합니다. RAG 포트는 내부 네트워크에만 expose됩니다.
MCP URL 기본값은 `http://rag-mcp:8082/mcp`입니다. ingress 인증을 별도로 추가하지 않았으므로 신뢰된 내부 네트워크에서 사용합니다.

독립 실행은 rag-mcp 디렉터리에서 Python 3.12 가상환경에 shared와 해당 패키지를 설치한 뒤 실행합니다.

```bash
pip install -e ../../shared -e '.[dev]'
# 아래 값은 shell export 또는 현재 디렉터리 .env로 설정합니다.
# DATABASE_URL, BUSINESS_MCP_URL, EXTERNAL_MCP_URL, OPENAI_API_KEY
alembic upgrade head
python -m app
```

HOST/PORT는 `RAG_MCP_HOST`/`RAG_MCP_PORT`, 요청 제한 시간은 `RAG_MCP_REQUEST_TIMEOUT_SECONDS`입니다.
기본 health는 DB나 embedding 서비스 준비 여부를 보장하지 않습니다. migration은 startup에서 자동 실행하지 않습니다.

## Tool과 데이터 흐름

- `ensure_analysis_index(task_id)`: 공식 MCP SDK Client로 Business MCP `get_analysis_context`를 호출합니다. 고정된 Memo 버전 및 조직을 확보하고 External MCP `get_disclosure`로 공시를 취득합니다. Agent는 원문을 중계하지 않습니다. 문서별 chunk/vector 저장이 완료된 뒤 Task manifest를 연결합니다.
- `search_evidence(task_id, query, top_k=5, document_types=null)`: Business MCP에서 최신 context를 확인하고 해당 조직 및 Task manifest의 Memo/공시 문서만 검색합니다. types는 `MEMO`, `DISCLOSURE`, top_k는 1~20입니다. 검색은 자동 색인하지 않으며 미준비 시 `INDEX_NOT_READY` Tool Error를 반환합니다.

정상 검색에서 임계값에 맞는 결과가 없으면 `results: []`입니다. MCP/embedding/DB 장애는 Tool Error로 구분합니다.
응답 score는 `(cosine_similarity + 1) / 2`로 0~1, 높을수록 유사합니다.
`RAG_MIN_SIMILARITY=0.6`은 이 normalized score 기준이며 실제 문서 평가 후 조정할 수 있습니다.
query는 최대 2000 Unicode 문자입니다.

## Embedding / chunking

실제 provider는 OpenAI Embeddings API, 모델은 `text-embedding-3-small`, 1536차원입니다.
[공식 명세](https://developers.openai.com/api/docs/guides/embeddings)를 기준으로 구현했습니다.
별도 추론 서버가 필요 없고 한국어/영문 입력을 처리할 수 있는 MVP 선택입니다.
문서 text와 검색 query가 embedding API에 전송됩니다. LLM 생성 호출은 없습니다.
provider는 `EmbeddingService` 계약 및 `create_app(embedding=...)`로 fake를 주입할 수 있습니다.
모델/차원을 바꾸려면 migration 및 색인 fingerprint 정책도 함께 변경해야 합니다.

Chunk 기본값은 Unicode 문자 1000/overlap 100입니다. 문단/heading 경계를 우선하고 표는 행을 분리 단위로 사용합니다.
큰 표는 헤더를 반복하며 같은 행의 정정 전·후 셀을 분리하지 않습니다. 2000문자를 초과하는 단일 표 행은 임의 절단 대신 `CHUNK_TOO_LARGE`로 거부합니다.
파서가 제공한 표/heading 정보를 chunk metadata에 보존하며 의미 분석은 하지 않습니다.

## DB 및 재사용

독립 Alembic 이력은 `rag.alembic_version`, revision은 `0001_rag_index`입니다.
`rag.documents`, `rag.chunks`, `rag.analysis_indexes`만 소유하며 core table은 읽거나 수정하지 않습니다.
`CREATE EXTENSION IF NOT EXISTS vector` 권한이 필요합니다. extension이 없는 운영 환경에서는 DBA가 먼저 설치할 수 있습니다.

Memo는 조직/ID/version/content hash, 공시는 조직/receipt/파싱된 내용 hash로 식별합니다.
embedding 모델·차원·chunk 설정 fingerprint도 재사용 키에 포함합니다.
같은 문서는 다시 embedding하지 않습니다. 공시 내용 변경 감지를 위해 ensure 호출 시 원문은 다시 취득합니다.
동시 최초 요청은 embedding 호출이 중복될 수 있지만 DB unique와 문서 단위 transaction으로 chunk 중복은 막습니다.
문서와 chunk는 함께 commit되며 두 문서가 준비된 뒤 manifest를 갱신합니다. 일부 문서 취득 실패 시 준비된 문서 캐시는 다음 호출에 재사용합니다.

조직 필터 + Task의 두 문서 ID로 범위를 고정하고 pgvector cosine distance로 exact 검색합니다.
MVP 규모에서는 ANN index 없이 정확도를 우선하며 범위 조회용 B-tree index를 둡니다.
조직 복합 FK로 문서/chunk/manifest의 조직 일관성을 보장합니다.
Disclosure도 조직별로 저장합니다. RAG 파생 자료만 삭제 시 chunk cascade를 사용합니다.

```bash
# RAG 데이터가 삭제됩니다. core migration과 독립된 이력입니다.
alembic downgrade base
alembic upgrade head
```

downgrade는 공유될 수 있는 vector extension과 rag schema 자체를 제거하지 않습니다.

## 검증 상태

이번 요청에 따라 테스트, PostgreSQL smoke test, migration upgrade/downgrade, 실제 embedding API 호출은 실행하지 않았습니다.
API key를 Tool 입력이나 응답으로 전달하지 않으며 Business API/OpenDART를 직접 호출하지 않습니다.
