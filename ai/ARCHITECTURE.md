# AI 코드 구조와 확장 방법

현재 구현은 하나의 AI 프로세스 안에서 역할별 모듈을 분리한다. 기본 실행은 RabbitMQ Worker이며 HTTP와 로컬 실행은 추가 진입점이다. 업무 DB의 상태와 조직 권한은 기존 Business API가 소유한다.

## 계층별 책임

| 위치 | 책임 | 주요 진입점 |
| --- | --- | --- |
| `presentation` | HTTP, 큐, CLI 입력 처리 | `http/controllers/analysis_controller.py`, `queue/consumer.py`, `cli/local.py` |
| `application` | 고정 입력 확인, 실행·재개·저장 복구 조율 | `services/execute_analysis.py`, `services/analysis_service.py`, `services/http_analysis.py` |
| `domain` | 근거, 제안, 관점 모델과 순수 검증 정책 | `models/`, `policies/` |
| `workflow` | LangGraph 상태, reducer, 순서, 분기, 병렬 실행 | `state.py`, `routing.py`, `graph.py`, `nodes/` |
| `analysis` | 자료 준비, 영향 분석, 관점 분석, 보고서 생성 | `inputs/`, `impact/`, `perspectives/`, `evidence/`, `reporting/` |
| `llm` | 프롬프트, 구조화 모델 응답, 내부 결과 변환 | `prompts/`, `schemas/analysis.py`, `mappings.py` |
| `ports` | 모델, 업무·공시·근거 조회, 실행 저장과 그래프 계약 | `model_gateway.py`, `execution.py`, `run_repository.py` 등 |
| `runtime` | 시간·토큰·턴 예약, 조회 공유, 재시도, 취소 전달 | `budget.py`, `model_executor.py`, `tool_executor.py`, `cache.py`, `transport.py` |
| `infrastructure` | OpenAI, MCP, SQLite, RabbitMQ와 체크포인트 구현 | `openai/`, `mcp/`, `persistence/`, `messaging/`, `checkpoint/` |
| `bootstrap.py` | 기본 실행 의존성 조립 | `build_dependencies()`, `build_model_gateway()` |

실행 경로는 `Controller/Message Handler → Application → Graph → Node → Analysis Service`다. Node는 필요한 입력을 추출하여 서비스에 넘기고 변경값을 반환한다. 기본 분석, 관점 분석, 보고서 생성 서비스는 Graph State 전체 대신 명시적인 입력을 받는다. 공유 조회 결과 취합과 복구 함수는 기존 체크포인트 호환을 위해 상태 사전을 사용한다.

Domain은 HTTP, 모델 SDK, MCP, LangGraph, 저장소에 의존하지 않는다. Application과 Analysis는 구체적인 외부 Adapter를 import하지 않는다. Infrastructure는 내부 계약을 구현한다. 실제 연결은 Bootstrap 또는 진입점에서 수행한다. 기존 Harness 생성 방식에는 기본 모델 Gateway를 지연 생성하는 호환 경로가 남아 있다.

## 모델 응답과 검증된 결과

- HTTP 입력은 `presentation/http/schemas/requests.py`에 둔다. 현재 내부 Command와 필드가 같으므로 이를 상속하며, 별도 HTTP 클래스로 관리한다.
- 고정 실행 입력은 `application/commands/analyze_disclosure.py`에 둔다.
- LLM JSON 형식은 `llm/schemas/analysis.py`에서 관리한다. `llm/mappings.py`가 사전 형태의 후보 결과를 만든 다음 Domain 정책이 메모 연결과 근거를 검증한다.
- Domain 모델과 Graph State는 JSON으로 보존할 수 있는 TypedDict를 사용한다. SDK 객체나 ORM 세션은 State에 넣지 않는다. TypedDict 자체는 런타임 검증기가 아니며 실제 검증은 입력 스키마와 정책이 담당한다.
- 보고서 초안·검사는 `analysis/reporting/service.py`, `grounding_review.py`, 표현은 `renderer.py`가 담당한다.

## 관점 확장

기존 관점의 제목, 공개 학술 검색어와 허용 도구는 `analysis/perspectives/definitions/`에 있으며 `registry.py`에서 등록한다. 도구 요청은 `domain/policies/tool_permission_policy.py`가 관점의 허용 목록을 확인한 뒤 인자를 구성한다. 모델이 요청했다고 바로 외부 호출하지 않는다.

