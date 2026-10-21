# 공시체크 (DisclosureCheck)

AI, Frontend, Backend의 설치, 환경 설정, 실행 및 연동 방법을 안내합니다. 실행 순서와 터미널별 명령은 [6.1 실행 방법](#61-실행-방법-backend--ai--frontend)에 정리되어 있습니다.

## 목차

1. [프로젝트 소개](#1-프로젝트-소개)
2. [전체 구성 및 연결 구조](#2-전체-구성-및-연결-구조)
3. [실행 전 준비 사항](#3-실행-전-준비-사항)
4. [환경 변수 설정](#4-환경-변수-설정)
5. [각 서비스 설치 및 실행 방법](#5-각-서비스-설치-및-실행-방법)
6. [전체 연동 및 실행 순서](#6-전체-연동-및-실행-순서)
7. [연동 테스트](#7-연동-테스트)
8. [자주 발생하는 오류와 해결 방법](#8-자주-발생하는-오류와-해결-방법)

## 1. 프로젝트 소개

공시체크는 증권사 RA가 공시 이벤트 이후 기존 기업분석 메모의 문장, 수치, 가정을 재검토하도록 돕는 서비스입니다. AI가 공시와 고정된 메모 버전을 비교하고, 필요한 관점의 추가 분석을 거쳐 근거, 미확인 사항, 수정 제안을 담은 보고서를 생성합니다.

### 주요 기능

- 공시, 메모 원문 및 기준 버전 조회
- 기본 변경영향 분석과 필요한 전문 관점 선택
- 근거 검색 및 출처를 포함한 보고서 생성
- 분석 작업 대기열, 진행 이벤트, 보고서 저장

### 서비스별 역할

| 서비스 | 역할 | 주요 기술 |
| --- | --- | --- |
| AI | 큐 작업 수신, 기본, 전문 분석, 보고서 생성, 체크포인트 보존 | Python, LangGraph, OpenAI, SQLite |
| Frontend | 공시, 메모 선택, 분석 진행 및 보고서 화면 | Vue 3, TypeScript, Vite, Pinia |
| Backend | 인증, 업무 데이터, 분석 접수, 진행, 저장, MCP 제공 | FastAPI, SQLAlchemy, PostgreSQL, RabbitMQ, MCP |

> Frontend는 실제 API를 사용합니다. 기업 목록에서 즐겨찾기를 추가하면 내 페이지에 기업이 표시됩니다. 기업 상세의 정정공시와 기준 메모를 선택해 분석합니다.

## 2. 전체 구성 및 연결 구조

### 2.1 프로젝트 구조

```text
SKALA_Disclosure_Revision_Analysis-main/
├── README.md                     # 이 문서
├── ai/
│   ├── disclosure_ai/            # LangGraph, Harness, Worker, 선택적 API
│   ├── tests/
│   ├── .env.example
│   └── pyproject.toml
├── backend/
│   ├── business-api/            # 인증, 공시, 메모, 분석, 이벤트 API
│   ├── mcp/
│   │   ├── business-mcp/        # 업무 조회, 진행 상태, 보고서 저장
│   │   ├── external-mcp/        # OpenDART 공시 원문 조회
│   │   └── rag-mcp/             # 메모, 공시 색인 및 근거 검색
│   ├── shared/
│   ├── .env.example
│   └── docker-compose.yml
├── frontend/
│   ├── src/services/            # 실제 HTTP API 연결
│   ├── src/views/
│   ├── package.json
│   └── vite.config.ts
└── docs/                       # 팀 작업 기록
```

### 2.2 요청 및 응답 흐름

```mermaid
flowchart TD
    UI[Frontend]
    API[Business API :8080]
    Q[RabbitMQ :5672]
    AI[AI Worker: ai/]
    B[Business MCP :8081/mcp]
    E[External MCP :8083/mcp]
    R[RAG MCP :8082/mcp]
    DB[(PostgreSQL + pgvector)]
    D[OpenDART]
    O[OpenAI]
    UI -->|Bearer 인증| API
    API -->|분석 작업 발행| Q
    Q -->|작업 ID 전달| AI
    AI -->|입력 조회, 진행 기록, 결과 저장| B
    B -->|내부 API + 내부 인증키| API
    API --> DB
    AI --> E
    E --> D
    AI --> R
    R --> B
    R --> E
    R --> DB
    R -->|임베딩| O
    AI -->|분석, 보고서 생성| O
    API -->|분석 상태와 보고서 조회| UI
```

작업 접수 → 공시, 메모 수집 → RAG 준비 → 기본 분석 → 필요한 관점 실행 → 보고서 생성 → 업무 DB 저장 순서입니다. AI Worker는 HTTP 서버가 아니므로 기본 실행에 별도 접속 포트가 없습니다.

### 2.3 서비스별 주소와 포트

Frontend는 `http://127.0.0.1:5173`, Business API는 `http://127.0.0.1:8080`에서 실행합니다. RabbitMQ 관리 화면은 `http://127.0.0.1:15672`입니다. AI Worker와 MCP, PostgreSQL은 같은 Docker 네트워크에서 통신합니다.

Business MCP는 `http://business-mcp:8081/mcp`, RAG MCP는 `http://rag-mcp:8082/mcp`, External MCP는 `http://external-mcp:8083/mcp`입니다. 이 주소와 DB의 `postgres:5432`는 Docker 내부 주소입니다. Worker에는 웹 접속 포트가 없습니다.

## 3. 실행 전 준비 사항

| 준비 항목 | 기준 |
| --- | --- |
| 운영 환경 | 아래 명령은 macOS/Linux의 zsh/bash 기준. AI가 `fcntl`을 사용하므로 Windows는 WSL2/Linux 환경 사용 |
| Python | 3.12 이상. 아래 예시는 `python3.12` 명령 사용 |
| Node.js | 22.18 이상인 22 계열 또는 24.12 이상 |
| npm | Node.js와 함께 설치 |
| Docker | Docker 엔진과 Compose. Docker Desktop 또는 사용 중인 Docker 환경을 먼저 시작 |
| OpenAI API 키 | AI 분석과 Backend RAG 임베딩에 각각 설정 |
| OpenDART API 키 | Backend External MCP에 설정 |
| 테스트 자료 | UTF-8 `.txt` 메모와 실제 공시 접수번호 14자리 |

```bash
python3.12 --version
node --version
npm --version
docker --version
docker compose version
```

아래 명령은 `ai/`, `backend/`, `frontend/`가 있는 프로젝트 루트를 기준으로 합니다. 저장소를 내려받은 위치에서 프로젝트 폴더로 이동합니다.

```bash
cd SKALA_Disclosure_Revision_Analysis-main
```

`.env.example`은 예시이며 실제 키가 아닙니다. 각 `.env`를 직접 작성해야 합니다. API 키, 인증키, 상태 DB는 공유하거나 커밋하지 않습니다. Frontend의 `VITE_*` 값은 브라우저에 포함되므로 비밀키를 넣으면 안 됩니다.

## 4. 환경 변수 설정

### 4.1 설정 파일과 연결 지점

| 변경 파일 | 설정할 항목 | 연결 대상 |
| --- | --- | --- |
| `backend/.env` | DB, RabbitMQ URL, JWT, 내부 인증키, OpenDART, OpenAI 키 | Backend → DB, 큐, 외부 API |
| `backend/.env`의 AI 설정 | OPENAI_MODEL과 OPENAI_API_KEY | Docker Worker와 모델 API |
| `frontend/vite.config.ts` | `/api` 개발 프록시 | Frontend → Backend `:8080` |
| `frontend/src/services/index.ts` | 실제 HTTP 서비스 선택 | 화면 → HTTP adapter |
| `frontend/src/services/http.ts` | API 경로, Bearer 헤더, 응답 변환 | Frontend → `/api/v1/...` |

Backend → AI는 HTTP 주소 대신 RabbitMQ 작업 큐로 연결합니다. 양쪽의 계정, 교환기, 큐 이름을 맞추고, AI → Backend의 업무 조회와 저장에는 Business MCP 주소를 사용합니다.

### 4.2 Backend: `backend/.env`

**실행 위치: `backend/`. 새 터미널을 열고 프로젝트 루트에서 시작합니다.**

```bash
cd backend
cp .env.example .env
```

처음 설정할 때만 복사합니다. 기존 `.env`가 있다면 보존하세요. `backend/.env`에서 다음 값을 수정합니다.

| 변수 | 설정 내용 |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_DB` | 기본 예시 값 `disclosure` 사용 가능 |
| `POSTGRES_PASSWORD` | 로컬 DB 비밀번호 |
| `DATABASE_URL` | `postgresql+psycopg://disclosure:DB비밀번호@postgres:5432/disclosure` |
| `RABBITMQ_DEFAULT_USER` | 예: `disclosure` |
| `RABBITMQ_DEFAULT_PASS` | 로컬 큐 비밀번호 |
| `RABBITMQ_URL` | `amqp://disclosure:큐비밀번호@rabbitmq:5672/` |
| `JWT_SECRET_KEY` | 무작위 문자열, 최소 32바이트. `change-me`로는 로그인 불가 |
| `INTERNAL_API_KEY` | 무작위 문자열, 최소 32바이트. Business API와 Business MCP가 같은 값 사용 |
| `OPENDART_API_KEY` | 실제 OpenDART 키 |
| `OPENAI_API_KEY` | RAG 임베딩용 실제 OpenAI 키 |

비밀번호에 URL 특수문자가 있으면 접속 URL 안의 비밀번호를 URL 인코딩합니다. 처음에는 영문, 숫자로 만든 임의 비밀번호를 사용하면 설정이 간단합니다. DB/큐 비밀번호와 URL 안의 비밀번호는 반드시 일치해야 합니다.

다음 명령은 JWT용과 내부 통신용 임의 값을 각각 생성하는 예시입니다. 출력된 값을 로컬 `.env`에 넣습니다.

```bash
python3.12 -c 'import secrets; print(secrets.token_hex(32))'
python3.12 -c 'import secrets; print(secrets.token_hex(32))'
```

`RABBITMQ_EXCHANGE=analysis.exchange`, `RABBITMQ_ANALYSIS_QUEUE=analysis.tasks`, `RABBITMQ_MAX_RETRIES=3`은 기본값으로 유지합니다. 포트도 8080~8083, 5672, 15672 기본값을 기준으로 합니다.

### 4.3 AI 설정

Compose의 `ai-worker`는 `backend/.env`의 OpenAI 키와 RabbitMQ 설정을 사용합니다. 모델 기본값은 `gpt-5.4-mini`이며 `OPENAI_MODEL`로 변경할 수 있습니다. RAG 임베딩 기본값은 `text-embedding-3-small`입니다.

Worker의 상태와 체크포인트는 Docker의 `ai-state` 볼륨에 저장합니다. 토큰 계산용 캐시는 같은 볼륨의 `/state/cache`에 둡니다. 별도 호스트 실행 방법은 [AI README](ai/README.md)를 따릅니다.

### 4.4 Frontend와 Backend 연결

Vite는 `/api` 요청을 `http://127.0.0.1:8080`으로 전달합니다. 서버가 다른 주소에 있으면 Frontend 실행 환경변수 `API_PROXY_TARGET`을 지정합니다. 브라우저에는 OpenDART 키나 내부 API 키를 전달하지 않습니다.

정적 빌드 배포에는 같은 `/api` reverse proxy와 SPA fallback이 필요합니다. 개발용 프록시는 빌드 결과에 포함되지 않습니다.

## 5. 각 서비스 설치 및 실행 방법

Backend 인프라를 먼저 준비하고 AI Worker와 Frontend를 실행합니다. 각 명령의 시작 폴더를 확인하세요.

### 5.1 Backend Compose 준비

`backend/.env`를 설정한 뒤 `backend/`에서 실행합니다. 기존 `.env`는 보존합니다.

```bash
docker compose -p disclosure-web config --quiet
docker compose -p disclosure-web build
```

MCP는 Docker 내부 네트워크에서만 접근합니다. 별도 Compose 파일을 생성할 필요가 없습니다.

### 5.2 Backend: 의존성 설치, DB 초기화, 실행

**실행 위치: 계속 `backend/`.**

```bash
docker compose -p disclosure-web build
docker compose -p disclosure-web up -d postgres rabbitmq
docker compose -p disclosure-web ps
```

PostgreSQL과 RabbitMQ가 `healthy` 상태가 될 때까지 기다립니다. 이후 **업무 DB와 RAG DB를 각각** 초기화합니다. 컨테이너 기동만으로 테이블이 자동 생성되지는 않습니다.

```bash
docker compose -p disclosure-web run --rm --no-deps business-api alembic upgrade head
docker compose -p disclosure-web run --rm --no-deps rag-mcp alembic upgrade head
docker compose -p disclosure-web up -d
docker compose -p disclosure-web ps
```

업무 migration은 `0006_disclosure_watch`, RAG migration은 별도 이력의 `0001_rag_index`까지 적용합니다. RAG migration에는 pgvector 확장 생성 권한이 필요하며, 예시 Compose의 최초 DB 사용자는 이 로컬 초기화에 사용됩니다.

### 5.3 Backend: 정상 실행 확인

```bash
curl -f http://127.0.0.1:8080/health
curl -f http://127.0.0.1:8080/health/db
curl -f http://127.0.0.1:8080/health/rabbitmq
```

`/health`는 프로세스 생존 확인입니다. DB와 큐는 `/health/db`, `/health/rabbitmq`도 성공해야 합니다. MCP의 `/health` 성공만으로 OpenDART, 임베딩 호출까지 검증되지는 않습니다. `/mcp`는 MCP 프로토콜 주소이므로 일반 브라우저 GET으로 점검하지 않습니다.

- API 명세와 수동 요청: `http://127.0.0.1:8080/docs`
- RabbitMQ 관리: `http://127.0.0.1:15672`, `.env`의 RabbitMQ 계정으로 로그인

### 5.4 최초 계정 생성

웹 로그인 화면의 회원가입 버튼을 사용합니다. 조직 이름, 이메일과 12자 이상 비밀번호로 새 조직과 RA 사용자를 생성합니다. 기존 조직에 가입하는 기능은 포함하지 않습니다. 동일 이메일이 있으면 기존 계정으로 로그인합니다.

### 5.5 AI Worker 실행

Backend와 migration 준비 후 큐를 초기화하고 Worker를 시작합니다.

```bash
curl -f http://127.0.0.1:8080/health/rabbitmq
docker compose -p disclosure-web up -d ai-worker
docker compose -p disclosure-web logs --tail=30 ai-worker
```

Worker는 `analysis.tasks`에서 작업을 받고 메모 버전과 접수번호를 고정합니다. 실패 시 큐 재시도와 최종 실패 보관을 사용합니다. 저장 재시도와 단독 실행은 [AI README](ai/README.md)를 확인합니다. 동일 상태 파일을 사용하는 Worker를 중복 실행하지 않습니다.

### 5.8 Frontend: 설치, 실행, 정상 확인

**실행 위치: `frontend/`. 실제 로그인과 업무 조회에는 Backend가 필요합니다.**

프로젝트 루트에서:

```bash
cd frontend
npm ci
npm run dev
```

브라우저에서 `http://127.0.0.1:5173`에 접속합니다. 포트가 고정되어 있어 5173번을 다른 프로그램이 사용하면 실행이 실패합니다.

빌드 및 확인:

```bash
npm run typecheck
npm test
npm run build
npm run preview
```

`preview`의 실제 접속 주소는 터미널 출력을 확인합니다. `dist/`가 빌드 결과입니다. 정적 배포 시 `/companies/...`, `/analyses/...` 요청도 `index.html`로 보내는 SPA fallback이 필요합니다.

## 6. 전체 연동 및 실행 순서

### 6.1 실행 방법: Backend → AI → Frontend

터미널 1의 `backend/`에서 최초 실행합니다.

```bash
docker compose -p disclosure-web build
docker compose -p disclosure-web up -d --wait postgres rabbitmq
docker compose -p disclosure-web run --rm --no-deps business-api alembic upgrade head
docker compose -p disclosure-web run --rm --no-deps rag-mcp alembic upgrade head
docker compose -p disclosure-web up -d --wait business-api business-mcp external-mcp rag-mcp
curl -f http://127.0.0.1:8080/health/db
curl -f http://127.0.0.1:8080/health/rabbitmq
docker compose -p disclosure-web up -d ai-worker
```

터미널 2의 `frontend/`에서 `npm ci`, `npm run dev`를 실행합니다. 기존 환경은 migration 적용 여부를 확인한 뒤 `docker compose -p disclosure-web up -d`로 시작합니다.

### 6.2 화면과 API 계약

기업 목록은 OpenDART 회사 목록을 20건씩 조회하며 검색과 무한스크롤을 지원합니다. 별표는 사용자별 즐겨찾기를 서버에 저장합니다. 내 페이지에서 기업을 선택하면 기업 상세의 기존 공시 탭을 엽니다.

공시 탭은 회사와 기간으로 목록을 조회하며 정정공시를 함께 표시합니다. 정정공시 선택 시 원문을 서버에 등록하고 오른쪽 분석 패널에 선택합니다. 신규 공시는 분석 버튼을 비활성화하며 서버도 등록 여부와 정정 여부를 검사합니다.

메모 관리에서 파일을 업로드하거나 작성 버튼으로 본문을 입력하고 저장합니다. 분석은 `memo_id`, `memo_version`, `disclosure_receipt_no`를 보내며 조직 범위와 버전을 서버가 확인합니다. 관점은 `INDUSTRY_CONTRACT`, `FINANCE`, `FX_HEDGE`를 사용합니다.

화면은 2초마다 분석 진행을 조회합니다. 분석 이력과 보고서는 사용자 인증을 적용한 `/api/v1/analyses`, `/{id}/report`, `/{id}/perspectives`로 읽습니다. 기업의 공시 목록은 화면이 열려 있으면 1분마다 갱신합니다.

### 6.3 종료

Frontend 터미널에서 `Ctrl+C`를 누르고 `backend/`에서 실행합니다.

```bash
docker compose -p disclosure-web down
```

DB, 큐와 AI 상태 볼륨은 보존합니다. 일반 종료에는 `down -v`를 사용하지 않습니다.

## 7. 연동 테스트

### 7.1 화면 기능 확인

회원가입과 로그인 후 기업 목록에서 기업을 검색합니다. 즐겨찾기한 기업이 내 페이지에 표시되는지 확인하고 기업 상세로 이동합니다. 신규 공시의 분석 버튼은 비활성 상태여야 합니다.

메모 관리에서 업로드와 직접 작성을 확인하고 저장 후 새로고침하여 같은 본문을 읽습니다. 정정공시를 선택해 분석을 시작하고 실제 작업 ID, 진행 상태와 서버에 저장된 보고서를 확인합니다. 계정과 조직이 다른 자료에는 접근할 수 없어야 합니다.

자동 검증 명령과 실제 서버 검사 환경변수는 [Frontend README](frontend/README.md)에 있습니다. 원문과 메모는 브라우저 저장소에 보관하지 않습니다.

### 7.2 실제 연동: 로그인과 토큰 준비

`http://127.0.0.1:8080/docs`에서 `POST /api/v1/auth/login`을 실행합니다.

```json
{
  "email": "ra.local@example.com",
  "password": "5.4절에서_직접_입력한_비밀번호"
}
```

응답의 `access_token`을 아래 터미널 변수에 넣습니다. 예시 문자열을 그대로 사용하지 않습니다. 후속 명령은 **새 터미널의 동일한 셸**에서 실행합니다.

```bash
export ACCESS_TOKEN='로그인_응답의_access_token'
```

### 7.3 실제 연동: 메모 업로드

기업, 작성일, 기존 가정이 포함된 테스트 메모를 UTF-8 `.txt`로 준비합니다. 최대 크기는 기본 5 MiB이며 PDF, DOCX는 현재 업로드 대상이 아닙니다.

```bash
curl -fS -X POST http://127.0.0.1:8080/api/v1/memos \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F 'file=@/실제/경로/memo.txt;type=text/plain' \
  -F 'title=공시 분석 연동 테스트'
```

응답의 `id`가 실제 `memo_id`입니다. 제목이나 Frontend 샘플의 `lnf`, `shi` 같은 ID를 보내면 안 됩니다. 실제 업로드 API는 `file`, 선택 `title`을 받으며 기업 ID를 받지 않습니다. `company_name`이 `null`일 수 있습니다.

```bash
export MEMO_ID='업로드_응답의_id_UUID'
export RECEIPT_NO='원문_제공이_확인된_실제_14자리_접수번호'
```

### 7.4 실제 연동: 분석 요청과 진행 확인

```bash
curl -fS -X POST http://127.0.0.1:8080/api/v1/analyses \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"memo_id\":\"$MEMO_ID\",\"disclosure_receipt_no\":\"$RECEIPT_NO\"}"
```

정상 접수 시 HTTP `202`, `task_id`, `status: QUEUED`를 반환합니다. `202`는 큐 발행 성공이며 분석 완료를 뜻하지 않습니다. 분석 전에 POST /api/v1/filings로 해당 정정공시를 등록해야 합니다. 같은 조직에 등록된 정정공시만 분석할 수 있습니다.

```bash
export TASK_ID='분석_응답의_task_id_UUID'

curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/events" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl -N "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/events/stream" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

SSE 조회는 계속 열려 있을 수 있으며 `Ctrl+C`로 종료합니다. 정상 경로는 `QUEUED → RUNNING → SAVING → COMPLETED` 또는 `COMPLETED_WITH_WARNINGS`입니다. 조회 제한, 미구현 도구, 근거 부족 등으로 경고나 실패가 발생할 수 있으므로 상태와 이벤트를 함께 확인합니다.

### 7.5 실제 연동: 보고서 저장 확인

인증한 사용자는 다음 API로 보고서를 읽습니다.

```bash
curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/report" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

보고서 생성 전에는 null을 반환합니다. 저장 후에는 `content`, `report_json`, `saved_at`을 확인합니다. 웹에서 같은 작업을 새로고침하여 보고서를 다시 읽습니다. 기존 메모는 변경되지 않습니다.

```bash
docker compose -p disclosure-web logs --tail=50 business-api business-mcp external-mcp rag-mcp ai-worker
```

### 7.6 정상 결과 예시

실제 요청이 정상 접수되면 다음 형태로 응답합니다. UUID와 시각은 작업마다 달라집니다.

```json
{
  "task_id": "b4c6c01c-082a-4e7f-8a89-df6d27ef2e8d",
  "status": "QUEUED",
  "created_at": "2026-10-21T00:00:00Z"
}
```

연동 확인 기준은 같은 `task_id`에 대해 다음 결과가 이어지는 것입니다.

1. Frontend 또는 API 요청이 `202`를 반환합니다.
2. RabbitMQ 작업을 AI Consumer가 수신합니다.
3. 상태가 `RUNNING`으로 변경되고 입력 조회, 분석, 저장 이벤트가 기록됩니다.
4. `COMPLETED` 또는 `COMPLETED_WITH_WARNINGS`로 종료됩니다.
5. `core.analysis_reports`에 보고서와 `saved_at`이 저장됩니다.
6. 웹 API 연결 후에는 같은 서버 보고서가 화면에 표시됩니다.

`COMPLETED_WITH_WARNINGS`이면 미구현 도구, 근거 부족 등 경고 내용을 함께 확인합니다. 샘플 화면만 실행한 결과는 실제 연동 완료에 포함하지 않습니다.

### 7.7 검증 범위와 제한

실제 서버 검사에서는 회원가입, 로그인, 기업 목록의 검색과 페이지 추가, 즐겨찾기 저장, 메모 저장과 새로고침, 정정공시 분석 접수 및 저장 보고서 재조회를 확인합니다. 신규 공시 거부와 조직별 접근 범위는 API 테스트로 확인합니다.

모델 보고서의 경고는 함께 확인해야 합니다. 근거 부족 시 수정 제안을 제외할 수 있습니다. 저장 재시도는 Worker의 보존 상태에서 처리하며 공개 웹 재시도 버튼은 제공하지 않습니다. 시장 지표와 주가는 현재 API가 없어 미제공으로 표시합니다.

### 7.8 서비스별 검증 명령

Frontend 폴더:

```bash
npm run typecheck
npm test
npm run build
```

AI 폴더의 의존성 설치 후:

```bash
.venv/bin/python -m pytest -q
```

Backend Python 서비스는 모두 `app` 패키지명을 사용하므로 로컬 테스트 시 서비스마다 별도 가상환경을 사용합니다. 예를 들어 프로젝트 루트에서 Business API 테스트를 준비하려면:

```bash
cd backend/business-api
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ../shared -e '.[dev]'
.venv/bin/python -m pytest -q
```

외부 DB/Broker 통합 테스트는 별도의 폐기 가능한 테스트 환경이 필요합니다. 일반 개발 DB에 테스트용 초기화, migration 왕복 검증을 실행하지 않습니다. UI 테스트 통과와 실제 모델, MCP, 웹 전체 E2E 통과는 서로 다른 검증입니다.

## 8. 자주 발생하는 오류와 해결 방법

| 증상 | 확인 및 해결 |
| --- | --- |
| Docker 연결 실패 | Docker 엔진이 실행 중인지 확인 |
| 5173/8080/8081~8083/5672 포트 충돌 | 해당 포트 사용 프로그램을 종료하거나 관련 호스트 포트, 접속 URL을 함께 변경 |
| `.env`를 작성했는데 AI 키가 없음 | Compose Worker는 backend/.env를 사용. 키 변경 후 Worker를 다시 생성 |
| `MCP_UNAVAILABLE` | Docker 내부 MCP 주소와 health, 컨테이너 로그 확인 |
| `QUEUED`에서 진행되지 않음 | Worker 기동 여부와 큐 Consumer 수 확인. 양쪽 RabbitMQ URL, 계정, 교환기, 큐 일치 확인 |
| `BROKER_RECONNECT` 반복 | RabbitMQ health, 호스트 포트, AI의 비밀번호 및 URL 호스트 확인 |
| 로그인 실패/인증 설정 오류 | 실제 계정 존재, 비밀번호와 JWT 키 확인. 첫 이용 시 웹 회원가입 |
| 내부 인증 오류 | Business API와 Business MCP의 `INTERNAL_API_KEY` 일치 및 컨테이너 재생성 여부 확인 |
| DB 테이블, `rag`, vector 오류 | Business API와 RAG migration을 각각 적용했는지 확인. DB 확장 생성 권한 확인 |
| DB/큐 비밀번호를 바꿨는데 인증 실패 | 기존 볼륨은 최초 자격 증명을 유지할 수 있음. 기존 서비스 계정과 `.env`를 맞추거나 서비스의 계정 변경 절차 사용 |
| OpenDART 원문 조회 실패 | 실제 키, 접수번호, 원문 제공 여부 확인. `014`는 해당 공시 원문이 제공되지 않는 경우를 확인 |
| `TOOL_NOT_AVAILABLE` / 일부 분석 미완료 | 추가 조회 도구의 가용성과 설정을 확인하고 확보한 근거와 보고서 경고를 확인 |
| `409 ANALYSIS_ALREADY_RUNNING` | 같은 메모 버전, 접수번호에 진행 작업이 있음. 응답의 `existing_task_id`로 기존 작업 조회 |
| SSE가 브라우저에서 인증 실패 | JWT 헤더를 지원하는 스트림 구현 사용. 토큰을 URL에 넣지 않음 |
| CORS/화면에서 API 호출 실패 | 4.4의 개발 프록시와 adapter의 `/api` 상대경로 확인 |
| `SAVE_FAILED` | 같은 AI 상태 파일의 보고서 보존 확인 후 단일 작업 재저장. 공개 웹 재시도 API는 별도 구현 필요 |
| SQLite 잠금 오류 | 같은 상태 파일을 사용하는 Worker, 선택적 API의 중복 실행 종료 |
| 업로드 415/413/422 | UTF-8 `.txt`, `text/plain`, 기본 5 MiB 한도, multipart의 `file` 필드 확인 |
| 모델 호출 실패 | `OPENAI_API_KEY` 로드 여부, `OPENAI_MODEL` 접근 권한, 네트워크, 호출 한도 확인. 이 구성에는 로컬 모델 가중치 로딩 단계가 없음 |

### 관련 문서

- [AI 상세 설명](ai/README.md)
- [Backend 상세 설명](backend/README.md)
- [Business API 상세 설명](backend/business-api/README.md)
- [Business MCP 상세 설명](backend/mcp/business-mcp/README.md)
- [External MCP 상세 설명](backend/mcp/external-mcp/README.md)
- [RAG MCP 상세 설명](backend/mcp/rag-mcp/README.md)
- [Frontend 상세 설명](frontend/README.md)
