# Business MCP MVP

Business MCP는 AI Agent와 Business API 사이의 HTTP Adapter입니다. DB 연결, 상태 머신,
조직 판단, Perspective 선택, Report 생성, Worker/LLM 코드를 포함하지 않습니다.

```text
AI Agent → Business MCP → Business API /internal/** → Service → Repository → PostgreSQL
```

공식 MCP Python SDK v1 (`mcp>=1.12,<2`, 검증 버전 1.30.0)의 FastMCP를 유지합니다.
Streamable HTTP, stateless + JSON response이며 endpoint는 `/mcp`입니다.
참고: [공식 SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.30.0).

## 환경변수

| 변수 | 기본값 / 용도 |
| --- | --- |
| BUSINESS_API_BASE_URL | http://business-api:8080 |
| INTERNAL_API_KEY | Business API와 동일한 32 bytes 이상 secret, placeholder 사용 불가 |
| BUSINESS_MCP_HOST | 0.0.0.0 |
| BUSINESS_MCP_PORT | 8081 |
| BUSINESS_MCP_REQUEST_TIMEOUT_SECONDS | 30 |
| MCP_ALLOWED_HOSTS | localhost:*, 127.0.0.1:*, business-mcp:* |

`INTERNAL_API_KEY`는 Tool argument가 아니며 SecretStr로 관리합니다. 전체 header/response를
로그로 dump하지 않습니다. DB URL 환경변수는 필요하지 않고 Compose에서도 전달하지 않습니다.
DNS rebinding 보호를 유지하므로 새 접속 도메인을 추가하면 MCP_ALLOWED_HOSTS도 설정합니다.
별도 MCP ingress 인증은 이 MVP에 없으므로 신뢰된 내부 네트워크에서만 사용합니다.

## 실행

backend/.env.example의 필요한 값을 로컬 backend/.env에 설정한 뒤 backend/에서 실행합니다.

```bash
docker compose up -d --build business-mcp
```

Compose 내부 endpoint는 `http://business-mcp:8081/mcp`입니다. 포트를 변경하면 해당 포트로 접속합니다.
MCP 포트는 host에 공개하지 않습니다. Business API는 내부 DNS `business-api`로 호출합니다.

독립 실행은 이 디렉터리에서 Python 3.12 이상 가상환경을 사용합니다.

```bash
python -m pip install -e ../../shared -e '.[dev]'
export BUSINESS_API_BASE_URL=http://127.0.0.1:8080
export INTERNAL_API_KEY='<Business API와 동일한 로컬 secret>'
python -m app
```

`python -m app`이 HOST/PORT 설정을 읽습니다. `/health`는 인증 없이 process liveness를 반환하며
Business API readiness를 의미하지 않습니다. Key 미설정 시 health/list는 유지하고 Tool 호출은
configuration 오류로 실패합니다. 실제 secret은 .env.example이나 저장소에 기록하지 않습니다.

## Tool 계약

경로 prefix는 `/internal/analyses/{task_id}`입니다.

| Tool | HTTP | 경로 |
| --- | --- | --- |
| get_analysis_context | GET | /context |
| get_analysis_status | GET | /status |
| report_analysis_event | POST | /events |
| update_analysis_state | POST | /state |
| register_perspective | POST | /perspectives |
| update_perspective | PATCH | /perspectives/{perspective_id} |
| save_analysis_report | POST | /report |

선택 인자의 None은 생략하고 false/빈 JSON object는 보존합니다. UUID는 경로에 안전하게 전달합니다.
상태 값·전이·조직 범위·기준 버전·멱등성은 Business API만 판단합니다. 결과는 원래 JSON object를
MCP structuredContent로 반환하며, configured API Key 또는 credential 필드는 방어적으로 제거합니다.
Report는 이미 Agent가 생성한 입력을 전달할 뿐 여기서 생성하지 않습니다.

## Client와 오류

FastAPI lifespan에 httpx.AsyncClient 한 개를 만들고 재사용한 뒤 종료합니다. timeout을 설정하고
redirect를 따라가지 않으며 환경 proxy를 자동 사용하지 않습니다. X-Internal-API-Key는 서버 설정에서만
헤더에 넣습니다. Event append 등은 멱등하지 않으므로 Adapter에서 자동 retry하지 않습니다.

ToolError는 SDK의 MCP `isError=true` 결과가 됩니다. 안전한 오류 정보는 JSON 형태로 포함됩니다.

- business_api_4xx / business_api_5xx: HTTP status와 API error.code/message를 가능한 범위에서 유지
- timeout / connection_failure: 원본 연결 예외·URL을 숨긴 고정 code/message
- malformed_response: 잘못된 JSON/object 또는 예상 밖 HTTP status
- configuration: key/client 사용 불가

Business API의 422 detail에는 application error.code가 없으므로 HTTP 422와 일반 안전 문구를 반환합니다.
Raw stack trace/HTML/credential 포함 URL은 전달하지 않습니다. Adapter의 Key redaction은 임의의
외부 secret까지 탐지하는 기능이 아니므로 Internal API도 안전한 응답 계약을 유지해야 합니다.

## 핵심 검증

```bash
python -m pytest -q
```

MockTransport와 실제 `/mcp` JSON-RPC 호출로 Tool 등록/경로/body/header/오류 변환을 검증합니다.
별도 DB/Broker/Agent나 전체 프로젝트 회귀 실행은 필요하지 않습니다.
