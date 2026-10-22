# 공시체크 (DisclosureCheck)

증권사 RA가 공시 이벤트 이후 기존 기업분석 메모에서 다시 검토할 문장·수치·가정을 찾도록 돕는 AI 분석 서비스입니다.

이 문서는 제공된 최종 코드 폴더를 기준으로 **Backend, AI, Frontend의 설치·실행과 전체 연동**을 안내합니다. 기본 실행 방식은 **Backend와 AI를 Docker Compose로 실행하고, Frontend를 로컬에서 실행**하는 방식입니다.

> 처음 실행한다면 3~4장의 준비와 설정을 마친 뒤 **6.1의 명령을 순서대로 실행**하세요. 터미널은 기본적으로 2개가 필요합니다. 이 파일은 프로젝트 루트의 `README.md`로 사용하는 것을 기준으로 작성했습니다.

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

공시체크는 공시와 기존 메모의 특정 버전을 비교해 변경의 직접 영향과 추가 검토가 필요한 부분을 분석합니다. 기본 변경영향 분석 후 필요한 전문 관점을 선택하고, 근거·미확인 사항·수정 제안을 포함한 보고서를 생성해 저장합니다.

### 주요 기능

- 회원가입·로그인과 조직 범위의 자료 접근 관리
- 기업·공시 검색, 관심 기업 등록, 공시 원문 등록
- UTF-8 텍스트 메모 업로드 및 기준 메모 버전 선택
- 기본 분석과 기업·산업, 재무·실적, 외부환경·위험 관점의 선택적 분석
- 분석 진행 상황 조회, 보고서 저장 및 Markdown·PDF 다운로드
- 분석 상태·체크포인트 보존과 실패 시 제한적 재시도

AI 분석은 원본 메모를 자동으로 덮어쓰지 않습니다. 결과 보고서를 읽고 기존 가정과 근거를 검토하는 방식으로 사용합니다.

보고서 초안은 프로젝트의 목적과 설계 배경을 참고하는 자료로 사용했습니다. 기술 스택, 실행 명령, 포트, API 경로는 제공된 코드로 확인했습니다. 초안에 있는 승인 후 메모 새 버전 생성과 같은 설계 항목을 이 문서의 실행 완료 조건으로 가정하지 않습니다.

## 2. 전체 구성 및 연결 구조

### 2.1 폴더 구성과 역할

```text
SKALA_Disclosure_Revision_Analysis-main/
├── ai/
│   ├── disclosure_ai/             # LangGraph 분석, Harness, Worker
│   ├── .env.example               # AI를 호스트에서 실행할 때의 예시
│   ├── pyproject.toml
│   └── Dockerfile
├── backend/
│   ├── business-api/              # 인증·메모·공시·분석·보고서 API
│   ├── mcp/
│   │   ├── business-mcp/          # 업무 조회, 진행 기록, 보고서 저장
│   │   ├── external-mcp/          # OpenDART·SEC·외부 자료 조회
│   │   └── rag-mcp/               # 원문 색인, 임베딩, 근거 검색
│   ├── shared/                    # Backend 서비스 공통 패키지
│   ├── .env.example
│   └── docker-compose.yml         # Backend 인프라와 AI Worker 포함
├── frontend/
│   ├── src/                      # Vue 화면과 HTTP 서비스
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.ts            # /api → Backend 개발 프록시
└── docs/
```

| 구분 | 주요 기술 | 실행 형태 |
| --- | --- | --- |
| Frontend | Vue 3, TypeScript, Vite, Pinia | 로컬 개발 서버 |
| Backend API·MCP | Python 3.12, FastAPI, MCP, SQLAlchemy, Alembic | Docker 컨테이너 |
| AI | Python 3.12, LangGraph, OpenAI, SQLite | RabbitMQ 메시지를 받는 Worker 컨테이너 |
| 저장·작업 전달 | PostgreSQL 16 + pgvector, RabbitMQ | Docker 컨테이너와 영속 볼륨 |

### 2.2 연결 흐름

```mermaid
flowchart TD
    Browser[브라우저] --> Frontend[Frontend :5173]
    Frontend -->|/api 프록시 + JWT| API[Business API :8080]
    API -->|분석 작업 ID 발행| Queue[RabbitMQ :5672]
    Queue --> Worker[AI Worker]
    Worker --> Business[Business MCP :8081/mcp]
    Business -->|내부 인증키| API
    Worker --> External[External MCP :8083/mcp]
    Worker --> RAG[RAG MCP :8082/mcp]
    API --> External
    RAG --> Business
    RAG --> External
    API --> DB[(PostgreSQL / core)]
    RAG --> Vector[(동일 PostgreSQL / rag + pgvector)]
    Worker --> State[(SQLite 체크포인트)]
    Worker -->|분석·보고서| OpenAI[OpenAI API]
    RAG -->|임베딩| OpenAI
    External --> Data[OpenDART / SEC / SerpApi]
```

연결에서 맞춰야 하는 핵심은 다음과 같습니다.

