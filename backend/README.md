# Backend — 실행 뼈대 및 Business API DB 기반 구성

구현 담당자: 박다솔

Python 3.12 이상, Docker와 Docker Compose를 사용합니다. 세 서비스는 독립 FastAPI 애플리케이션이며 공통 설정과 health 응답만 `shared`에서 가져옵니다.
Business MCP는 향후 Business API의 `/internal/**`만 호출합니다. DB 연결 설정과 DB 드라이버를 갖지 않습니다. RAG MCP는 향후 PostgreSQL + pgvector를 읽는 검색 전용 서비스입니다.

## 구조

```text
backend/
├── business-api/          # 업무 데이터 Source of Truth, :8080
├── mcp/
│   ├── business-mcp/      # 내부 HTTP API adapter, :8081/mcp
│   └── rag-mcp/           # 검색 전용, :8082/mcp
├── shared/               # disclosure_shared 패키지
├── .env.example
├── docker-compose.yml
└── README.md
```

## Docker Compose

저장소 루트에서:

```bash
cd backend
cp .env.example .env
# .env의 개발용 비밀번호를 변경하면 DATABASE_URL/RABBITMQ_URL도 함께 변경
# JWT_SECRET_KEY는 최소 32 bytes의 무작위 값으로 설정 (change-me로는 인증 불가)

docker compose config --quiet
docker compose up --build -d
docker compose ps
curl -f http://localhost:8080/health
```

API만 호스트 loopback에 공개합니다. MCP, PostgreSQL, RabbitMQ는 Compose 기본 내부 네트워크를 사용하며 호스트 포트는 공개하지 않습니다. MCP 주소는 `http://business-mcp:8081/mcp`, `http://rag-mcp:8082/mcp`입니다. 향후 AI Agent가 같은 네트워크에 참여해야 합니다.

```bash
docker compose exec business-mcp python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8081/health').read().decode())"
docker compose exec rag-mcp python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8082/health').read().decode())"
docker compose logs -f business-api business-mcp rag-mcp
docker compose down
```

`down`은 이름 있는 DB/큐 볼륨을 보존합니다. pgvector 이미지를 준비했고 core 업무 schema는 Alembic migration으로 관리합니다. pgvector extension 활성화와 큐 선언·연결 코드는 아직 없습니다. PostgreSQL 초기 자격 증명은 빈 볼륨을 처음 생성할 때 적용됩니다.

## 로컬 독립 실행

각 서비스마다 별도 가상환경을 사용합니다. 모두 `app` 패키지 이름을 쓰므로 한 가상환경에 세 서비스를 함께 설치하지 않습니다. 아래 명령은 저장소 루트 기준입니다.

Business API:

```bash
cd backend/business-api
python3 -m venv .venv
.venv/bin/python -m pip install -e ../shared -e '.[dev]'
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Business MCP:

```bash
cd backend/mcp/business-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e ../../shared -e '.[dev]'
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8081
```

RAG MCP:

```bash
cd backend/mcp/rag-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e ../../shared -e '.[dev]'
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8082
```

설정은 프로세스 환경변수 및 실행 디렉터리의 `.env`에서 읽습니다(환경변수 우선). Compose는 `backend/.env`를 사용합니다. 로컬 실행은 기본값으로 외부 인프라 없이 가능합니다. 필요하면 해당 서비스 폴더에 `.env`를 두거나 환경변수를 export하세요. 로컬 인프라 주소는 Docker 서비스 이름 대신 실제 접근 가능한 주소로 바꿔야 합니다.

```bash
curl -f http://localhost:8080/health
curl -f http://localhost:8081/health
curl -f http://localhost:8082/health
# 각 서비스 폴더에서 실행
.venv/bin/python -m pytest -q
```

세 health 응답은 `{"status":"ok","service":"서비스 이름"}`입니다. 프로세스 liveness만 나타내며 DB/큐 readiness를 보장하지 않습니다. `/mcp`는 MCP JSON-RPC endpoint로 일반 GET health check 대상이 아닙니다.

MCP는 공식 Python SDK v1의 Streamable HTTP를 사용합니다. JSON 응답/stateless 모드이며 업무 Tool은 0개입니다. 별도 SSE endpoint는 구현하지 않습니다. FastAPI lifespan에서 MCP session manager를 시작합니다. 참고: [공식 SDK ASGI 실행 문서](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/README.md#mounting-to-an-existing-asgi-server).
내부 호스트 이름과 localhost만 허용합니다. 프록시 또는 새 도메인 추가 시 해당 MCP 서비스의 `MCP_ALLOWED_HOSTS`를 JSON 배열로 지정하세요. 내부 인증과 권한 처리는 다음 단계입니다.

## 다음 단계 / TODO

- RAG 모델·pgvector extension·checkpoint 영역의 별도 migration 설계
- 실제 업무 endpoint별 조직/역할 정책 적용 및 서비스 간 내부 인증 (JWT 로그인/current_user/RBAC 기반은 구현됨)
- 분석 생성 API·나머지 업무 API, `/internal/**`, Business MCP HTTP client와 실제 Tool (Filing/Memo 조직 범위 조회는 구현됨)
- RabbitMQ queue 선언, 메시지 계약, publish/consume, 재시도와 중복 처리
- RAG read-only DB 계정, 검색·원문·claim source Tool, embedding 정책
- 의존성 lock 파일, CI, 운영 비밀 관리와 readiness 정책
- frontend, ai-agent, LangGraph checkpoint는 별도 영역에서 구현

## Business API DB 구성

SQLAlchemy 2.x sync + psycopg 3를 사용합니다. 현재 업무 중심 서비스의 트랜잭션을 단순하게 관리하기 위한 선택이며 DB를 사용하는 Router는 `def`로 작성해 FastAPI thread pool에서 실행합니다. `async def`에서 sync DB 작업을 직접 실행하지 않습니다.

`app/core/database.py`의 `Base`가 공통 ORM base입니다. Engine과 session factory는 프로세스별로 지연 생성하며 PostgreSQL 연결 URL은 `postgresql+psycopg://`만 허용합니다. 연결 timeout은 `DATABASE_CONNECT_TIMEOUT`(기본 3초)입니다. 실행 중 환경변수 변경 시 프로세스를 재시작하세요.

`Depends(get_db)`로 요청별 Session을 받습니다. dependency 종료 시 Session을 닫아 미완료 트랜잭션을 rollback하고 자동 commit은 하지 않습니다. 향후 Service가 `with session.begin():` 또는 명시적 `commit()/rollback()`으로 경계를 관리합니다. Repository는 commit하지 않습니다. Service에서 `session.begin()`을 쓸 경우 그 전에 같은 Session에서 쿼리를 실행해 autobegin한 상태가 아닌지 확인해야 합니다.

DB가 없어도 `/health`는 기존 응답을 유지합니다. `/health/db`는 `SELECT 1` 성공 시 `200 {"status":"ok","service":"business-api-db"}`, 설정 누락·연결 실패 시 세부 credential을 노출하지 않는 `503 {"detail":"Database unavailable"}`을 반환합니다. Engine 생성과 연결만 준비하며 시작 시 테이블을 생성하지 않습니다.

환경변수는 `backend/.env.example`의 예시를 참고하세요. 예시 비밀번호는 실제 credential이 아닙니다. 로컬 실행은 서비스 실행 디렉터리의 `.env` 또는 export한 환경변수를 읽으며, Compose의 `postgres` 호스트 이름은 Compose 네트워크에서만 해석됩니다. 비밀번호의 특수 문자는 URL-encode하세요.

### Alembic 실행

Business API 폴더에서 로컬 가상환경으로:

```bash
cd backend/business-api
# DATABASE_URL 설정 후
.venv/bin/alembic current
.venv/bin/alembic check
.venv/bin/alembic upgrade head
# 후속 schema 변경 시 revision 생성 및 검토
```

Compose에서는 저장소의 backend 폴더에서:

```bash
docker compose up -d --build business-api
docker compose exec business-api alembic current
docker compose exec business-api alembic check
curl -f http://localhost:8080/health/db
```

`env.py`가 앱과 동일한 설정으로 URL을 읽고 `app.models`를 import하여 `Base.metadata`에 연결합니다. 새 모델은 `app/models/__init__.py`에서 명시적으로 import해야 합니다. 13개 업무 모델과 `0001_initial_core` → `0002_align_report_flow` revision chain이 있습니다. 업무 테이블은 `core` schema에 생성하며 autogenerate는 core만 비교합니다. RAG/checkpoint/public의 다른 테이블은 제외합니다. `create_all`은 사용하지 않습니다. 상세 nullable·unique·삭제 정책과 PostgreSQL 모델/migration 테스트는 [Business API README](business-api/README.md)를 참고하세요.

### PostgreSQL 테스트

```bash
cd backend/business-api
.venv/bin/python -m pytest -q
# 전용 임시 PostgreSQL DB를 지정하면 통합 테스트까지 실행
# TEST_DATABASE_URL은 실제 credential을 문서나 커밋에 넣지 않고 로컬에서 설정
TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest -q
```

통합 테스트는 일반 개발·운영 DB가 아닌 전용 테스트 DB를 사용하세요. migration을 적용하므로 공유 DB를 지정하지 마세요. `TEST_DATABASE_URL` 미설정 시 PostgreSQL 연결·모델 테스트는 skip합니다. downgrade 왕복 테스트는 추가로 `TEST_ALLOW_SCHEMA_RESET=1`이 필요합니다. 잘못된 password가 거부되는 password 인증 DB여야 합니다. 테스트는 연결, health, 트랜잭션 정리, 업무 제약조건, Alembic 비교를 확인합니다. 업무 테이블은 migration으로 생성하고 모델 테스트 데이터는 rollback합니다.

구현 근거: [SQLAlchemy Session 관리](https://docs.sqlalchemy.org/en/20/orm/session_basics.html), [Alembic metadata 연결](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).
