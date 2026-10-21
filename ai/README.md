# 정정공시 메모 영향 분석

## 1. 실습 또는 과제 요구사항

강의 자료 `AI-Agent Capstone(+MCP).pdf`의 69쪽부터 73쪽까지와 첨부 흐름도를 기준으로 구현했습니다. 고정된 메모와 정정공시를 분석하고, 필요한 관점만 병렬로 실행한 뒤 근거를 포함한 보고서를 자동 저장합니다. 원래 메모는 수정하지 않습니다.

외부 자료는 사용자가 지정한 OpenDART와 Google Scholar로 제한했습니다. 외부 API 조회 함수와 키, 업무 DB 및 RAG 저장소는 백엔드가 담당합니다. AI는 백엔드 MCP 호출과 분석 흐름을 담당합니다. 현재 재무 조회와 학술 검색 도구는 백엔드에 없어 해당 요청의 미완료 사유를 보고서에 남깁니다.

전체 분석은 120초, 입력과 출력 합계 예약 60,000토큰, 모델 8턴으로 제한합니다. 보고서용 30초와 12,000토큰 및 모델 1턴을 남깁니다. 사용자 요청에 따라 기본 분석의 최대 출력은 4,000토큰입니다. 관점 분석은 입력 6,000토큰과 출력 1,500토큰, 기본 분석과 보고서는 입력 10,000토큰, 보고서 출력은 2,000토큰입니다.

## 2. 요구사항 적용 위치

`workflow/graph.py`는 REQUEST, S1, S2, S3, REPORT_AGENT, SAVE를 연결합니다. S1은 자료 취합과 검색 준비 및 기본 분석입니다. S2는 선택된 관점의 모델 호출 한 번을 병렬로 실행합니다. S3는 STATUS, KEY, SHARED, RESULT, JOIN 노드로 조회 요청을 처리하고, 자료를 받은 관점이 있으면 S2로 돌아갑니다. 종료된 관점은 재호출하지 않습니다.

`harness/runtime.py`는 병렬 모델 호출 전에 예산을 예약하고 관점별 최대 3턴을 강제합니다. 모델 요청은 최대 20초이며 남은 시간보다 길게 실행하지 않습니다. 일시 오류는 추가 2회, 구조화 응답의 형식 복구는 1회까지 허용하고 재시도도 예산에 포함합니다.

`harness/lookup.py`는 자료 조회와 최초 보고서 저장을 호출당 최대 10초, 같은 도구 전체 최대 3회로 제한합니다. 동일한 요청의 결과와 진행 중 호출을 공유하고, 조회 대기 한도에 도달한 관점은 종료합니다. `workflow/execution.py`는 시간 초과와 예상하지 못한 실행 오류에서도 보고서를 로컬에 보존합니다.

## 3. 파일별 구현 내용

```text
ai/
├── disclosure_ai/
│   ├── entrypoints/
│   │   ├── worker.py        RabbitMQ 소비와 작업 실행
│   │   ├── api.py           선택적 내부 HTTP 접수와 결과 조회
│   │   └── local.py         제공된 메모와 ZIP의 로컬 실행
│   ├── workflow/
│   │   ├── graph.py         State와 서브그래프 연결
│   │   ├── initial.py       S1 자료 취합과 기본 분석
│   │   ├── perspectives.py  S2 관점 선택과 분석 응답
│   │   ├── shared.py        S3 공유 조회와 관점 재개
│   │   ├── reporting.py     보고서 생성과 저장, 비상 보고서
│   │   └── execution.py     공통 실행, 복구와 재저장
│   ├── services/
│   │   ├── business.py      MCP 전송과 업무 도구 매핑
│   │   ├── tools.py         허용 도구 호출과 응답 변환
│   │   └── documents.py     공시 처리와 근거 대조
│   ├── harness/
│   │   ├── runtime.py       모델 예산과 실행 한도
│   │   ├── lookup.py        조회 정규화와 동시 호출 공유
│   │   ├── ledger.py        실행 상태와 원문 및 보고서 보존
│   │   ├── transport.py     상태 동기화와 재저장 전송 제한
│   │   └── output.py        민감 정보와 투자 권유 출력 검사
│   ├── prompts/            역할별 지시문
│   ├── schemas.py          고정 입력과 모델 응답 형식
│   └── errors.py           실행 한도 오류
├── tests/                  단위 검사, 백엔드 연결과 명시적 실제 실행 검사
├── .env.example
├── pyproject.toml
└── uv.lock
```