1. **Frontend → Backend:** 브라우저가 `/api/v1/...`을 호출하면 Vite가 `http://127.0.0.1:8080`으로 전달합니다.
2. **Backend → AI:** Backend가 `analysis.tasks` 큐에 작업을 발행하고 AI Worker가 받습니다. RabbitMQ 계정·URL·교환기·큐 이름이 일치해야 합니다.
3. **AI → Backend:** AI는 Business MCP로 메모와 작업 정보를 읽고 진행 상황과 보고서를 저장합니다. Business MCP와 Business API의 `INTERNAL_API_KEY`가 일치해야 합니다.
4. **AI → 자료·검색:** External MCP가 외부 자료를 조회하고 RAG MCP가 원문을 색인·검색합니다. 분석용 OpenAI 키와 임베딩용 OpenAI 키가 모두 전달되어야 합니다. 기본 Compose는 같은 키를 두 서비스에 전달합니다.
5. **결과 → 화면:** Frontend가 Backend의 분석 상태와 저장된 보고서를 다시 조회합니다. 현재 화면의 분석 진행 조회 간격은 2초입니다.

### 2.3 접속 주소

| 대상 | 사용자 PC에서 접근 | Docker 내부 주소 | 설명 |
| --- | --- | --- | --- |
| Frontend | `http://127.0.0.1:5173` | 해당 없음 | 사용자가 여는 웹 화면 |
| Business API | `http://127.0.0.1:8080` | `http://business-api:8080` | 업무 API |
| API 문서 | `http://127.0.0.1:8080/docs` | 해당 없음 | Swagger UI |
| RabbitMQ | `127.0.0.1:5672` | `rabbitmq:5672` | 작업 큐 연결 |
| RabbitMQ 관리 | `http://127.0.0.1:15672` | 해당 없음 | 큐·Consumer 확인 |
| Business MCP | 기본 구성에서는 직접 접근 불가 | `http://business-mcp:8081/mcp` | 내부 업무 도구 |
| RAG MCP | 기본 구성에서는 직접 접근 불가 | `http://rag-mcp:8082/mcp` | 내부 근거 검색 |
| External MCP | 기본 구성에서는 직접 접근 불가 | `http://external-mcp:8083/mcp` | 내부 외부자료 도구 |
| PostgreSQL | 기본 구성에서는 직접 접근 불가 | `postgres:5432` | 업무·RAG 데이터 저장 |
| AI Worker | 웹 접속 주소 없음 | 큐와 MCP로 연결 | 별도 HTTP 포트를 열지 않음 |

`business-api`, `business-mcp`, `postgres`, `rabbitmq` 등의 호스트명은 Compose 네트워크 안에서 사용합니다. 기본 Compose의 MCP 설정은 `expose`이므로 PC의 `127.0.0.1:8081~8083`에 포트를 공개하지 않습니다.

## 3. 실행 전 준비 사항

### 3.1 필요한 프로그램과 키

| 준비 항목 | 필요 조건 |
| --- | --- |
| Docker·Docker Compose | Docker 엔진이 실행 중이어야 함. `docker compose ... --wait`를 지원하는 버전 사용 |
| Node.js·npm | 저장소 Frontend 안내 기준 Node.js 22.18 이상인 22 계열 또는 24.12 이상 사용 |
| Python | 기본 Docker 실행에는 PC 설치 불필요. AI를 PC에서 직접 실행할 경우 Python 3.12 이상 필요 |
| OpenAI API 키 | AI 분석과 RAG 임베딩에 사용. 사용 가능한 모델과 호출 한도 확인 |
| OpenDART API 키 | 국내 기업·공시 검색과 원문 수집에 사용 |
| SerpApi API 키 | Google Scholar 검색을 사용할 경우 설정. 해당 도구 호출 시 키가 없으면 실패할 수 있음 |
| 테스트 메모 | 내용이 있는 UTF-8 `.txt` 파일, 기본 최대 5 MiB |
| 테스트 공시 | 원문 제공이 확인되는 실제 OpenDART 접수번호 14자리 |

명령은 macOS/Linux의 bash·zsh 기준입니다. Windows에서는 WSL2와 Docker 연동 환경을 사용하세요. AI Worker가 `fcntl`을 사용하므로 Windows Python에서 그대로 실행할 수 없습니다.

```bash
docker --version
docker compose version
docker info
node --version
npm --version
```

`docker info`가 실패하면 Docker Desktop 또는 사용하는 Docker 엔진을 먼저 시작합니다. 첫 빌드에는 이미지와 패키지 다운로드를 위한 네트워크 연결이 필요합니다.

### 3.2 프로젝트 루트 지정

**아래 명령은 각 새 터미널에서 한 번씩 실행합니다.** 제공된 폴더 위치를 사용한 예시입니다. 다른 PC에서는 실제 경로로 바꾸세요.

```bash
export PROJECT_ROOT="/Users/gimgyeong-eun/Downloads/SKALA_Disclosure_Revision_Analysis-main"
cd "$PROJECT_ROOT"
```

`PROJECT_ROOT`는 명령에서 폴더 이동을 쉽게 하기 위한 터미널 변수입니다. 프로젝트의 `.env`에 추가할 필요는 없습니다.

## 4. 환경 변수 설정

### 4.1 기본 실행에서 사용하는 환경 파일

| 실행 방식 | 설정 파일 | 적용 방식 |
| --- | --- | --- |
| Backend + Docker AI Worker | `backend/.env` | Compose가 읽고 각 컨테이너에 전달 |
| Frontend 개발 서버 | 기본 환경 파일 불필요 | `vite.config.ts`의 `/api` 프록시 사용 |
| AI Worker를 PC에서 직접 실행 | `ai/.env` | 5.4의 명령으로 셸에 로드 |

