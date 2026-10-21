# API Key 설정 위치

실제 Key는 example 파일이 아닌 로컬 `.env`에 기록합니다. Key를 채팅, 코드, 커밋에 넣지 않습니다.
기존 파일이 있으면 덮어쓰지 말고 필요한 항목만 추가합니다.

## Backend: backend/.env

```dotenv
OPENDART_API_KEY=<OpenDART에서 발급받은 키>
SERPAPI_API_KEY=<SerpApi 키>
OPENAI_API_KEY=<OpenAI API 키>
```

- OpenDART: External MCP의 get_disclosure가 사용합니다.
- SerpApi: External MCP의 search_academic_papers가 Google Scholar 검색에 사용합니다. Google/Gemini/OpenAI 키와 별개입니다.
- OpenAI: RAG MCP embedding(text-embedding-3-small)이 사용합니다. GPT 생성 모델 설정과 별개입니다.

```bash
cd backend
docker compose up -d --build external-mcp rag-mcp
```

Compose가 backend/.env를 변수 치환에 사용하고 필요한 Key만 해당 서비스 environment에 전달합니다.
External MCP에는 OpenAI Key를 전달하지 않습니다. Standalone 실행 시 해당 서비스 cwd의 .env 또는 shell 환경변수를 사용합니다.

## GPT Agent: ai/.env

현재 Agent 구현 경로는 ai/입니다. ai-agent/는 존재하지 않습니다.

```dotenv
OPENAI_API_KEY=<OpenAI API 키>
OPENAI_MODEL=gpt-4.1-mini
BUSINESS_MCP_URL=http://127.0.0.1:8081/mcp
EXTERNAL_MCP_URL=http://127.0.0.1:8083/mcp
RAG_MCP_URL=http://127.0.0.1:8082/mcp
```

OPENAI_MODEL은 현재 코드의 기본값을 적었습니다. 계정에서 사용할 모델 ID로 변경할 수 있습니다.
AI runtime은 os.environ을 읽으므로 .env 파일을 작성하는 것만으로 자동 로딩되지는 않습니다.
설치된 환경에서 다음처럼 명시적으로 전달합니다.

```bash
cd ai
uv run --env-file .env python -m disclosure_ai.entrypoints.worker --state outputs/ai-state.sqlite
```

Worker 실행에는 ai/.env.example의 RabbitMQ 설정 등도 필요합니다.
위 127.0.0.1 URL은 호스트 실행 예시이며 현재 Compose의 MCP 포트는 호스트에 publish되지 않습니다.
호스트에서 Agent를 실행한다면 MCP도 호스트에서 직접 실행하거나 개발용 Compose override로
각 포트를 127.0.0.1에 publish해야 합니다. 컨테이너 실행 시 같은 Docker 네트워크의 서비스 DNS를 사용합니다.

GPT 호출 및 OpenDART 호출은 이미 코드에 연결되어 있습니다.
학술 검색의 Agent academic 분기는 아직 TOOL_NOT_AVAILABLE이며 별도 Agent 연결 작업이 필요합니다.
실제 Key를 읽거나 외부 유료 API를 호출하여 확인하지 않았습니다.

## 환경설정 동기화 원칙

backend/.env와 .env.example은 항목·순서·설명이 같으며, 실제 키/로컬 값만 다릅니다.
.env.example의 빈 API Key 및 JWT/Internal secret placeholder는 실제 값으로 교체해야 합니다.
.env에 이미 있던 값은 동기화 중 보존했습니다. PostgreSQL/RabbitMQ credential과 연결 URL은 서로 일치해야 합니다.
MCP 포트를 변경하면 BUSINESS_MCP_URL / EXTERNAL_MCP_URL도 해당 포트로 함께 수정합니다.
Compose는 위 URL과 BUSINESS_API_BASE_URL 설정을 그대로 전달합니다.