`services/business.py`는 Business MCP의 작업 context, 상태, 이벤트, 관점과 보고서 도구를 호출합니다. `services/tools.py`는 External MCP의 get_disclosure, RAG MCP의 ensure_analysis_index와 search_evidence를 AI 문맥으로 변환합니다. 자료 ID와 원문 위치 및 공개 시점을 보존하고, 응답에 포함된 내부 오류 원문은 모델에 전달하지 않습니다.

`services/documents.py`는 공시 표와 본문을 대조하고 원문 인용을 검증합니다. 로컬 ZIP은 메모리에서 크기와 파일 수를 제한해 처리합니다. 복잡한 표가 없고 모든 정정이 허용된 공백 차이일 때만 기본 분석을 생략합니다. 금액, 날짜, 기업명과 계약 조건 및 부정 표현 변경은 일반 분석으로 진행합니다.

`harness/output.py`는 규칙 검사 후 모델에 문장별 의미 검사를 요청합니다. 이 검사도 전체 모델 예산을 사용합니다. 검사 실패나 예산 소진 시 자유 서술을 제외하고 검증된 원문과 처리 상태를 남깁니다. 원문에 들어 있는 명령은 지시로 실행하지 않습니다.

## 4. 전체 실행 및 처리 흐름

백엔드는 분석 요청의 권한과 고정 입력을 확인하고 RUN_ANALYSIS 메시지를 발행합니다. worker는 task_id로 작업을 조회한 뒤 조직과 메모 버전 및 공시 접수번호를 고정합니다. 완료되거나 취소된 작업은 재실행하지 않습니다.

S1은 공시와 메모를 병렬로 조회하고 정정표와 관련 문단을 모읍니다. RAG 색인이나 검색의 실패 사유는 보존하며 확보된 자료로 분석을 이어갑니다. 기본 분석의 수정 제안은 메모의 실제 문장과 원문 근거를 확인하고, 근거가 없으면 HOLD로 보류합니다.

S2는 관점별 응답에서 완료, 근거 부족, 추가 조회 필요를 구분합니다. 추가 조회는 S3가 처리합니다. 같은 조건의 조회는 한 번만 실행하고 결과를 요청한 관점에 반환합니다. 학술 검색어는 고정된 공개 연구 주제로 제한해 사내 메모 문장을 외부 검색으로 보내지 않습니다. 모든 선택 관점이 종료되면 보고서를 작성합니다.

보고서는 요약, 정정 내용, 메모 영향, 수정 제안, 관점 결과, 제한 사유와 출처를 포함합니다. 모델 생성 실패 시 확보한 결과로 같은 양식의 보고서를 구성합니다. 저장 요청 전에 로컬에 보존하고 같은 task_id로 업무 DB에 저장합니다. 저장 실패 시 본문을 유지하며 재저장은 모델을 다시 호출하지 않습니다.

문맥 처리 실패는 단계와 사유를 남기고 보고서 경로로 이동합니다. 전체 실행 시간이 끝났거나 그래프 실행이 중단되면 마지막 체크포인트의 원문 근거와 처리 상태로 비상 보고서를 보존합니다. 남은 시간이 없으면 네트워크 저장을 추가로 실행하지 않고 SAVE_FAILED와 TIME_LIMIT을 반환합니다. 이후 재저장 경로로 복구할 수 있습니다.

## 5. 핵심 코드의 의도와 작동 원리