**기본 Docker 방식은 `backend/.env` 하나로 Backend와 AI를 설정합니다. `ai/.env`는 Compose에서 자동으로 읽지 않습니다.** `.env.example`의 주석보다 실제 `docker-compose.yml`의 전달 설정을 기준으로 합니다.

### 4.2 Backend와 Docker AI 설정

터미널에서 프로젝트 루트를 지정한 뒤 실행합니다. 기존 설정이 있으면 보존됩니다.

```bash
cd "$PROJECT_ROOT/backend"
if [ ! -f .env ]; then cp .env.example .env; fi
```

`backend/.env`를 편집기로 열고 아래 항목을 설정합니다. 다음 블록은 **수정할 항목의 예시**이며, `REPLACE_...` 값은 실제 값으로 바꿔야 합니다. 나머지 예시 파일의 설정은 유지합니다. `OPENAI_MODEL`이 없으면 추가합니다.

```dotenv
POSTGRES_USER=disclosure
POSTGRES_PASSWORD=REPLACE_WITH_DB_PASSWORD
POSTGRES_DB=disclosure
DATABASE_URL=postgresql+psycopg://disclosure:REPLACE_WITH_DB_PASSWORD@postgres:5432/disclosure

RABBITMQ_DEFAULT_USER=disclosure
RABBITMQ_DEFAULT_PASS=REPLACE_WITH_QUEUE_PASSWORD
RABBITMQ_URL=amqp://disclosure:REPLACE_WITH_QUEUE_PASSWORD@rabbitmq:5672/
RABBITMQ_EXCHANGE=analysis.exchange
RABBITMQ_ANALYSIS_QUEUE=analysis.tasks
RABBITMQ_MAX_RETRIES=3

JWT_SECRET_KEY=REPLACE_WITH_RANDOM_JWT_SECRET
INTERNAL_API_KEY=REPLACE_WITH_RANDOM_INTERNAL_SECRET

OPENDART_API_KEY=REPLACE_WITH_OPENDART_KEY
OPENAI_API_KEY=REPLACE_WITH_OPENAI_KEY
OPENAI_MODEL=gpt-5.4-mini
RAG_EMBEDDING_MODEL=text-embedding-3-small

BUSINESS_API_BASE_URL=http://business-api:8080
BUSINESS_MCP_URL=http://business-mcp:8081/mcp
EXTERNAL_MCP_URL=http://external-mcp:8083/mcp
```

| 항목 | 설정 시 확인할 점 |
| --- | --- |
| DB 비밀번호 | `POSTGRES_PASSWORD`와 `DATABASE_URL`의 비밀번호를 동일하게 설정 |
| 큐 비밀번호 | `RABBITMQ_DEFAULT_PASS`와 `RABBITMQ_URL`의 비밀번호를 동일하게 설정 |
| JWT 키 | UTF-8 기준 최소 32바이트의 무작위 값. 기본 `change-me`를 교체 |
| 내부 인증키 | 최소 32바이트의 무작위 값. `change-me`로 시작하는 값은 거부됨. Compose가 API·Business MCP에 같은 값 전달 |
| OpenAI 키 | Compose가 AI Worker와 RAG MCP에 함께 전달 |
| 분석 모델 | 코드 기본값은 `gpt-5.4-mini`. 해당 모델을 사용할 수 있는 계정·키 필요 |
| 임베딩 모델 | 현재 DB 벡터 크기는 1536차원. 모델을 임의로 변경하면 검색·저장 오류가 날 수 있으므로 기본값 유지 |
| Scholar 검색 | 사용하려면 `.env`의 `SERPAPI_API_KEY` 설정 |
| SEC 조회 | 사용할 경우 `SEC_USER_AGENT`를 서비스명과 실제 연락처가 포함된 값으로 추가 설정 |

Docker를 사용할 수 있으면 아래 명령을 **각각 한 번씩, 총 두 번 실행**해 JWT 키와 내부 인증키를 생성할 수 있습니다. 서로 다른 출력값을 각 항목에 넣습니다.

```bash
docker run --rm python:3.12-slim python -c 'import secrets; print(secrets.token_hex(32))'
```

비밀번호의 특수문자는 URL 안에서 인코딩해야 합니다. 처음 로컬 환경을 구성할 때는 영문·숫자로 된 무작위 비밀번호를 사용하면 URL 설정이 간단합니다. 환경 파일의 실제 키·비밀번호를 저장소에 올리지 마세요.

### 4.3 Frontend 연결 설정

현재 코드에는 실제 HTTP 서비스가 이미 선택되어 있습니다. 별도의 Mock 전환 설정이 필요하지 않습니다.

- `frontend/src/services/index.ts`: `createHttpServices()` 사용
- `frontend/src/services/http.ts`: `/api/v1` 상대 경로로 요청하고 JWT 헤더 추가
- `frontend/vite.config.ts`: `/api`를 `http://127.0.0.1:8080`으로 전달

Backend 호스트 포트를 8080에서 바꾼 경우에는 Frontend 실행 명령에 주소를 지정합니다. 예를 들어 Backend를 8090으로 열었다면:

```bash
cd "$PROJECT_ROOT/frontend"
API_PROXY_TARGET=http://127.0.0.1:8090 npm run dev
```

현재 설정은 `process.env.API_PROXY_TARGET`을 읽으므로 위처럼 **실행할 때 셸 변수로 전달**하세요. `frontend/.env`에 추가하는 것만으로 적용된다고 가정하지 않습니다. Frontend에는 OpenAI·OpenDART·내부 인증키를 넣지 않습니다.

