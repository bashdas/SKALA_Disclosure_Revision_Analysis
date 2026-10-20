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

API와 개발용 RabbitMQ AMQP/Management 포트를 호스트 loopback에 공개합니다. MCP와 PostgreSQL은 Compose 기본 내부 네트워크만 사용합니다. MCP 주소는 `http://business-mcp:8081/mcp`, `http://rag-mcp:8082/mcp`입니다. 향후 AI Agent가 같은 네트워크에 참여해야 합니다.

```bash
docker compose exec business-mcp python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8081/health').read().decode())"
docker compose exec rag-mcp python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8082/health').read().decode())"
docker compose logs -f business-api business-mcp rag-mcp
docker compose down
```

`down`은 이름 있는 DB/큐 볼륨을 보존합니다. pgvector 이미지를 준비했고 core 업무 schema는 Alembic migration으로 관리합니다. pgvector extension 활성화는 아직 없으며 RabbitMQ 큐 선언·Producer 연결은 아래 Analysis 항목을 따릅니다. PostgreSQL 초기 자격 증명은 빈 볼륨을 처음 생성할 때 적용됩니다.

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
- Internal API + Internal API Key 인증, 나머지 업무 API, Business MCP HTTP client와 실제 Tool (분석 생성·조회·이벤트·SSE·취소와 Filing/Memo 조회는 구현됨)
- RabbitMQ Consumer 업무 retry·DLQ 판단·task_id 중복 실행 보호 (queue topology·메시지 계약·Producer는 구현됨)
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

`env.py`가 앱과 동일한 설정으로 URL을 읽고 `app.models`를 import하여 `Base.metadata`에 연결합니다. 새 모델은 `app/models/__init__.py`에서 명시적으로 import해야 합니다. 13개 업무 모델과 `0001_initial_core` → `0002_align_report_flow` → `0003_memo_upload` revision chain이 있습니다. 업무 테이블은 `core` schema에 생성하며 autogenerate는 core만 비교합니다. RAG/checkpoint/public의 다른 테이블은 제외합니다. `create_all`은 사용하지 않습니다. 상세 nullable·unique·삭제 정책과 PostgreSQL 모델/migration 테스트는 [Business API README](business-api/README.md)를 참고하세요.

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

Memo 업로드는 POST /api/v1/memos의 multipart file/title로 제공하며 UTF-8 .txt/text/plain, 기본 5 MiB 한도를 사용합니다. 회사명은 추측하지 않고 NULL로 저장합니다. 적용 전에 Alembic upgrade head가 필요합니다. 상세 정책과 transaction/metadata는 [Business API README](business-api/README.md)를 참고하세요.

## Analysis 생성 및 RabbitMQ Producer

인증된 RA / ANALYST가 자기 조직의 업로드 Memo로 분석을 요청합니다.

```http
POST /api/v1/analyses
Authorization: Bearer <access_token>
Content-Type: application/json

{"memo_id":"<memo UUID>","disclosure_receipt_no":"20261020000123"}
```

응답은 Broker publisher confirm 성공 후 `202 Accepted`이며
`{"task_id":"<task UUID>","status":"QUEUED","created_at":"..."}`를 반환합니다.
접수번호는 14자리 ASCII 숫자 형식만 검증하며, Filing 존재나 OpenDART 유효성을 확인하지 않습니다.
`organization_id`와 `requested_by`는 JWT를 DB User와 검증한 context에서만 가져옵니다.
`Memo.current_version`에 해당하는 원문 버전을 확인하고 `base_memo_version`으로 고정합니다.
회사 코드·회사명은 Agent 조회 전까지 NULL이며 Filing cache와 결합하지 않습니다.