공유 조회 키에는 작업 ID, 접근 범위, 도구 이름과 정규화된 인자가 포함됩니다. 검색어의 유니코드와 공백, 기준일 표기를 정리합니다. 의미가 비슷한 서로 다른 검색어까지 같은 요청으로 합치지 않습니다. 캐시를 반환하기 전에도 취소와 접근 상태를 확인합니다.

SQLite의 lookup_jobs에는 조회 시작 전에 RUNNING과 시도 횟수를 저장합니다. 완료 후 결과와 종료 상태를 보존합니다. 재시작 시 중단된 조회를 식별하고 기존 누적 횟수와 시간 안에서 다시 실행합니다. 조회는 읽기 작업이고 보고서 저장은 task_id 기준의 백엔드 중복 방지 계약을 사용합니다. URL 또는 문서 ID와 내용 및 접근 범위가 같은 원문은 source_bodies에 한 번 보관하고 캐시에서는 참조로 재사용합니다. 같은 URL이라도 내용이 바뀌면 별도 원문으로 보존합니다.

상태 조회와 단계 및 이벤트 전달은 새로운 자료를 얻는 조회와 구분됩니다. transport.py가 남은 실행 시간, 전송당 10초와 최대 3회 시도, 추적 기록을 적용합니다. 진행 상태는 최신 값이 필요해 조회 캐시를 사용하지 않습니다. 사용자 재저장은 별도 10초 작업으로 최대 3회 시도하며 같은 보고서와 작업 ID를 유지합니다. 전체 분석의 모델 예산을 초기화하지 않습니다.

실행과 조회 기록은 task_id로 연결됩니다. 토큰은 호출 전 입력과 최대 출력을 예약하고 실제 사용량은 별도 이벤트에 남깁니다. 예약값은 청구 토큰과 다릅니다. 하나의 상태 파일에는 worker 한 개를 사용합니다. 여러 호스트에서 동시에 처리하려면 공유 실행 임대와 공용 저장소가 필요합니다.

## 6. 입력, 출력과 확인 방법

Python 3.12 이상과 pyproject.toml의 의존성을 사용합니다. 설정 이름은 .env.example에 있습니다. AI에는 OPENAI_API_KEY와 각 MCP 주소, RabbitMQ 주소를 전달합니다. OpenDART와 SerpApi 키는 백엔드 설정입니다. 실제 키는 소스에 기록하지 않습니다.

```bash
python -m disclosure_ai.entrypoints.worker --state /absolute/path/ai-state.sqlite
python -m disclosure_ai.entrypoints.worker --state /absolute/path/ai-state.sqlite --task-id <작업 UUID>
python -m disclosure_ai.entrypoints.local --input <입력 JSON> --filing <공시 ZIP> --state /absolute/path/local.sqlite
uvicorn disclosure_ai.entrypoints.api:app --host 127.0.0.1 --port 8000 --workers 1
```

패키지 설치 후 disclosure-ai-worker와 disclosure-ai-local 명령도 같은 진입점을 사용합니다. 기본 주소는 Business API 8080, Business MCP 8081, External MCP 8083, RAG MCP 8082입니다. 각 MCP는 /mcp 경로로 연결합니다. worker는 백엔드와 같은 RABBITMQ_URL, RABBITMQ_EXCHANGE, RABBITMQ_ANALYSIS_QUEUE를 사용합니다.

로컬 JSON은 request 객체와 memo_text 문자열을 받습니다. request에는 analysis_task_id, memo_id, base_memo_version, disclosure_receipt_no, company_name_snapshot, corp_code와 thread_id를 포함합니다. 로컬 결과의 LOCAL_SAVED와 PENDING_BACKEND는 업무 DB 저장을 수행하지 않았음을 나타냅니다.

선택적인 AI API는 AI_INTERNAL_TOKEN과 AI_STATE_PATH를 사용합니다. POST /internal/analyses에는 고정 request 필드와 사용자 Authorization 헤더, X-AI-Token 헤더를 받습니다. /internal/analyses/{task_id}/result, /events, /retry-save도 같은 입력과 인증으로 POST 호출합니다.