## 5. 각 서비스 설치 및 실행 방법

5.1~5.3은 한 번 이어서 실행하는 기본 방식입니다. 처음부터 전체 명령을 한 번에 보려면 6.1을 사용하세요. 두 절의 명령을 중복 실행할 필요는 없습니다.

### 5.1 Backend 설치·DB 초기화·실행

**실행 위치: `backend/`. 4.2의 `.env` 설정을 먼저 완료합니다.**

```bash
cd "$PROJECT_ROOT/backend"

# 설정 구조 확인과 이미지 빌드: Python 의존성도 이미지 안에 설치됩니다.
docker compose -p disclosure-web config --quiet
docker compose -p disclosure-web build business-api business-mcp external-mcp rag-mcp

# DB와 큐가 정상 상태가 될 때까지 대기합니다.
docker compose -p disclosure-web up -d --wait postgres rabbitmq

# 업무 DB와 RAG DB를 각각 초기화/업데이트합니다.
docker compose -p disclosure-web run --rm --no-deps business-api alembic upgrade head
docker compose -p disclosure-web run --rm --no-deps rag-mcp alembic upgrade head

# API와 MCP 서비스를 실행합니다.
docker compose -p disclosure-web up -d --wait business-api business-mcp external-mcp rag-mcp
```

`alembic upgrade head`는 필요한 테이블을 만드는 명령입니다. 컨테이너를 시작하는 것만으로 테이블이 생성되지는 않습니다. 업무 데이터는 `core`, RAG 데이터는 `rag` 스키마를 사용하며 두 서비스의 migration을 모두 적용해야 합니다. 제공된 코드 기준 최신 revision은 업무 DB `0008_sec_favorites`, RAG DB `0001_rag_index`입니다.

정상 실행을 확인합니다.

```bash
curl -fS http://127.0.0.1:8080/health
curl -fS http://127.0.0.1:8080/health/db
curl -fS http://127.0.0.1:8080/health/rabbitmq
docker compose -p disclosure-web ps
```

각 health 요청이 HTTP 200과 `"status":"ok"`를 반환해야 합니다. `/health`는 API 프로세스, `/health/db`는 DB 접속을 확인합니다. **`/health/rabbitmq`는 큐 연결 확인과 분석 큐 구성을 준비하므로 AI Worker 시작 전에 꼭 호출합니다.**

### 5.2 AI 설치·실행 — 기본 Docker 방식

**실행 위치: 계속 `backend/`. Backend와 MCP가 정상 실행 중이어야 합니다.**

```bash
docker compose -p disclosure-web build ai-worker
curl -fS http://127.0.0.1:8080/health/rabbitmq
docker compose -p disclosure-web up -d ai-worker
docker compose -p disclosure-web ps ai-worker
docker compose -p disclosure-web logs --tail=50 ai-worker
```

AI 패키지와 Python 의존성은 `ai/Dockerfile`의 빌드 과정에서 설치됩니다. PC에서 별도로 `pip install`할 필요가 없습니다. Worker는 작업이 들어올 때까지 대기하므로 로그가 비어 있어도 `running` 상태와 큐 Consumer 연결을 확인하면 됩니다. Worker에는 별도 Docker healthcheck가 없습니다.

- 모델·큐·MCP 연결 값: `backend/.env`와 Compose의 `environment`
- 상태 저장 위치: 컨테이너의 `/state/ai-state.sqlite`
- 보존 방식: Docker의 `ai-state` 볼륨
- 실행 진입점: `python -m disclosure_ai.entrypoints.worker --state /state/ai-state.sqlite`

기본 연동에는 선택적 AI HTTP API `:8000`을 실행할 필요가 없습니다. 같은 SQLite 상태 파일을 사용하는 Worker를 여러 개 띄우지 않습니다.

### 5.3 Frontend 설치·실행

**새 터미널을 열고 3.2처럼 `PROJECT_ROOT`를 지정한 뒤 실행합니다.**

```bash
cd "$PROJECT_ROOT/frontend"
npm ci
npm run dev
```

브라우저에서 **`http://127.0.0.1:5173`**에 접속합니다. 이 터미널은 실행한 상태로 유지합니다. `5173`이 사용 중이면 자동으로 다른 포트를 고르지 않고 실행이 실패합니다.

처음 이용할 때는 웹 화면에서 회원가입 후 로그인합니다. 조직 이름·이메일·12~128자의 비밀번호가 필요합니다. 회원가입은 새 조직과 RA 계정을 생성하므로 미리 준비된 기본 계정은 없습니다.

빌드가 필요한 경우 Frontend 폴더에서 실행합니다.

```bash
npm run build
```

결과는 `frontend/dist/`에 생성됩니다. 실제 정적 배포에는 `/api`를 Backend로 전달하는 reverse proxy와 SPA 경로를 `index.html`로 보내는 fallback 설정이 필요합니다. 이 문서의 `npm run dev` 연동은 개발 실행 기준입니다.

### 5.4 AI를 PC에서 직접 실행하는 방법 — 선택 사항

AI 코드를 수정하며 실행할 때만 사용합니다. **5.2의 Docker Worker를 대신하는 방법**이며, Backend·DB·RabbitMQ·MCP는 Docker에서 실행합니다. Python 3.12 이상이 필요합니다. 아래 예시는 `python3.12` 명령 기준입니다.