중복 키는 `(organization_id, memo_id, base_memo_version, disclosure_receipt_no)`이고
CREATED / QUEUED / RUNNING / SAVING / SAVE_FAILED는 `409 ANALYSIS_ALREADY_RUNNING`입니다.
응답의 `error.existing_task_id`로 기존 작업을 식별합니다. Terminal 상태는 재실행 가능합니다.
Service는 PostgreSQL 기본 READ COMMITTED에서 조직 범위 Memo를 `SELECT FOR UPDATE`로 잠그고,
현재 버전 읽기·중복 확인·Task 생성·commit을 직렬화합니다. 이 경로를 우회하는 직접 insert까지
차단하는 DB unique 제약은 없습니다. 향후 버전 변경/분석 생성 경로도 같은 Memo 잠금 규약을 따라야 합니다.

### RabbitMQ 연결과 topology

동기 SQLAlchemy/Service에 맞춰 Pika 1.3.x를 사용합니다. 프로세스별 lifespan Producer가 전용
스레드에서 connection/channel을 소유하고 재사용하며, idle 중에도 heartbeat를 처리합니다.
연결은 첫 publish 또는 `/health/rabbitmq`에서 준비하고 실패하면 다음 요청에서 재연결합니다.
Broker 일시 장애가 `/health`, 로그인, Memo 조회를 막지 않습니다. 종료 시 연결을 닫습니다.
`/health/db`와 `/health/rabbitmq`는 각각 독립 확인이며 Broker 장애는 후자에서 503입니다.

기본 topology는 모두 durable이고 direct exchange `analysis.exchange`를 사용합니다.

| Queue | Routing key | 동작 |
| --- | --- | --- |
| analysis.tasks | analysis.run | 정상 작업, reject(requeue=false)는 DLQ로 이동 |
| analysis.tasks.retry | analysis.retry.1 | 5초 TTL 후 main queue로 DLX 전달 |
| analysis.tasks.retry.2 | analysis.retry.2 | 15초 TTL 후 main queue로 DLX 전달 |
| analysis.tasks.retry.3 | analysis.retry.3 | 45초 TTL 후 main queue로 DLX 전달 |
| analysis.tasks.dlq | analysis.dead | 최종 실패 보관 |

