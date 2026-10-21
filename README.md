# 공시체크 (DisclosureCheck)

AI·Frontend·Backend의 설치, 환경 설정, 실행 및 연동 방법을 안내합니다. 실행 순서와 터미널별 명령은 [6.1 실행 방법](#61-실행-방법-backend--ai--frontend)에 정리되어 있습니다.

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

공시체크는 증권사 RA가 공시 이벤트 이후 기존 기업분석 메모의 문장·수치·가정을 재검토하도록 돕는 서비스입니다. AI가 공시와 고정된 메모 버전을 비교하고, 필요한 관점의 추가 분석을 거쳐 근거·미확인 사항·수정 제안을 담은 보고서를 생성합니다.

### 주요 기능

- 공시·메모 원문 및 기준 버전 조회
- 기본 변경영향 분석과 필요한 전문 관점 선택
- 근거 검색 및 출처를 포함한 보고서 생성
- 분석 작업 대기열, 진행 이벤트, 보고서 저장

### 서비스별 역할

| 서비스 | 역할 | 주요 기술 |
| --- | --- | --- |
| AI | 큐 작업 수신, 기본·전문 분석, 보고서 생성, 체크포인트 보존 | Python, LangGraph, OpenAI, SQLite |
| Frontend | 공시·메모 선택, 분석 진행 및 보고서 화면 | Vue 3, TypeScript, Vite, Pinia |
| Backend | 인증, 업무 데이터, 분석 접수·진행·저장, MCP 제공 | FastAPI, SQLAlchemy, PostgreSQL, RabbitMQ, MCP |

> Frontend는 현재 샘플 데이터 기반으로 동작합니다. 실제 Backend·AI 분석은 API로 실행할 수 있으며, 화면에서 실제 분석을 요청하려면 6.2~6.4절의 API 연결 작업이 필요합니다.

## 2. 전체 구성 및 연결 구조

### 2.1 프로젝트 구조

```text
SKALA_Disclosure_Revision_Analysis-main/
├── README.md                     # 이 문서
├── ai/
│   ├── disclosure_ai/            # LangGraph·Harness·Worker·선택적 API
│   ├── tests/
│   ├── .env.example
│   └── pyproject.toml
├── backend/
│   ├── business-api/            # 인증·공시·메모·분석·이벤트 API
│   ├── mcp/
│   │   ├── business-mcp/        # 업무 조회·진행 상태·보고서 저장
│   │   ├── external-mcp/        # OpenDART 공시 원문 조회
│   │   └── rag-mcp/             # 메모·공시 색인 및 근거 검색
│   ├── shared/
│   ├── .env.example
│   └── docker-compose.yml
├── frontend/
│   ├── src/services/            # 현재 mock 구현, 실제 HTTP adapter 필요
│   ├── src/views/
│   ├── package.json
│   └── vite.config.ts
└── docs/                       # 팀 작업 기록
```

### 2.2 요청 및 응답 흐름

```mermaid
flowchart TD
    UI[Frontend: 현재 샘플 UI]
    API[Business API :8080]
    Q[RabbitMQ :5672]
    AI[AI Worker: ai/]
    B[Business MCP :8081/mcp]
    E[External MCP :8083/mcp]
    R[RAG MCP :8082/mcp]
    DB[(PostgreSQL + pgvector)]
    D[OpenDART]
    O[OpenAI]
    UI -. HTTP adapter 구현 필요 .-> API
    API -->|분석 작업 발행| Q
    Q -->|작업 ID 전달| AI
    AI -->|입력 조회·진행 기록·결과 저장| B
    B -->|내부 API + 내부 인증키| API
    API --> DB
    AI --> E
    E --> D
    AI --> R
    R --> B
    R --> E
    R --> DB
    R -->|임베딩| O
    AI -->|분석·보고서 생성| O
    API -. 인증된 상태 조회·SSE: 화면 연결 필요 .-> UI
```

작업 접수 → 공시·메모 수집 → RAG 준비 → 기본 분석 → 필요한 관점 실행 → 보고서 생성 → 업무 DB 저장 순서입니다. AI Worker는 HTTP 서버가 아니므로 기본 실행에 별도 접속 포트가 없습니다.

### 2.3 서비스별 주소와 포트

Backend와 인프라는 Docker로, AI와 Frontend는 Mac/Linux 호스트에서 실행합니다. AI가 Docker 내부 MCP에 접근할 수 있도록 **로컬 전용 실행 파일에서만 MCP 포트를 `127.0.0.1`에 공개**합니다.

| 서비스 | 호스트에서 쓰는 주소 | Docker 내부에서 쓰는 주소 |
| --- | --- | --- |
| Frontend | `http://127.0.0.1:5173` | 해당 없음 |
| Business API | `http://127.0.0.1:8080` | `http://business-api:8080` |
| Business MCP | `http://127.0.0.1:8081/mcp` | `http://business-mcp:8081/mcp` |
| RAG MCP | `http://127.0.0.1:8082/mcp` | `http://rag-mcp:8082/mcp` |
| External MCP | `http://127.0.0.1:8083/mcp` | `http://external-mcp:8083/mcp` |
| RabbitMQ AMQP | `amqp://사용자:비밀번호@127.0.0.1:5672/` | `amqp://사용자:비밀번호@rabbitmq:5672/` |
| RabbitMQ 관리 화면 | `http://127.0.0.1:15672` | 해당 없음 |
| PostgreSQL | 기본 호스트 포트 공개 없음 | `postgres:5432` |
| 선택적 AI API | `http://127.0.0.1:8000` | 기본 흐름에서는 실행하지 않음 |

`business-mcp`, `rabbitmq`, `postgres` 같은 이름은 Docker 내부 주소입니다. 반대로 컨테이너 안에서 `127.0.0.1`은 그 컨테이너 자신이므로 다른 서비스 주소로 사용하면 연결되지 않습니다.

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

`.env.example`은 예시이며 실제 키가 아닙니다. 각 `.env`를 직접 작성해야 합니다. API 키·인증키·상태 DB는 공유하거나 커밋하지 않습니다. Frontend의 `VITE_*` 값은 브라우저에 포함되므로 비밀키를 넣으면 안 됩니다.

## 4. 환경 변수 설정

### 4.1 설정 파일과 연결 지점

| 변경 파일 | 설정할 항목 | 연결 대상 |
| --- | --- | --- |
| `backend/.env` | DB·RabbitMQ URL, JWT·내부 인증키, OpenDART·OpenAI 키 | Backend → DB·큐·외부 API |
| `backend/docker-compose.local.yml` | MCP 호스트 포트 공개 | 호스트 AI → Docker 내부 MCP |
| `ai/.env` | RabbitMQ URL, MCP URL, 모델 이름과 OpenAI 키 | AI → 큐·MCP·모델 API |
| `frontend/vite.config.ts` | `/api` 개발 프록시 | Frontend → Backend `:8080` |
| `frontend/src/services/index.ts` | 실제 HTTP 서비스 선택 | 화면 → HTTP adapter |
| `frontend/src/services/http.ts` (추가 필요) | API 경로, Bearer 헤더, 응답 변환 | Frontend → `/api/v1/...` |

Backend → AI는 HTTP 주소 대신 RabbitMQ 작업 큐로 연결합니다. 양쪽의 계정·교환기·큐 이름을 맞추고, AI → Backend의 업무 조회와 저장에는 Business MCP 주소를 사용합니다.

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

비밀번호에 URL 특수문자가 있으면 접속 URL 안의 비밀번호를 URL 인코딩합니다. 처음에는 영문·숫자로 만든 임의 비밀번호를 사용하면 설정이 간단합니다. DB/큐 비밀번호와 URL 안의 비밀번호는 반드시 일치해야 합니다.

다음 명령은 JWT용과 내부 통신용 임의 값을 각각 생성하는 예시입니다. 출력된 값을 로컬 `.env`에 넣습니다.

```bash
python3.12 -c 'import secrets; print(secrets.token_hex(32))'
python3.12 -c 'import secrets; print(secrets.token_hex(32))'
```

`RABBITMQ_EXCHANGE=analysis.exchange`, `RABBITMQ_ANALYSIS_QUEUE=analysis.tasks`, `RABBITMQ_MAX_RETRIES=3`은 기본값으로 유지합니다. 포트도 8080~8083, 5672, 15672 기본값을 기준으로 합니다.

### 4.3 AI: `ai/.env`

프로젝트 루트에서 다음 파일을 준비합니다. 기존 설정이 있으면 복사하지 않습니다.

```bash
cd ai
cp .env.example .env
```

기존 `.env`는 덮어쓰지 않습니다. `ai/.env`에 다음 값을 설정합니다.

```dotenv
OPENAI_MODEL=gpt-4.1-mini
OPENAI_API_KEY=실제_OpenAI_API_키
BUSINESS_API_BASE_URL=http://127.0.0.1:8080
BUSINESS_MCP_URL=http://127.0.0.1:8081/mcp
EXTERNAL_MCP_URL=http://127.0.0.1:8083/mcp
RAG_MCP_URL=http://127.0.0.1:8082/mcp
RABBITMQ_URL=amqp://disclosure:Backend와_같은_큐비밀번호@127.0.0.1:5672/
RABBITMQ_EXCHANGE=analysis.exchange
RABBITMQ_ANALYSIS_QUEUE=analysis.tasks
RABBITMQ_MAX_RETRIES=3
AI_STATE_PATH=outputs/ai-state.sqlite
LANGSMITH_TRACING=false
```

위의 한글 값은 설명용 자리 표시자입니다. 실제 키·비밀번호로 바꿉니다. AI용 `RABBITMQ_URL`의 호스트는 **`127.0.0.1`**, Backend용 URL의 호스트는 **`rabbitmq`**입니다. 사용자·비밀번호·교환기·큐·재시도 횟수는 양쪽이 일치해야 합니다.

AI에는 OpenDART 키나 Backend의 `INTERNAL_API_KEY`를 넣지 않습니다. OpenDART 키는 External MCP가, 내부 API 키는 Business MCP가 사용합니다. `BUSINESS_API_BASE_URL`은 선택적 AI API의 사용자 권한 확인에도 사용되며, 기본 Worker의 업무 조회·저장은 Business MCP를 통합니다.

### 4.4 Frontend → Backend 연결 및 CORS

현재 Backend에는 CORS middleware가 없고 Vite에는 API 프록시가 없습니다. 로컬 개발에서는 Frontend가 `/api/...` 상대경로를 호출하고 Vite가 8080으로 전달하도록 설정할 수 있습니다.

`frontend/vite.config.ts`의 기존 `server` 항목을 다음처럼 바꿉니다. 기존 `plugins`, `test` 설정은 유지합니다.

```ts
server: {
  port: 5173,
  strictPort: true,
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8080',
      changeOrigin: true,
    },
  },
},
```

프록시는 요청 경로를 바꾸지 않으므로 `/api/v1/memos`는 Backend의 같은 경로로 전달됩니다. 변경 후 Vite를 재시작합니다. 이 설정은 개발 서버용이며 빌드 배포에는 별도의 reverse proxy 또는 허용 origin을 지정한 Backend CORS 설정이 필요합니다.

`VITE_API_BASE_URL`은 현재 코드에서 읽지 않습니다. 해당 환경변수만 추가해도 연결되지 않습니다. 위 방식을 사용하면 adapter는 `/api/v1` 기준의 상대경로를 사용하면 됩니다.

## 5. 각 서비스 설치 및 실행 방법

Backend 인프라를 먼저 준비하고 AI Worker와 Frontend를 실행합니다. 각 명령의 시작 폴더를 확인하세요.

### 5.1 Backend: 로컬 Compose 설정

새 터미널을 열고 프로젝트 루트에서 Backend 폴더로 이동합니다. 4.2절의 `.env` 설정을 먼저 완료합니다.

```bash
cd backend
```

`docker-compose.yml`의 서비스 설정에 다음 `postgres` 블록이 중복되어 있습니다. 로컬 실행 파일을 생성할 때 이 블록만 제거하고, `image:`로 시작하는 PostgreSQL 서비스 설정은 유지합니다.

```yaml
  postgres:
        condition: service_healthy
```

다음 명령은 **원본을 보존**하고 이 블록을 제거한 `backend/docker-compose.local.yml`을 생성합니다. 동시에 호스트 AI가 접근하도록 MCP 포트 3개를 loopback에 공개합니다. 이미 같은 이름의 파일이 있으면 덮어쓰지 않고 중단합니다.

```bash
python3.12 - <<'PY'
from pathlib import Path

source = Path("docker-compose.yml").read_text(encoding="utf-8")
invalid_block = "\n  postgres:\n        condition: service_healthy\n"
if source.count(invalid_block) != 1:
    raise SystemExit("원본 구조가 달라졌습니다. 중복 postgres 항목을 직접 확인하세요.")
source = source.replace(invalid_block, "", 1)
for name, port in (
    ("BUSINESS_MCP_PORT", 8081),
    ("RAG_MCP_PORT", 8082),
    ("EXTERNAL_MCP_PORT", 8083),
):
    marker = f'    expose:\n      - "${{{name}:-{port}}}"'
    if source.count(marker) != 1:
        raise SystemExit(f"{name} 서비스 설정을 직접 확인하세요.")
    published = (
        f'    ports:\n      - "127.0.0.1:{port}:${{{name}:-{port}}}"\n'
        + marker
    )
    source = source.replace(marker, published, 1)
with Path("docker-compose.local.yml").open("x", encoding="utf-8") as output:
    output.write(source)
print("docker-compose.local.yml 생성 완료")
PY

docker compose -f docker-compose.local.yml config --quiet
```

이후 Backend 명령에는 항상 **`-f docker-compose.local.yml`**을 붙입니다. 생성 파일과 실제 `.env`는 로컬 실행용으로 관리합니다. MCP는 별도 사용자 인증이 없는 내부 도구이므로 이 예시의 `127.0.0.1` 바인딩을 유지합니다.

### 5.2 Backend: 의존성 설치·DB 초기화·실행

**실행 위치: 계속 `backend/`.**

```bash
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml up -d postgres rabbitmq
docker compose -f docker-compose.local.yml ps
```

PostgreSQL과 RabbitMQ가 `healthy` 상태가 될 때까지 기다립니다. 이후 **업무 DB와 RAG DB를 각각** 초기화합니다. 컨테이너 기동만으로 테이블이 자동 생성되지는 않습니다.

```bash
docker compose -f docker-compose.local.yml run --rm --no-deps business-api alembic upgrade head
docker compose -f docker-compose.local.yml run --rm --no-deps rag-mcp alembic upgrade head
docker compose -f docker-compose.local.yml up -d
docker compose -f docker-compose.local.yml ps
```

업무 migration은 `0004_analysis_company`, RAG migration은 별도 이력의 `0001_rag_index`까지 적용합니다. RAG migration에는 pgvector 확장 생성 권한이 필요하며, 예시 Compose의 최초 DB 사용자는 이 로컬 초기화에 사용됩니다.

### 5.3 Backend: 정상 실행 확인

```bash
curl -f http://127.0.0.1:8080/health
curl -f http://127.0.0.1:8080/health/db
curl -f http://127.0.0.1:8080/health/rabbitmq
curl -f http://127.0.0.1:8081/health
curl -f http://127.0.0.1:8082/health
curl -f http://127.0.0.1:8083/health
```

`/health`는 프로세스 생존 확인입니다. DB와 큐는 `/health/db`, `/health/rabbitmq`도 성공해야 합니다. MCP의 `/health` 성공만으로 OpenDART·임베딩 호출까지 검증되지는 않습니다. `/mcp`는 MCP 프로토콜 주소이므로 일반 브라우저 GET으로 점검하지 않습니다.

- API 명세와 수동 요청: `http://127.0.0.1:8080/docs`
- RabbitMQ 관리: `http://127.0.0.1:15672`, `.env`의 RabbitMQ 계정으로 로그인

### 5.4 Backend: 최초 개발 계정 생성

회원가입 API와 기본 계정 자동 생성은 지원하지 않습니다. 새 DB에서는 조직과 사용자를 먼저 만들어야 합니다. 기존 개발 계정이 있다면 이 절차를 건너뜁니다.

**실행 위치: `backend/`. 아래는 로컬 개발 DB에만 사용하는 최초 계정 생성 예시입니다.** 비밀번호는 터미널에서 입력하며 출력되지 않습니다. 같은 이메일이 있으면 기존 계정을 변경하지 않습니다.

```bash
docker compose -f docker-compose.local.yml exec business-api python -c '
from getpass import getpass
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_engine
from app.core.security import hash_password
from app.models import Organization, User
from app.models.enums import UserRole

email = "ra.local@example.com"
password = getpass("개발 계정 비밀번호: ")
if not password:
    raise SystemExit("빈 비밀번호는 사용할 수 없습니다.")
with Session(get_engine()) as session, session.begin():
    if session.scalar(select(User).where(User.email == email)):
        raise SystemExit("동일 이메일이 있습니다. 기존 비밀번호로 로그인하세요.")
    organization = Organization(name="Local Demo Team")
    session.add(organization)
    session.flush()
    session.add(User(
        organization_id=organization.id,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.RA,
    ))
print("개발 계정 생성 완료:", email)
'
```

### 5.5 AI: 의존성 설치 및 모델 준비

새 터미널을 열고 프로젝트 루트에서 실행합니다. 4.3절의 `ai/.env` 설정을 먼저 완료합니다.

```bash
cd ai
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

분석 모델은 OpenAI API로 호출하므로 모델 가중치를 별도로 다운로드하지 않습니다. `OPENAI_MODEL`과 사용 가능한 API 키를 설정합니다. RAG 임베딩 모델은 `backend/.env`의 `RAG_EMBEDDING_MODEL`로 지정하며 기본값은 `text-embedding-3-small`입니다.

### 5.6 AI: Worker 실행 및 확인

AI 소스는 `os.environ`에서 설정을 읽고 **`.env`를 자동 로드하지 않습니다.** `ai/`에서 다음을 실행합니다. `source`로 읽을 수 있도록 `.env`는 `이름=값` 형식으로 쓰고, 공백 등이 있는 값은 따옴표로 감쌉니다.

```bash
set -a
source .env
set +a
mkdir -p outputs
.venv/bin/python -m disclosure_ai.worker --state "$PWD/outputs/ai-state.sqlite"
```

터미널을 계속 열어 둡니다. 처리할 작업이 없으면 대기합니다. Worker는 작업마다 메모 버전과 공시 접수번호를 고정하고, 상태·체크포인트·보고서를 로컬 SQLite에 보존합니다. `outputs/ai-state.sqlite`와 관련 체크포인트 파일을 보존하고, 같은 파일을 사용하는 Worker는 하나만 실행합니다.

RabbitMQ 관리 화면에서 `analysis.tasks`의 Consumer 연결을 확인할 수 있습니다. 큐가 아직 없다면 먼저 `GET /health/rabbitmq`로 Backend의 큐 초기화가 성공하는지 확인합니다.

### 5.7 AI: 선택 실행 방법

- **특정 작업 한 건 실행/재저장:** 큐 Consumer를 종료한 뒤 같은 `ai/` 설정과 같은 상태 파일로 아래 명령을 실행합니다. 실제 Backend에 존재하는 UUID로 바꾸세요. 저장된 로컬 보고서가 있으면 이를 재사용합니다. 이미 종료된 작업은 상태에 따라 재실행되지 않습니다.

```bash
.venv/bin/python -m disclosure_ai.worker \
  --state "$PWD/outputs/ai-state.sqlite" \
  --task-id '실제_작업_UUID'
```

- **Backend 없이 AI만 확인:** 고정 메모 JSON과 별도로 확보한 OpenDART 원문 ZIP이 필요합니다. 프로젝트 전체 ZIP이나 기획 PDF를 `--filing`에 넣으면 안 됩니다. 입력 형식은 [AI README](ai/README.md)의 설정과 실행 항목을 참고합니다.

```bash
.venv/bin/python -m disclosure_ai.local \
  --input /실제/경로/input.json \
  --filing /실제/경로/opendart-document.zip \
  --state "$PWD/outputs/local-state.sqlite"
```

이 경로도 모델 호출용 OpenAI 키가 필요하며, `LOCAL_SAVED` / `PENDING_BACKEND`는 **로컬 보존·업무 DB 저장 대기**입니다.

- **선택적 AI HTTP API:** 기본 RabbitMQ 흐름과 별도 방식입니다. 필요한 경우에만 최소 32자 임의 `AI_INTERNAL_TOKEN`을 설정하고 실행합니다. Worker와 동시에 같은 상태 파일을 사용하지 말고 별도 파일로 지정합니다.

```bash
export AI_STATE_PATH="$PWD/outputs/ai-api-state.sqlite"
export AI_INTERNAL_TOKEN='직접_생성한_32자_이상의_임의_토큰'
.venv/bin/uvicorn disclosure_ai.api:app --host 127.0.0.1 --port 8000 --workers 1
```

`GET /health`로 기동을 확인합니다. 내부 분석 요청에는 `Authorization: Bearer <사용자 JWT>`와 `X-AI-Token`이 필요합니다. 이 토큰을 Frontend에 넣거나 현재 웹 연결의 대체 수단으로 사용하지 않습니다.

### 5.8 Frontend: 설치·실행·정상 확인

**실행 위치: `frontend/`. Backend 없이 화면만 확인할 수 있습니다.**

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

**터미널 3개를 열고, 각각 프로젝트 루트(`ai/`, `backend/`, `frontend/`가 있는 폴더)에서 시작합니다.** 먼저 Docker를 실행합니다.

#### 처음 실행하기 전: 필수 설정

다음 설정을 한 번 완료해야 아래 명령을 실행할 수 있습니다.

| 순서 | 준비할 파일 | 해야 할 작업 |
| --- | --- | --- |
| 1 | `backend/.env` | 4.2절에 따라 `.env.example` 복사 후 DB·큐 비밀번호, JWT·내부 인증키, OpenDART·OpenAI 키 입력 |
| 2 | `ai/.env` | 4.3절에 따라 복사 후 OpenAI 키, Backend와 같은 큐 계정·비밀번호, MCP 주소 입력 |
| 3 | `backend/docker-compose.local.yml` | 5.1절의 생성 명령 실행. 원본 Compose의 중복 항목 정리 및 MCP 포트 공개 |

위 파일은 실행 명령이 자동 생성하지 않습니다. 예시 키를 실제 값으로 바꾸고 다음 단계로 진행합니다.

#### 터미널 1: Backend 실행

프로젝트 루트에서 다음 명령을 순서대로 실행합니다. Docker 이미지 안에 Backend Python 의존성이 설치됩니다.

```bash
cd backend
docker compose -f docker-compose.local.yml config --quiet
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml up -d --wait postgres rabbitmq
docker compose -f docker-compose.local.yml run --rm --no-deps business-api alembic upgrade head
docker compose -f docker-compose.local.yml run --rm --no-deps rag-mcp alembic upgrade head
docker compose -f docker-compose.local.yml up -d --wait
curl -f http://127.0.0.1:8080/health/db
curl -f http://127.0.0.1:8080/health/rabbitmq
```

**완료 기준:** 마지막 두 요청이 모두 HTTP 200으로 응답합니다. 실패하면 AI 실행 전에 Backend 로그를 확인합니다. 최초 설치에서는 5.4절의 개발 계정 생성도 실행합니다.

설치와 DB 초기화가 끝난 다음부터는 이 터미널에서 `docker compose -f docker-compose.local.yml up -d --wait`로 다시 시작하면 됩니다. 새 migration이 생겼다면 해당 migration도 적용합니다.

#### 터미널 2: AI 실행

새 터미널의 프로젝트 루트에서 실행합니다. 처음에는 가상환경 생성과 의존성 설치를 진행합니다.

```bash
cd ai
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
set -a
source .env
set +a
mkdir -p outputs
.venv/bin/python -m disclosure_ai.worker --state "$PWD/outputs/ai-state.sqlite"
```

**완료 기준:** 프로세스가 종료되지 않고 작업을 기다리며 RabbitMQ 관리 화면의 `analysis.tasks`에 Consumer가 연결됩니다. AI는 별도 웹 주소가 없는 Worker입니다. 이 터미널은 열어 둡니다.

다음 실행부터는 가상환경 생성과 의존성 설치 두 줄을 생략합니다. `source .env`를 포함한 환경 로드와 Worker 명령은 매번 실행합니다.

#### 터미널 3: Frontend 실행

새 터미널의 프로젝트 루트에서 실행합니다.

```bash
cd frontend
npm ci
npm run dev
```

**완료 기준:** 터미널에 개발 서버 주소가 출력됩니다. 브라우저에서 **`http://127.0.0.1:5173`**에 접속합니다. 다음 실행부터는 의존성이 바뀌지 않았다면 `npm ci`를 생략할 수 있습니다.

#### 실제 분석 요청

서비스를 켜는 것만으로 분석이 시작되지는 않습니다. **`http://127.0.0.1:8080/docs`**에서 로그인하고, 7.2~7.5절 순서로 메모 업로드 → 분석 요청 → 진행 조회 → 보고서 저장을 확인합니다.

현재 웹은 샘플 서비스에 연결되어 있습니다. 화면에서 실제 분석을 요청하려면 6.2~6.4절의 HTTP adapter와 API 계약을 연결해야 합니다. 웹의 샘플 분석 버튼과 실제 큐 분석은 별도로 동작합니다.

### 6.2 Frontend의 HTTP adapter 연결

1. `frontend/src/services/contracts.ts`의 `Services` 계약을 기준으로 `src/services/http.ts` 같은 adapter를 구현합니다.
2. `src/services/index.ts`의 `createMockServices(...)`를 실제 서비스 생성 함수로 교체합니다. 현재는 이 위치에서 샘플 구현이 항상 선택됩니다.
3. 실제 로그인 폼에서 `/api/v1/auth/login`을 호출하고 JWT를 요청 헤더에 전달합니다. 현재 `LoginView.vue`의 데모 사용자 선택은 서버 인증을 수행하지 않습니다.
4. `snake_case` 응답을 화면의 `camelCase` 모델로 변환합니다. 메모·공시 목록 응답과 버전 본문 응답은 분리되어 있으므로 필요한 버전 조회도 수행합니다.
5. 서버 오류의 `error.code/message`, 422 응답의 `detail`, 401/403과 토큰 만료를 화면 오류로 처리합니다.

인증된 요청 형태의 최소 예시는 다음과 같습니다. 실제 adapter에는 응답 검사와 오류 변환이 추가로 필요합니다.

```ts
const response = await fetch('/api/v1/memos', {
  headers: { Authorization: `Bearer ${accessToken}` },
})
```

### 6.3 API 경로와 데이터 계약

| 화면 기능 | 현재 서버 API | 연결할 때 필요한 작업 |
| --- | --- | --- |
| 로그인 | `POST /api/v1/auth/login` | 실제 계정 입력·JWT·만료 처리 |
| 공시 목록·본문 | `GET /api/v1/filings`, `/{id}/versions/{version}` | DB 캐시 기반. 실시간 OpenDART 전체 목록 조회로 취급하지 않음 |
| 메모 목록·본문 | `GET /api/v1/memos`, `/{id}/versions/{version}` | nullable 회사명·버전 본문을 화면 모델로 변환 |
| 메모 업로드 | `POST /api/v1/memos` | `FormData`의 `file`, 선택 `title` 사용. Content-Type은 브라우저에 맡김 |
| 분석 시작 | `POST /api/v1/analyses` | 실제 메모 UUID와 공시 접수번호 사용. `base_memo_version`은 서버가 고정 |
| 작업 진행 | `GET /api/v1/analyses/{task_id}` | 상태·단계 표시. 현재 응답에는 전체 관점 결과나 보고서 본문이 없음 |
| 이벤트 | `GET /api/v1/analyses/{task_id}/events`, `/events/stream` | sequence와 SSE payload를 화면 상태로 변환 |
| 취소 | `POST /api/v1/analyses/{task_id}/cancel` | 요청자 권한·종료 상태 처리 |
| 기업 목록·관심종목·문서 읽음 | 현재 대응 공개 API 없음 | 기업 식별·관계 및 사용자별 저장 계약 추가 |
| 분석 이력 전체 목록 | 현재 `GET /api/v1/analyses` 없음 | 조직/사용자 범위의 목록 API 추가 |
| 보고서·관점 결과 조회 | 현재 사용자용 조회 API 없음 | 접근 권한을 적용한 조회 API 및 화면 DTO 설계 |
| 보고서 저장 재시도 | 현재 사용자용 공개 API 없음 | 로컬 보고서 보존을 활용하는 서버 재시도 경로 설계 |
| 승인 후 메모 새 버전 | 현재 공개 API/UI 미구현 | 승인 권한·감사 기록·새 버전 생성 계약 구현 |

내부 `/internal/analyses/...` API나 MCP를 브라우저에 직접 연결하지 않습니다. `INTERNAL_API_KEY`를 웹에 노출하지 말고 사용자 인증을 적용한 공개 API를 추가합니다.

**분석 시작 입력:** 화면의 `StartAnalysisInput`은 `filingId`, `memoId`, `memoVersion`을 사용하지만 현재 서버 요청은 `memo_id`, `disclosure_receipt_no` 두 항목만 받습니다. adapter가 선택 공시의 `receiptNo`를 찾아 변환해야 합니다. 접수번호가 없는 샘플은 실제 요청 대상으로 사용할 수 없습니다. 화면에서 선택한 과거 버전을 서버가 분석한다고 표시하면 안 되며, 과거 버전 선택이 필요하면 API 계약을 확장해야 합니다.

**SSE 인증:** 서버는 Bearer 헤더를 요구하며 토큰 query parameter를 허용하지 않습니다. 기본 브라우저 `EventSource`에는 임의 Authorization 헤더를 넣을 수 없으므로 `fetch`의 스트림과 Bearer 헤더를 사용하거나 같은 인증을 지원하는 SSE 클라이언트를 구현합니다. 재연결 시 마지막 `sequence`를 `after_sequence` 또는 `Last-Event-ID`로 전달하고 중복 이벤트를 제거합니다.

**분석 관점 불일치:**

| 구분 | 현재 값 |
| --- | --- |
| Frontend·기획의 관점 | `BUSINESS_INDUSTRY`, `FINANCE`, `EXTERNAL_RISK` |
| Backend·AI의 관점 | `INDUSTRY_CONTRACT`, `FINANCE`, `FX_HEDGE` |

기업·산업과 산업·계약, 외부 위험과 환헤지는 범위가 다릅니다. 라벨만 치환하지 말고 공통 관점 정의를 먼저 확정해야 합니다. Frontend 타입, Backend Enum/DB 제약/migration, AI 스키마·프롬프트를 함께 맞춥니다.

### 6.4 주소·포트·API 경로 점검

| 확인 구간 | 일치해야 하는 설정 |
| --- | --- |
| Frontend → Backend | Vite proxy target `http://127.0.0.1:8080`, adapter 요청 `/api/v1/...` |
| Backend → RabbitMQ → AI | 계정·비밀번호, `analysis.exchange`, `analysis.tasks`, 재시도 횟수 |
| AI → Business MCP | `BUSINESS_MCP_URL=http://127.0.0.1:8081/mcp`와 호스트 포트 8081 |
| AI → RAG / External MCP | `/mcp` 경로, 각각 호스트 포트 8082 / 8083 |
| Business MCP → Backend | 내부 `BUSINESS_API_BASE_URL=http://business-api:8080`, 동일 `INTERNAL_API_KEY` |
| Backend / RAG → DB | Docker 내부 `postgres:5432`, 사용자·비밀번호·DB 이름 |

AI의 `RABBITMQ_URL`에는 호스트 주소 `127.0.0.1`, Backend에는 Docker 서비스 주소 `rabbitmq`를 사용합니다. MCP의 포트 공개와 허용 호스트 설정도 실제 접속 주소에 맞아야 합니다.

### 6.5 종료

Frontend와 AI 터미널에서 각각 `Ctrl+C`를 누릅니다. Backend는 `backend/`에서:

```bash
docker compose -f docker-compose.local.yml down
```

이 명령은 DB·큐의 이름 있는 볼륨을 보존합니다. 다음 실행과 저장 재시도를 위해 AI 상태 파일도 보존합니다. `down -v`는 DB·큐 데이터를 삭제하므로 일반 종료에는 사용하지 않습니다.

## 7. 연동 테스트

### 7.1 화면 기능 확인

화면 시연 순서:

1. `/login`에서 데모 사용자를 선택합니다. 실제 계정 로그인은 수행하지 않습니다.
2. 기업 목록에서 엘앤에프 또는 삼성중공업을 선택합니다.
3. 공시·메모를 열고 대상 문서와 기준 버전을 선택합니다.
4. 분석을 시작해 단계·선택 관점·샘플 보고서를 확인합니다.
5. 근거 원문과 미확인 사항, 메모 탭·분석 이력을 확인합니다.

샘플 업로드·생성 작업·보고서는 메모리에 있으며 새로고침 시 초기화됩니다. 사용자 선택·관심종목·읽음 기록 일부는 브라우저에 남습니다. 실제 메모와 보고서의 서버 저장은 Backend API 연동 후 지원합니다.

API adapter 연결 전에는 위 절차가 샘플 시연입니다. 연결 후에는 브라우저 개발자 도구의 Network에서 실제 `/api/v1/analyses` 요청과 `task_id`를 확인하고, 아래 절차로 같은 작업의 이벤트와 DB 저장을 대조합니다.

Frontend의 샘플 버튼과 별개로 **API 요청으로 실제 Backend → RabbitMQ → AI → MCP → DB 경로를 확인**합니다. 5장의 Backend와 AI Worker가 모두 실행 중이어야 합니다.

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

기업·작성일·기존 가정이 포함된 테스트 메모를 UTF-8 `.txt`로 준비합니다. 최대 크기는 기본 5 MiB이며 PDF·DOCX는 현재 업로드 대상이 아닙니다.

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

정상 접수 시 HTTP `202`, `task_id`, `status: QUEUED`를 반환합니다. `202`는 큐 발행 성공이며 분석 완료를 뜻하지 않습니다. API는 접수번호의 형식만 검사하므로 유효한 공시와 원문 제공 여부는 실제 조회 시 확인됩니다.

```bash
export TASK_ID='분석_응답의_task_id_UUID'

curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl -fS "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/events" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl -N "http://127.0.0.1:8080/api/v1/analyses/$TASK_ID/events/stream" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

SSE 조회는 계속 열려 있을 수 있으며 `Ctrl+C`로 종료합니다. 정상 경로는 `QUEUED → RUNNING → SAVING → COMPLETED` 또는 `COMPLETED_WITH_WARNINGS`입니다. 조회 제한·미구현 도구·근거 부족 등으로 경고나 실패가 발생할 수 있으므로 상태와 이벤트를 함께 확인합니다.

### 7.5 실제 연동: 보고서 저장 확인

현재 사용자용 API에는 보고서 조회 endpoint가 없습니다. 개발 확인은 **`backend/` 터미널에서** DB를 조회합니다. 아래 SQL의 UUID를 실제 `task_id`로 바꿉니다.

```bash
docker compose -f docker-compose.local.yml exec postgres \
  psql -U disclosure -d disclosure -c \
  "SELECT analysis_task_id, saved_at, has_warnings, content, report_json
   FROM core.analysis_reports
   WHERE analysis_task_id = '실제_작업_UUID';"
```

`POSTGRES_USER`, `POSTGRES_DB`를 바꿨다면 `-U`, `-d`도 수정합니다. 보고서 한 건과 `saved_at`을 확인하고, 업로드한 원문은 `GET /api/v1/memos/{memo_id}/versions/1`의 `content`로 재확인합니다. 보고서 생성과 기존 메모의 승인·수정 반영은 별도 기능입니다.

Backend 로그는 다음과 같이 확인합니다.

```bash
docker compose -f docker-compose.local.yml logs --tail=100 \
  business-api business-mcp external-mcp rag-mcp
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
3. 상태가 `RUNNING`으로 변경되고 입력 조회·분석·저장 이벤트가 기록됩니다.
4. `COMPLETED` 또는 `COMPLETED_WITH_WARNINGS`로 종료됩니다.
5. `core.analysis_reports`에 보고서와 `saved_at`이 저장됩니다.
6. 웹 API 연결 후에는 같은 서버 보고서가 화면에 표시됩니다.

`COMPLETED_WITH_WARNINGS`이면 미구현 도구·근거 부족 등 경고 내용을 함께 확인합니다. 샘플 화면만 실행한 결과는 실제 연동 완료에 포함하지 않습니다.

### 7.7 웹 연동 확인 항목

- [ ] 화면 로그인으로 실제 서버 JWT를 얻고 비로그인·만료 상태를 처리한다.
- [ ] 샘플 서비스 대신 실제 API adapter를 사용하며 실제 UUID·접수번호로 요청한다.
- [ ] 업로드한 메모가 새로고침 후에도 서버에서 조회된다.
- [ ] 화면의 분석 시작 요청이 `202`와 실제 `task_id`를 반환한다.
- [ ] Worker가 해당 작업을 수신하고 실제 이벤트가 화면에 나타난다.
- [ ] 서버에서 조회한 보고서와 근거를 표시하고 샘플 보고서와 혼동하지 않는다.
- [ ] 관점·버전·기업 연결의 계약 불일치를 해결한다.
- [ ] 근거 부족·분석 실패·저장 실패·저장 재시도를 구분한다.

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

외부 DB/Broker 통합 테스트는 별도의 폐기 가능한 테스트 환경이 필요합니다. 일반 개발 DB에 테스트용 초기화·migration 왕복 검증을 실행하지 않습니다. UI 테스트 통과와 실제 모델·MCP·웹 전체 E2E 통과는 서로 다른 검증입니다.

## 8. 자주 발생하는 오류와 해결 방법

| 증상 | 확인 및 해결 |
| --- | --- |
| `mapping key "postgres" already defined` | 원본 Compose 중복 항목 오류. 5.1로 실행 파일을 만들고 모든 명령에 `-f docker-compose.local.yml` 지정 |
| `FileExistsError: docker-compose.local.yml` | 이미 생성한 파일이 있음. 기존 내용을 확인하고 재사용. 생성 명령을 다시 실행할 필요 없음 |
| Docker 연결 실패 | Docker 엔진이 실행 중인지 확인 |
| 5173/8080/8081~8083/5672 포트 충돌 | 해당 포트 사용 프로그램을 종료하거나 관련 호스트 포트·접속 URL을 함께 변경 |
| Frontend만 실행했는데 보고서가 나옴 | 현재 mock 데이터 흐름. 실제 AI 실행 여부는 API 작업 ID·Worker·DB 저장으로 확인 |
| `.env`를 작성했는데 AI 키가 없음 | AI는 `.env` 자동 로드 없음. `ai/`에서 `set -a`, `source .env`, `set +a` 후 실행 |
| `MCP_UNAVAILABLE` | AI URL이 localhost인지, 5.1의 포트 공개 여부·MCP health·컨테이너 로그 확인 |
| `QUEUED`에서 진행되지 않음 | Worker 기동 여부와 큐 Consumer 수 확인. 양쪽 RabbitMQ URL·계정·교환기·큐 일치 확인 |
| `BROKER_RECONNECT` 반복 | RabbitMQ health·호스트 포트·AI의 비밀번호 및 URL 호스트 확인 |
| 로그인 실패/인증 설정 오류 | 실제 계정 존재, 비밀번호, 32바이트 이상의 JWT 키 확인. 데모 로그인 선택은 서버 계정 생성이 아님 |
| 내부 인증 오류 | Business API와 Business MCP의 `INTERNAL_API_KEY` 일치 및 컨테이너 재생성 여부 확인 |
| DB 테이블·`rag`·vector 오류 | Business API와 RAG migration을 각각 적용했는지 확인. DB 확장 생성 권한 확인 |
| DB/큐 비밀번호를 바꿨는데 인증 실패 | 기존 볼륨은 최초 자격 증명을 유지할 수 있음. 기존 서비스 계정과 `.env`를 맞추거나 서비스의 계정 변경 절차 사용 |
| OpenDART 원문 조회 실패 | 실제 키·접수번호·원문 제공 여부 확인. `014`는 해당 공시 원문이 제공되지 않는 경우를 확인 |
| `TOOL_NOT_AVAILABLE` / 일부 분석 미완료 | 재무·학술 추가 조회 도구가 미구현. 확보한 근거와 보고서 경고를 확인 |
| `409 ANALYSIS_ALREADY_RUNNING` | 같은 메모 버전·접수번호에 진행 작업이 있음. 응답의 `existing_task_id`로 기존 작업 조회 |
| SSE가 브라우저에서 인증 실패 | JWT 헤더를 지원하는 스트림 구현 사용. 토큰을 URL에 넣지 않음 |
| CORS/화면에서 API 호출 실패 | 4.4의 개발 프록시와 adapter의 `/api` 상대경로 확인 |
| `SAVE_FAILED` | 같은 AI 상태 파일의 보고서 보존 확인 후 단일 작업 재저장. 공개 웹 재시도 API는 별도 구현 필요 |
| SQLite 잠금 오류 | 같은 상태 파일을 사용하는 Worker·선택적 API의 중복 실행 종료 |
| 업로드 415/413/422 | UTF-8 `.txt`, `text/plain`, 기본 5 MiB 한도, multipart의 `file` 필드 확인 |
| 모델 호출 실패 | `OPENAI_API_KEY` 로드 여부, `OPENAI_MODEL` 접근 권한, 네트워크·호출 한도 확인. 이 구성에는 로컬 모델 가중치 로딩 단계가 없음 |

### 관련 문서

- [AI 상세 설명](ai/README.md)
- [Backend 상세 설명](backend/README.md)
- [Business API 상세 설명](backend/business-api/README.md)
- [Business MCP 상세 설명](backend/mcp/business-mcp/README.md)
- [External MCP 상세 설명](backend/mcp/external-mcp/README.md)
- [RAG MCP 상세 설명](backend/mcp/rag-mcp/README.md)
- [Frontend 상세 설명](frontend/README.md)