먼저 기존 Worker를 중지하고, 기본 Compose에서 공개하지 않는 MCP 포트를 로컬 PC에 연결합니다. `backend/compose.ai-local.yml` 파일이 이미 있으면 기존 내용을 확인한 뒤 병합하세요. 처음 만드는 경우:

```bash
cd "$PROJECT_ROOT/backend"
docker compose -p disclosure-web stop ai-worker

cat > compose.ai-local.yml <<'YAML'
services:
  business-mcp:
    ports:
      - "127.0.0.1:8081:8081"
  rag-mcp:
    ports:
      - "127.0.0.1:8082:8082"
  external-mcp:
    ports:
      - "127.0.0.1:8083:8083"
YAML

docker compose -p disclosure-web -f docker-compose.yml -f compose.ai-local.yml up -d --wait business-api business-mcp external-mcp rag-mcp
curl -fS http://127.0.0.1:8080/health/rabbitmq

cd "$PROJECT_ROOT/ai"
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
if [ ! -f .env ]; then cp .env.example .env; fi
```

`ai/.env`의 다음 항목을 설정합니다. RabbitMQ 사용자·비밀번호·포트는 `backend/.env`와 맞춥니다. 아래의 비밀번호와 OpenAI 키는 실제 값으로 교체합니다.

```dotenv
OPENAI_API_KEY=REPLACE_WITH_OPENAI_KEY
OPENAI_MODEL=gpt-5.4-mini
RABBITMQ_URL=amqp://disclosure:REPLACE_WITH_QUEUE_PASSWORD@127.0.0.1:5672/
RABBITMQ_EXCHANGE=analysis.exchange
RABBITMQ_ANALYSIS_QUEUE=analysis.tasks
RABBITMQ_MAX_RETRIES=3
BUSINESS_MCP_URL=http://127.0.0.1:8081/mcp
EXTERNAL_MCP_URL=http://127.0.0.1:8083/mcp
RAG_MCP_URL=http://127.0.0.1:8082/mcp
```

`backend/.env`의 Docker 내부 URL은 그대로 둡니다. PC에서 실행하는 AI의 URL만 `127.0.0.1`을 사용합니다. RAG 임베딩 키는 계속 `backend/.env`에서 관리합니다.

설정 후 같은 AI 터미널에서 실행합니다. Worker는 환경 파일을 자동으로 로드하지 않으므로 아래의 `source`가 필요합니다.

```bash
cd "$PROJECT_ROOT/ai"
set -a
source .env
set +a
.venv/bin/python -m disclosure_ai.entrypoints.worker --state "$PROJECT_ROOT/ai/outputs/ai-state.sqlite"
```

이 경우 Backend 관리용, AI 실행용, Frontend 실행용으로 터미널 3개를 사용합니다. 로컬 Worker는 `Ctrl+C`로 종료합니다. Docker Worker로 돌아갈 때는 로컬 Worker를 먼저 종료하고 5.2를 실행하세요. 로컬과 Docker의 상태 파일은 서로 다른 위치에 있으므로 기존 작업의 재저장은 해당 작업을 처리한 환경의 상태 파일로 수행합니다.

## 6. 전체 연동 및 실행 순서

### 6.1 최초 실행 — 이 순서대로 실행

**선행 조건: 3장의 프로그램 준비와 4.2의 `backend/.env` 설정 완료. 각 명령이 성공한 것을 확인한 뒤 다음 단계로 진행합니다.**

**터미널 1: Backend → AI**

```bash
export PROJECT_ROOT="/Users/gimgyeong-eun/Downloads/SKALA_Disclosure_Revision_Analysis-main"
cd "$PROJECT_ROOT/backend"

# 1. 설정 확인 및 Backend·AI 전체 이미지 빌드
docker compose -p disclosure-web config --quiet
docker compose -p disclosure-web build

# 2. DB·RabbitMQ 시작 및 정상 상태 대기
docker compose -p disclosure-web up -d --wait postgres rabbitmq

# 3. 업무 DB와 RAG DB 각각 초기화/업데이트
docker compose -p disclosure-web run --rm --no-deps business-api alembic upgrade head
docker compose -p disclosure-web run --rm --no-deps rag-mcp alembic upgrade head

# 4. Backend API와 MCP 시작
docker compose -p disclosure-web up -d --wait business-api business-mcp external-mcp rag-mcp

# 5. DB 연결 확인과 작업 큐 준비
curl -fS http://127.0.0.1:8080/health/db
curl -fS http://127.0.0.1:8080/health/rabbitmq

# 6. AI Worker 시작
docker compose -p disclosure-web up -d ai-worker
docker compose -p disclosure-web ps
```

**터미널 2: Frontend**

```bash
export PROJECT_ROOT="/Users/gimgyeong-eun/Downloads/SKALA_Disclosure_Revision_Analysis-main"
cd "$PROJECT_ROOT/frontend"
npm ci
npm run dev
```

**브라우저:** `http://127.0.0.1:5173` 접속 → 회원가입·로그인 → 기업 검색 → 공시·메모 선택 → 분석 시작 → 보고서 확인.

Backend·MCP는 `healthy`, AI Worker는 `running`이어야 합니다. 화면이 열리는 것과 AI 분석 연동이 완료되는 것은 별도로 확인해야 합니다. 7장의 테스트로 보고서 저장까지 확인하세요.

### 6.2 설치 후 다시 실행

이미 초기화한 동일한 환경에서는 다음으로 시작합니다.