TTL/DLX는 [RabbitMQ 기본 기능](https://www.rabbitmq.com/docs/ttl)을 사용하며 plugin이 필요 없습니다.
재시도마다 별도 queue를 사용해 긴 TTL 메시지가 짧은 TTL 메시지를 막지 않도록 합니다.
`RABBITMQ_MAX_RETRIES=3`과 `RABBITMQ_RETRY_DELAY_SECONDS=5`가 위 topology를 결정합니다.
Consumer는 미구현입니다. 향후 Consumer가 실패 시 retry_count를 증가시키고 1~3 단계로
confirmed republish한 뒤 원본을 ack하며, 3회 재시도 이후에는 analysis.dead로 보내야 합니다.
큐 구성만으로 retry_count 증가/최대 횟수 판단을 자동 실행하지 않습니다.
Classic queue의 기본 dead-letter 전달은 장애 중 무손실 전달을 보장하지 않습니다.
기존 큐의 TTL/DLX 설정 변경 시 RabbitMQ 정책 또는 계획된 큐 재구성이 필요합니다.

메시지는 `message_id`(UUID), `task_id`, `type=RUN_ANALYSIS`, `retry_count=0`만 포함합니다.
본문·JWT·조직 데이터는 복제하지 않습니다. AMQP properties에도 message_id/retry_count를 기록합니다.
Persistent 메시지 + mandatory routing + publisher confirm으로 전송 성공을 확인합니다.
같은 publish의 transport retry는 같은 message_id를 재사용합니다.

### 실패와 transaction 경계

Service가 CREATED → QUEUED, stage REQUEST_VALIDATION을 기록하고 DB commit한 뒤 publish합니다.
Producer는 `RABBITMQ_PUBLISH_MAX_ATTEMPTS=3`번 **총 시도**하며, 간격은 0.2/0.4초입니다.
이것은 Consumer의 5/15/45초 업무 retry와 별개입니다. 연결/blocked/RPC/confirm 대기를
`RABBITMQ_PUBLISH_TIMEOUT_SECONDS` 기준으로 제한합니다. transport stack 수립에는 1초 여유를 둡니다.
최종 실패 시 새 transaction에서 Task를 잠가 QUEUED → FAILED로 바꾸고 completed_at을 설정합니다.
`error_stage=REQUEST_VALIDATION`, `error_code=RABBITMQ_PUBLISH_FAILED`와 고정 진단 문구를 저장하고
503을 반환합니다. 연결 URL이나 원본 library exception은 응답/DB 오류 메시지에 포함하지 않습니다.
FAILED는 다음 동일 요청을 차단하지 않습니다.

Outbox는 구현하지 않습니다. DB commit 직후 프로세스가 중단되거나 실패 상태 기록 때 DB까지
불능이면 QUEUED가 남을 수 있습니다. Broker가 수신했으나 confirm만 유실되면 중복 전달될 수 있으므로
향후 Worker는 task_id 기준 중복 실행 보호가 필요합니다. 이미 Worker가 진행시킨 Task를
publish 실패 정리에서 FAILED로 덮어쓰지 않으며, 이 경우에도 요청은 503을 반환합니다.
이 구조는 DB/Broker 간 원자성이나 exactly-once를 보장하지 않습니다.

### 실행 및 검증

`.env.example`을 참고해 로컬 `.env`를 설정하고 기존 DB에는 먼저 migration을 적용합니다.

```bash
docker compose up -d --build postgres rabbitmq business-api
docker compose exec business-api alembic upgrade head
curl http://localhost:8080/health
curl http://localhost:8080/health/rabbitmq
```

RabbitMQ AMQP 5672와 Management UI `http://localhost:15672`는 기본 loopback에만 노출됩니다.
포트는 RABBITMQ_AMQP_PORT / RABBITMQ_MANAGEMENT_PORT로 변경합니다. 개발 계정은 로컬에서 교체합니다.
Business API 컨테이너의 RABBITMQ_URL host는 `rabbitmq`를 사용합니다.
0004_analysis_company는 AnalysisTask.company_name_snapshot을 nullable로 변경합니다.
NULL이 남아 있으면 downgrade를 명시적으로 차단하며 회사명을 임의로 채우지 않습니다.

```bash
# business-api 디렉터리, 폐기 가능한 별도 테스트 DB/Broker만 지정
TEST_DATABASE_URL='<test PostgreSQL URL>' TEST_ALLOW_SCHEMA_RESET=1 \
TEST_RABBITMQ_URL='<test AMQP URL>' python -m pytest -q
```

실제 RabbitMQ integration probe는 고유 이름의 exchange/queue를 만들고 정리합니다.
Consumer 서비스는 아직 구현하지 않았습니다. 분석 조회/SSE/취소는 다음 절을 따릅니다.


## Analysis 조회·Event·SSE·취소

모든 endpoint는 Authorization Bearer 인증과 RA / ANALYST 권한이 필요합니다.
Task ID는 항상 DB User에서 확인한 current_user.organization_id로 제한합니다.
다른 조직의 Task와 없는 Task는 동일한 404 ANALYSIS_NOT_FOUND입니다.

| Endpoint | 동작 |
| --- | --- |
| GET /api/v1/analyses/{task_id} | 상태·단계·기준 Memo 버전·접수번호·시각·회사 snapshot |
| GET /api/v1/analyses/{task_id}/events | sequence ASC 이벤트 조회 |
| GET /api/v1/analyses/{task_id}/events/stream | 영속 이벤트 기반 SSE |
| POST /api/v1/analyses/{task_id}/cancel | 요청자 본인의 협력적 취소 |

상세 응답은 error_stage/error_code를 포함하지만 내부 error_message, thread_id,
organization_id, requested_by는 노출하지 않습니다. 회사 식별값은 조회 전 NULL입니다.
이벤트 응답은 sequence/event_type/payload/created_at이며 목록은 after_sequence(기본 0)와
limit(기본 200, 최대 500)을 지원합니다. sequence > after_sequence 조건을 사용합니다.

### 영속 Event와 transaction

AnalysisEventType은 queued/started, 입력 조회, RAG, 기본 분석, Perspective 선택·실행·실패,
보고서 생성·저장·실패, warning/failed/cancelled/completed 이벤트 이름을 정의합니다.
Agent 이벤트 수신 API는 이번 단계에서 만들지 않았습니다.

AnalysisEventService.append_event는 조직 범위 Task를 SELECT FOR UPDATE로 잠근 뒤
latest sequence + 1을 할당하고 INSERT/commit합니다. 따라서 같은 Task의 동시 append를
직렬화하며, 기존 UNIQUE(analysis_task_id, sequence)도 유지합니다. 다른 Task는 독립적으로
1부터 시작합니다. 별도 sequence 컬럼이나 migration은 추가하지 않았습니다.
모든 event writer는 같은 Task 잠금 규약을 따라야 합니다. Repository는 sequence를 할당하거나
commit하지 않습니다. 이 정책은 PostgreSQL 기본 READ COMMITTED를 전제로 합니다.

append_in_transaction은 상위 Service의 transaction에 합성하는 용도이며 commit하지 않습니다.
기존 Task 변경과 합칠 때는 먼저 해당 Task를 잠가 최신 상태를 확인하고, 변경을 flush한 뒤
append해야 합니다. 해당 조회가 populate_existing으로 ORM 객체를 갱신하기 때문입니다.

Task 생성과 ANALYSIS_QUEUED(sequence 1)를 같은 transaction에서 commit한 뒤 Broker에
publish합니다. 이 이벤트는 DB의 QUEUED 전이를 뜻하며, Broker 수신 확인 자체를 뜻하지 않습니다.
202는 기존대로 publisher confirm 이후에만 반환합니다. publish 최종 실패로 Task를 FAILED로
바꿀 때 ANALYSIS_FAILED도 같은 transaction에 저장합니다. 이미 Worker가 진행한 Task는
이전 정책대로 실패 처리로 덮어쓰지 않습니다.
취소와 ANALYSIS_CANCELLED도 한 transaction입니다. 이 세 workflow는 이벤트 저장/commit
실패 시 상태 변경도 rollback합니다. DB 장애 때의 정체 Task 복구는 기존 Outbox 미사용 한계로 남습니다.

payload는 status/stage/code/message/perspective/reason의 명시적인 요약 필드만 허용합니다.
code 100자, message 500자, reason 1000자 한도이며 임의 nested 데이터, memo_content,
password, JWT/API key 같은 필드는 거부합니다. 자유 텍스트 안의 credential을 자동 탐지하는
기능은 없으므로 호출자도 반드시 안전한 요약만 전달해야 합니다. 원문·secret은 기록하지 않습니다.

### SSE 재연결과 Session

```bash
# TOKEN에는 로컬 로그인에서 발급받은 Access Token을 설정합니다.
curl -N -H "Authorization: Bearer $TOKEN" \
  -H "Last-Event-ID: 15" \
  "http://localhost:8080/api/v1/analyses/$TASK_ID/events/stream"
```

응답 Content-Type은 text/event-stream이며 각 frame은 다음 구조입니다.

```text
id: 16
event: BASE_ANALYSIS_COMPLETED
data: {"sequence":16,"event_type":"BASE_ANALYSIS_COMPLETED","payload":{},"created_at":"..."}

```

명시적 after_sequence가 Last-Event-ID보다 우선합니다. after_sequence=0도 명시적 우선값입니다.
헤더는 0~2147483647의 ASCII 숫자를 허용하고 잘못된 값은 400 INVALID_LAST_EVENT_ID입니다.
Query는 0~2147483647로 검증합니다. after_sequence 이외 query는 400 INVALID_STREAM_QUERY로
거부하며, URL token 인증을 지원하지 않습니다. 인증이 없으면 query token이 있어도 401입니다.
브라우저에서는 Authorization 헤더를 보낼 수 있는 fetch streaming/fetch-event-source 방식을 사용합니다.
프레임 형식 참고: [WHATWG SSE](https://html.spec.whatwg.org/dev/server-sent-events.html).

SSE 인증은 짧은 별도 Session에서 기존 DB-backed current_user 검증을 재사용합니다.
일반 request-scoped get_db 의존성을 사용하지 않습니다. 최초 scope 검사와 각 polling도
별도 Session에서 DTO를 만든 뒤 닫습니다. sync DB 작업은 thread pool에서 실행하며,
전송/heartbeat/sleep 중에는 Session/transaction을 보유하지 않습니다.

기본 SSE_POLL_INTERVAL_SECONDS=1, SSE_HEARTBEAT_SECONDS=15입니다. 새 이벤트가 없으면
heartbeat 주기에 `: heartbeat` comment를 전송합니다. heartbeat는 polling 주기 단위로
확인하므로 poll interval을 heartbeat보다 길게 설정하지 않는 것을 권장합니다.
backlog는 200개씩 읽으며 full batch 뒤에는 대기 없이 다음 batch를 읽습니다.
Cache-Control: no-cache, no-store 및 X-Accel-Buffering: no를 설정합니다.
배포 proxy의 buffering/idle timeout도 별도로 맞춰야 합니다.

COMPLETED / COMPLETED_WITH_WARNINGS / FAILED / CANCELLED이면 남은 이벤트를 전송하고 종료합니다.
SAVE_FAILED는 terminal이 아니므로 연결을 유지합니다. disconnect 시 loop를 종료합니다.
스트리밍 도중 DB 장애/리소스 소멸 시 민감한 예외 대신 SSE comment 후 연결을 종료합니다.
클라이언트는 마지막으로 받은 sequence에서 재연결할 수 있습니다. terminal 상태 변경과 마지막
이벤트는 같은 transaction에서 저장해야 하며, terminal 이후의 추가 기록은 이미 끝난 stream에
자동 전달되지 않습니다. 별도 Redis/Consumer/Agent/Event 수신 API는 구현하지 않았습니다.

### 협력적 취소

취소는 조직 범위를 확인한 뒤 requested_by == current_user.id인 경우에만 허용합니다.
같은 조직의 다른 사용자는 403 ANALYSIS_CANCEL_FORBIDDEN입니다. Task 행 잠금으로 최신 상태를
다시 읽고 기존 상태 머신으로 CANCELLED 전이를 검증합니다. COMPLETED /
COMPLETED_WITH_WARNINGS / FAILED는 409 ANALYSIS_CANNOT_BE_CANCELLED입니다.

이미 CANCELLED인 경우에도 먼저 조직·요청자 권한을 검증하고 200을 반환합니다.
completed_at을 바꾸거나 ANALYSIS_CANCELLED를 중복 추가하지 않습니다. 응답은
`{"task_id":"...","status":"CANCELLED"}`입니다.

RabbitMQ 메시지를 삭제하거나 Worker를 kill하지 않습니다. 향후 Consumer는 실행 전 Task 상태를
조회하여 CANCELLED이면 실행하지 않고 ack해야 합니다. 실행 중 Agent도 주요 subgraph/Perspective/
외부 tool 반복/보고서 생성 전에 취소를 확인해야 합니다. Worker의 상태 변경 역시 같은 Task 행 잠금과
최신 상태 검증을 따라야 취소를 stale ORM 객체로 덮어쓰지 않습니다. 이 Worker 계약은 문서화만 했고
Consumer/Internal API/Agent는 아직 구현하지 않았습니다.

다음 구현 범위는 Internal API + X-Internal-API-Key 인증입니다.