새 관점을 제품 전체에 추가하려면 다음을 함께 반영한다.

1. `PerspectiveDefinition`을 만들고 Registry에 등록한다. 중복 키는 거절한다.
2. `domain/enums.py`의 관점 Literal과 기본 분석·관점 프롬프트를 갱신한다.
3. 새 자료가 필요하면 해당 Port와 Adapter를 확장한다.
4. Business API/DB/Frontend의 관점 허용 계약도 함께 갱신한다. AI Registry 등록만으로 전체 서비스가 새 관점을 허용하는 것은 아니다.
5. 선택 기준, 금지할 추론과 근거 부족 사례를 평가셋에 추가한다.

공통 분석 방식으로 처리할 수 있는 관점은 기존 Graph와 공통 관점 Node를 그대로 사용한다. 독립된 실행 절차가 필요한 경우에만 전용 서비스나 서브그래프를 추가한다.

## 모델 및 자료 제공처 교체

`ModelGateway`는 내부 `ModelResponse`와 내부 예외를 사용한다. OpenAI SDK 응답과 오류는 Adapter에서 변환한다. `Harness(..., model_gateway=...)`로 다른 Gateway를 주입해도 Runtime의 예약·재시도·출력 검증 정책을 유지한다. 주입한 Gateway의 `close()`는 Harness가 호출한다.

`Tools`는 기존 문자열 도구 계약을 유지하는 Facade다. 내부에서는 Business, External, RAG Adapter로 분리하고 External/RAG 구현을 독립적으로 주입할 수 있다. 업무 메서드의 HTTP 호출 및 상태 전이는 Business Adapter가 처리한다. 향후 타입이 있는 업무별 메서드로 전환할 때도 기존 체크포인트의 도구 이름과 인자를 마이그레이션해야 한다.

`RunRepository`는 실행 기록의 계약이며 현재는 SQLite의 `db`와 `lock`을 노출한다. 예산·조회 예약의 원자성에 관한 기존 동작을 유지하기 위한 경계다. PostgreSQL 등으로 바꾸려면 이 두 속성을 그대로 흉내 내기보다 저장소 내부의 원자적 예약 메서드로 계약을 확장해야 한다. 단순 Adapter 교체만으로 다중 Worker를 지원하지 않는다.

## 호환과 이번 변경의 범위

`entrypoints/`, `harness/`, `services/`, 기존 `workflow/initial.py`, `perspectives.py`, `shared.py`, `reporting.py`, `execution.py`, `schemas.py`는 기존 import와 실행 명령을 위한 호환 경로다. 새 코드는 각 책임을 소유하는 경로를 import한다. 공개 함수는 호환 경로에서 같은 구현을 참조해 기존 테스트의 대체 객체 주입도 유지한다.

기존 `python -m disclosure_ai.entrypoints.worker`, `python -m disclosure_ai.entrypoints.local`과 `uvicorn disclosure_ai.entrypoints.api:app`을 유지한다. 설치 명령은 새 Presentation 경로로 연결된다. 프롬프트는 wheel의 `llm/prompts/*.md`에 포함한다.

S1/S2/S3 노드 이름, 직렬화된 상태 필드, 실행 ID, 예산, 조회 횟수, 모델 기본값, 보고서 및 백엔드 계약은 유지한다. 회계 등 새 분석 관점을 실제 활성화하거나 분석 판단을 바꾸는 변경은 포함하지 않는다. 기존 분석에서 확인한 경고 누락, SEC 추가 조회 날짜 처리, 최종 검사 예산과 긴 문맥 축약 정책도 이번 구조 변경과 분리한 후속 과제다.

## 검증

```bash
uv sync --extra dev
uv run pytest tests -q
uv run ruff check disclosure_ai tests
uv run ruff format --check disclosure_ai tests
```

기존 회귀 검사는 원래 위치에 유지한다. 새 검사는 `tests/unit`에서 의존성 방향, `tests/integration`에서 교체 가능한 Gateway와 실행 의존성, `tests/evaluation`에서 관점 및 제안 정책을 확인한다. 로컬 MCP 검사는 로컬 서버 포트가 필요하고, 첫 실행의 tiktoken 사전 확보에는 네트워크가 필요하다. 실제 OpenAI 호출과 전용 PostgreSQL/RabbitMQ 연결 검증은 별도 환경이 필요하다. 모델의 분석 정확도는 정책 단위 검사만으로 입증되지 않으며 실제 Golden Set 평가를 수행해야 한다.