```bash
cd "$PROJECT_ROOT/backend"
docker compose -p disclosure-web up -d --wait business-api business-mcp external-mcp rag-mcp
curl -fS http://127.0.0.1:8080/health/db
curl -fS http://127.0.0.1:8080/health/rabbitmq
docker compose -p disclosure-web up -d ai-worker
```

Frontend 터미널에서는 `cd "$PROJECT_ROOT/frontend"` 후 `npm run dev`를 실행합니다. `package-lock.json`이 변경되었을 때는 `npm ci`를 다시 실행합니다. 코드를 업데이트했다면 필요한 이미지를 다시 빌드하고, 새 migration이 있으면 6.1의 DB 업데이트도 적용합니다.

### 6.3 설정 변경 적용과 종료

`backend/.env`를 수정한 뒤에는 영향받는 컨테이너를 다시 생성해야 합니다. 예를 들어 OpenAI 키·모델을 변경한 경우:

```bash
cd "$PROJECT_ROOT/backend"
docker compose -p disclosure-web up -d --force-recreate rag-mcp ai-worker
```

JWT·내부 인증키는 `business-api business-mcp`, OpenDART·SerpApi 키는 `external-mcp`를 같은 방식으로 다시 생성합니다. `restart`만으로는 변경한 환경 변수가 반영되지 않습니다.

종료할 때는 Frontend 터미널에서 `Ctrl+C`를 누르고 Backend 폴더에서 실행합니다.

```bash
docker compose -p disclosure-web down
```

DB·RabbitMQ·AI 상태는 볼륨에 보존됩니다. 일반 종료에서는 볼륨을 삭제하는 `down -v`를 사용하지 않습니다. 모든 명령에서 `-p disclosure-web`을 동일하게 유지해야 같은 컨테이너·볼륨을 사용합니다.

## 7. 연동 테스트

### 7.1 서비스 연결 확인

Backend 폴더에서 실행합니다.

```bash
cd "$PROJECT_ROOT/backend"
docker compose -p disclosure-web ps
curl -fS http://127.0.0.1:8080/health
curl -fS http://127.0.0.1:8080/health/db
curl -fS http://127.0.0.1:8080/health/rabbitmq

# 브라우저와 동일한 Frontend 프록시를 거치는 API 요청: 미로그인 상태에서는 401 예상
curl -i http://127.0.0.1:5173/api/v1/users/me

# Worker가 큐에 연결되었는지 확인
docker compose -p disclosure-web exec rabbitmq rabbitmqctl list_queues name messages consumers
```

`analysis.tasks`의 Consumer는 기본 Worker 1개 기준 `1`이어야 합니다. 작업이 없을 때 `messages`가 `0`인 것은 정상입니다. MCP의 `/health` 성공만으로 외부 API 키·원문 조회·임베딩까지 검증되지는 않습니다.

### 7.2 웹 화면에서 전체 연동 확인

1. `http://127.0.0.1:5173`에 접속해 회원가입하고 로그인합니다.
2. 기업 목록에서 분석할 기업을 검색하고 즐겨찾기에 추가합니다. 관심 기업이 내 페이지에 표시되는지 확인합니다.
3. 기업 상세 공시 탭에서 날짜 범위를 지정해 공시를 조회합니다. 기본 조회 기간은 최근 90일이므로 과거 사례는 기간을 직접 바꿉니다.
4. 메모 관리에서 해당 기업의 UTF-8 `.txt` 메모를 업로드하거나 직접 작성해 저장합니다.
5. 원문을 제공하는 공시를 선택해 서버에 등록하고, 기준 메모와 버전을 선택해 분석을 시작합니다. 분석은 같은 조직에 등록한 정정공시만 선택할 수 있습니다. 일반 공시에는 분석 버튼이 표시되지 않습니다.
6. 분석 상태가 `QUEUED → RUNNING → SAVING → COMPLETED` 또는 `COMPLETED_WITH_WARNINGS`로 이동하는지 확인합니다. 일부 중간 상태는 빠르게 지나가 화면에서 보이지 않을 수 있습니다.
7. 보고서의 근거·미확인 사항·관점별 결과를 확인하고 MD 또는 PDF 다운로드를 확인합니다.
8. 새로고침 후에도 같은 보고서가 조회되고 원본 메모가 보존되는지 확인합니다.

기업 목록의 시세와 국내 관심종목은 외부 API로 조회합니다. 공시 배지는 최근 90일 공개 공시 건수이며 메모와 보고서는 기업별 저장 건수입니다. 산업군도 외부 분류를 조회합니다. 제공자 응답에 없는 종목은 시세 없음으로 표시합니다. 자세한 화면 동작은 [Frontend 안내](frontend/README.md)를 확인합니다.

### 7.3 API로 직접 확인 — 로그인·메모 업로드

화면에서 문제가 생겼을 때 아래 절차로 연결을 나누어 확인할 수 있습니다. 테스트용 계정은 웹 회원가입으로 먼저 생성합니다. 새 터미널에서 이후 명령을 **같은 셸 안에서 순서대로** 실행하세요.

`http://127.0.0.1:8080/docs`의 `POST /api/v1/auth/login`에 가입한 이메일·비밀번호를 넣습니다.

```json
{
  "email": "ra.local@example.com",
  "password": "회원가입할_때_정한_실제_비밀번호"
}
```

응답의 `access_token`을 사용하고 실제 메모 파일의 절대 경로를 지정합니다.

