# Backend — 1단계

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
# JWT_SECRET_KEY는 실제 인증 구현 전에 안전한 값으로 설정

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

`down`은 이름 있는 DB/큐 볼륨을 보존합니다. pgvector 이미지까지 준비하지만 extension 활성화, DB 스키마, 큐 선언과 연결 코드는 아직 없습니다. PostgreSQL 초기 자격 증명은 빈 볼륨을 처음 생성할 때 적용됩니다.

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

- SQLAlchemy, PostgreSQL 드라이버, Alembic 설치 및 환경 구성: 현재 DB 관련 의존성은 실제 사용 전까지 추가하지 않았습니다. `alembic.ini`와 디렉터리는 예약 구조이며 migration 실행은 아직 지원하지 않습니다.
- core/rag 모델, 스키마 소유권, pgvector extension 및 실제 migration 설계
- JWT 발급·검증, 조직/역할 접근 제어, 서비스 간 내부 인증
- 업무 API, `/internal/**`, Business MCP HTTP client와 실제 Tool
- RabbitMQ queue 선언, 메시지 계약, publish/consume, 재시도와 중복 처리
- RAG read-only DB 계정, 검색·원문·claim source Tool, embedding 정책
- 의존성 lock 파일, CI, 운영 비밀 관리와 readiness 정책
- frontend, ai-agent, LangGraph checkpoint는 별도 영역에서 구현