기본 검사는 pytest tests로 실행합니다. 백엔드 연결 검사는 전용 TEST_DATABASE_URL과 backend/business-api, backend/shared, backend/business-api/tests를 포함한 PYTHONPATH가 필요합니다. tests/live_runtime.py는 명시적으로 지정하고 AI_LIVE_RUNTIME=1, 전용 DB와 RabbitMQ, OpenAI 및 백엔드 OpenDART 설정을 제공할 때만 실제 외부 서비스를 호출합니다. RAG와 업무 DB의 원본 마이그레이션이 필요합니다.

## 7. 실제 실행 및 검증 결과

2026년 10월 21일 회귀 테스트 36개가 10.16초에 통과했습니다. 관점의 S2와 S3 왕복, 체크포인트 재개, 정규화된 조회 공유, 원문 재사용, 중단된 조회의 예산 유지와 접근 범위 분리, 대기 및 토큰 제한, 문맥 처리 실패와 전체 시간 초과를 확인했습니다. 실제 Business MCP와 전용 PostgreSQL로 초기 단계에서 중단된 보고서의 재저장과 중복 저장 방지도 확인했습니다.

변경된 패키지를 저장소 밖에서 wheel로 빌드해 설치했고 두 실행 명령과 프롬프트 파일 포함을 확인했습니다. 설치된 패키지의 실제 연결 검사 1개가 41.23초에 통과했습니다. RabbitMQ 수신, 원본 백엔드 MCP, OpenDART, OpenAI 모델과 임베딩, pgvector 검색, 보고서 DB 저장을 확인했습니다. 메모 원문은 보존됐고 보고서는 한 건 저장됐습니다. 기존 백엔드 테스트 마커 경고 25개가 표시됐습니다. Ruff 검사와 형식 검사도 통과했습니다.

재무와 학술 조회 도구는 백엔드 구현이 남아 있어 실제 연결은 미검증입니다. 사용자 화면의 버튼부터 보고서 표시까지의 검증과 다양한 실제 문장에 대한 투자 권유 판별 정확도 평가는 별도 범위입니다.

## 8. 트러블 슈팅

이전 흐름에서는 관점 함수 내부에서 추가 조회까지 실행해 S3가 결과 취합만 담당했습니다. 관점 응답과 공유 조회를 분리하고 S3 결과를 받은 관점이 S2에서 재개하도록 연결했습니다. 조회 실행 상태를 메모리에만 보관하던 부분도 SQLite에 기록하도록 보완했습니다.

시간 초과를 일반 실패로 반환하면 보고서가 생성되지 않을 수 있었습니다. 공통 실행 함수가 체크포인트를 읽고 모델 호출 없이 비상 보고서를 보존하도록 수정했습니다. 이 경로의 SAVE_FAILED는 보고서가 로컬에 보존돼 재저장할 수 있다는 뜻입니다.

실제 공시의 정정표 전체를 출력 검사에 다시 포함하면서 검사 문장 수 한도를 넘는 문제가 있었습니다. 원문 정정표는 보고서 생성 근거로 전달하고 생성된 서술을 출력 검사 대상으로 유지하도록 수정했습니다. 초기 단계에 보존된 비상 보고서는 AI 저장 호출부가 백엔드의 허용된 단계 전환을 거쳐 저장하도록 보완했습니다.

사용자가 보존을 지시한 기존 build와 disclosure_ai.egg-info는 그대로 두었습니다. 실행과 패키지 설치의 기준 소스는 disclosure_ai입니다.

현재 백엔드 Compose에는 postgres 항목 중복이 있습니다. 원본은 수정하지 않고 검증용 PostgreSQL과 RabbitMQ를 별도로 실행했습니다. 재무 조회와 학술 검색은 백엔드 도구가 없어 TOOL_NOT_AVAILABLE로 처리합니다.