```bash
export ACCESS_TOKEN='로그인_응답의_access_token으로_교체'
export MEMO_FILE='/실제/절대경로/memo.txt'

curl -fS -X POST http://127.0.0.1:8080/api/v1/memos \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "file=@${MEMO_FILE};type=text/plain" \
  -F 'title=공시 연동 테스트 메모'
```

HTTP 201 응답의 `id`와 `current_version`을 다음 변수에 넣습니다. 예시 문자열을 그대로 보내면 UUID 형식 오류가 발생합니다.

```bash
export MEMO_ID='업로드_응답의_id_UUID로_교체'
export MEMO_VERSION='1'
export RECEIPT_NO='실제_OpenDART_14자리_접수번호로_교체'
```

### 7.4 공시 원문 등록 → 분석 접수

**분석 요청 전에 같은 계정·조직으로 공시 원문을 등록해야 합니다.** 14자리 번호 형식만 맞추거나 공시 목록을 검색한 것만으로 등록되지는 않습니다.

```bash
# 1. 실제 공시 원문과 메타데이터를 조회해 등록
curl -fS -X POST http://127.0.0.1:8080/api/v1/filings \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"receipt_no\":\"$RECEIPT_NO\"}"

# 2. 공시 등록이 성공한 뒤 분석 요청
curl -fS -X POST http://127.0.0.1:8080/api/v1/analyses \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"memo_id\":\"$MEMO_ID\",\"memo_version\":$MEMO_VERSION,\"disclosure_receipt_no\":\"$RECEIPT_NO\"}"
```

분석 접수가 성공하면 HTTP 202와 `task_id`, `status: QUEUED`가 반환됩니다. 이는 큐 발행이 완료된 상태이며 분석 완료는 아닙니다. 응답의 `task_id`를 설정합니다.

```bash
export TASK_ID='분석_응답의_task_id_UUID로_교체'

# 상태·오류 코드 확인
curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# 진행 이벤트 확인
curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/events" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# 선택된 관점과 결과 확인
curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/perspectives" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

작업이 진행 중이면 상태 조회를 다시 실행합니다. JWT 기본 만료 시간은 30분이므로 401이 나오면 다시 로그인하고 `ACCESS_TOKEN`을 갱신합니다.

### 7.5 보고서 저장까지 확인

```bash
curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/report" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

보고서가 생성되기 전에는 `null`이 반환될 수 있습니다. 저장된 보고서에서는 `content`, `report_json`, `saved_at`을 확인합니다.

연동 완료 기준은 **같은 작업 ID에 대해 요청 접수 → AI 처리 → 보고서 저장 → 웹 재조회가 모두 이어지는 것**입니다. `COMPLETED_WITH_WARNINGS`이면 경고와 누락된 근거를 함께 확인합니다. 보고서가 만들어졌다는 사실만으로 모든 외부 도구 호출과 분석 내용의 정확성을 보장하지는 않습니다.

문제가 발생하면 Backend 폴더에서 로그를 확인합니다.

```bash
docker compose -p disclosure-web logs --tail=100 business-api business-mcp external-mcp rag-mcp ai-worker
```

### 7.6 코드 검증 명령과 문서 검증 범위

Frontend 폴더에서 기본 검사를 실행할 수 있습니다.

```bash
cd "$PROJECT_ROOT/frontend"
npm test
npm run build
```

`npm run build`에는 TypeScript 타입 검사가 포함됩니다. AI의 로컬 가상환경을 준비한 경우에는 다음으로 기본 테스트를 실행할 수 있습니다.

```bash
cd "$PROJECT_ROOT/ai"
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest tests -q
```

위 명령은 사용자가 수행할 검증 절차입니다. 이 README 작성 시에는 코드·설정·migration·명령 경로를 대조하고 Compose 설정 구조를 검사했습니다. 로컬 Docker 엔진이 실행 중이지 않아 컨테이너 기동, 실제 키를 사용한 외부 API 호출과 웹 전체 연동 테스트는 수행하지 않았습니다.

## 8. 자주 발생하는 오류와 해결 방법

| 증상 | 원인 확인 및 해결 |
| --- | --- |
| `Cannot connect to the Docker daemon` | Docker Desktop 또는 Docker 엔진 시작 후 `docker info` 확인 |
| `.env not found`, `required variable ... is missing` | `backend/`에서 `.env.example`을 `.env`로 복사했는지 확인. 기존 파일은 덮어쓰지 않고 필수 값 수정 |
| `npm ci` 실패·Node 버전 오류 | 3장의 Node 버전과 잠금 파일 확인. `frontend/`에서 실행 |
| `5173`, `8080`, `5672`, `15672` 포트 충돌 | 해당 포트를 사용하는 프로세스 확인. Backend API 호스트 포트를 바꾸면 Frontend의 `API_PROXY_TARGET`도 함께 변경 |
| 웹은 열리지만 API 연결 실패 | `http://127.0.0.1:8080/health`와 Frontend의 `/api` 프록시 확인. 포트·주소 변경 후 개발 서버 재시작 |
| 로그인 시 401 | 회원가입 여부, 이메일·비밀번호, 토큰 만료 확인. 기본 계정은 제공되지 않음 |
| JWT 설정 오류·내부 인증 503/401 | 무작위 키가 32바이트 이상인지 확인. API·Business MCP의 내부 인증키를 맞춘 뒤 두 컨테이너 재생성 |
| DB 테이블 없음·`rag` 스키마·`vector` 오류 | 업무 DB와 RAG DB migration을 모두 적용. 기본 `pgvector/pgvector:pg16` 이미지 사용 및 확장 생성 권한 확인 |
| 과거 README대로 했는데 일부 기능에서 DB 오류 | 최신 업무 migration `0008_sec_favorites`까지 반영됐는지 `alembic current`로 확인 |
| DB·RabbitMQ 비밀번호를 바꿔도 인증 실패 | 기존 볼륨의 실제 계정 정보와 `.env`를 일치시켜야 함. 환경 변수 변경만으로 기존 계정 비밀번호가 자동 변경되지 않음 |
| AI가 `QUEUED`에 머묾 | Worker `running` 여부, RabbitMQ 큐의 Consumer 수, 양쪽 큐 이름·교환기·계정 확인 |
| `BROKER_RECONNECT`가 반복됨 | `/health/rabbitmq`를 먼저 호출해 큐 준비. `RABBITMQ_URL`의 계정·호스트·포트 확인. Docker Worker는 `rabbitmq`, PC Worker는 `127.0.0.1` 사용 |
| `MCP_UNAVAILABLE`, 로컬 AI에서 연결 거절 | Docker 내부 MCP 주소와 로컬 주소 구분. 기본 Compose는 MCP를 PC에 공개하지 않으므로 PC Worker는 5.4의 포트 연결 필요 |
| `/mcp`를 브라우저로 열면 오류 | `/mcp`는 MCP 프로토콜 경로. 일반 GET 성공 여부로 판단하지 말고 컨테이너 health와 실제 도구 호출을 확인 |
| OpenDART 기업·공시 조회 실패 | `OPENDART_API_KEY`, 외부 연결, 호출 제한과 원문 제공 여부 확인. 키 변경 시 `external-mcp` 재생성 |
| Scholar 검색만 실패 | `SERPAPI_API_KEY`와 해당 도구 오류·보고서 경고 확인 |
| OpenAI·임베딩 오류 | `backend/.env`의 `OPENAI_API_KEY`, 모델 접근 가능 여부·호출 한도 확인 후 `rag-mcp ai-worker` 재생성 |
| 키를 `ai/.env`에 넣었는데 Docker AI에 적용되지 않음 | Docker Worker는 `backend/.env`를 사용. PC Worker는 `ai/.env`를 `source`한 셸에서 실행 |
| `CORRECTION_REQUIRED` / 422 | 같은 조직에 등록한 정정공시인지 확인한 후 분석합니다. |
| `ANALYSIS_ALREADY_RUNNING` / 409 | 동일 메모 버전·공시에 진행 중인 작업이 있음. 응답의 `existing_task_id`로 기존 작업 조회 |
| 메모 업로드 413·415·422 | 기본 5 MiB 이하, UTF-8 `.txt`, `text/plain`, multipart `file` 필드 확인. PDF·DOCX는 업로드 대상이 아님 |
| `SAVE_FAILED` | 분석을 처리한 Worker의 상태 파일을 보존하고 아래 재저장 절차 사용 |
| SQLite 잠금·`BlockingIOError` | 같은 상태 파일을 사용하는 Worker·선택적 AI API 중복 실행 여부 확인 |
| 보고서 API가 `null` | 아직 저장 전일 수 있음. 작업 상태·이벤트 확인. 실패 상태라면 오류 코드와 Worker 로그 확인 |
| 예전 공시가 화면에 안 보임 | 기본 최근 90일 필터를 테스트 사례 날짜에 맞게 변경 |
| 정적 배포에서 API·새로고침 오류 | 배포 서버에 `/api` reverse proxy와 SPA fallback 설정 필요 |

### 8.1 DB migration 적용 여부 확인

Backend 폴더에서 실행합니다.

```bash
cd "$PROJECT_ROOT/backend"
docker compose -p disclosure-web run --rm --no-deps business-api alembic current
docker compose -p disclosure-web run --rm --no-deps rag-mcp alembic current
```

현재 코드 기준 각각 `0008_sec_favorites`, `0001_rag_index`가 표시되어야 합니다. 뒤처져 있으면 5.1의 각 `alembic upgrade head`를 실행합니다.

### 8.2 Docker AI의 저장 실패 재시도

**5.2의 Docker Worker가 처리했고 `SAVE_FAILED` 상태인 작업**에 사용합니다. 같은 `ai-state` 볼륨과 동일한 작업 ID를 유지해야 합니다. 아래 작업 ID를 실제 값으로 바꾸세요.

```bash
cd "$PROJECT_ROOT/backend"
export TASK_ID='저장에_실패한_실제_task_id_UUID'

# 같은 상태 파일의 동시 사용을 막고, 보존한 보고서를 재저장합니다.
docker compose -p disclosure-web stop ai-worker
docker compose -p disclosure-web run --rm --no-deps ai-worker \
  python -m disclosure_ai.entrypoints.worker \
  --state /state/ai-state.sqlite --task-id "$TASK_ID"

# 재저장 결과를 확인한 뒤 Worker를 다시 시작합니다.
docker compose -p disclosure-web up -d ai-worker
```

이 경로는 기존 로컬 보고서를 다시 저장합니다. 실패 원인이 내부 인증·DB·MCP 연결이면 해당 설정을 먼저 복구해야 합니다. 상태 파일에 보고서가 없으면 이 방법으로 보고서를 복구할 수 없습니다. PC Worker가 처리한 작업은 해당 PC 상태 파일을 사용해 같은 `--task-id` 방식으로 실행합니다.
