# Business API — Core Domain Schema

구현 담당자: 박다솔. 기존 SQLAlchemy 2.x sync + psycopg 3, Base 및 세션 관리 방식을 유지합니다. 현재 Domain schema, 상태 머신 및 sync Repository를 제공합니다. Service, JWT, API와 Queue 연동은 아직 없습니다.

## 모델과 관계

모든 모델은 `app.models`에서 import할 수 있습니다. 모델 구현은 `app/models/domain.py`, Enum은 `app/models/enums.py`에 있습니다. 13개 테이블은 PostgreSQL `core` schema에 한정합니다.

| Model | 책임 / 최소 relationship |
| --- | --- |
| Organization | users, filings, memos, analysis_tasks |
| User | 조직 FK, 전역 unique email, password_hash, UserRole |
| Filing | 조직별 접수번호, 회사·공시 종류·공시시각 |
| FilingVersion | 공시 FK, 버전과 원문·content_hash |
| Contract | 공시 FK, 계약 금액과 날짜 |
| Memo | 조직 FK, 현재 버전; memo_versions |
| MemoVersion | 메모·작성자 FK, 버전별 본문 |
| AnalysisTask | 조직·요청자·메모 FK, 선택적 공시 캐시 FK; revision_proposals, analysis_events, perspective_tasks, report |
| RevisionProposal | 작업 FK, 주장 식별자, 영향·수정안·검증상태·근거 |
| AnalysisPerspectiveTask | 선택된 관점·선택 근거·질문·상태·실행 한도·결과 |
| AnalysisReport | 작업별 최종 보고서 본문·JSON·생성/저장 시각 |
| AnalysisEvent | 작업별 sequence, event_type, payload_json |
| AuditLog | 조직·사용자 FK, 행위·대상·metadata_json |

relationship은 필요한 부모→자식 방향만 추가했습니다. 컬렉션 이름은 `memo_versions`, `revision_proposals`, `analysis_events`, `perspective_tasks`이며 버전과 이벤트는 번호순으로 탐색합니다.

## 타입과 선택 사항

- PK/FK는 UUID입니다. ORM에서 UUID4를 생성합니다. raw SQL INSERT 시에는 id를 직접 전달해야 합니다.
- 7개 Enum은 StrEnum + SQLAlchemy Enum(`native_enum=False`, `validate_strings=True`)으로 매핑합니다. DB에는 VARCHAR + 이름 있는 CHECK가 생성됩니다. PostgreSQL enum TYPE 변경·삭제 순서를 피하면서 DB에서도 잘못된 값을 차단합니다. Enum 값 변경은 CHECK 변경 migration을 수동 검토해야 합니다.
- 모든 `*_at`는 `TIMESTAMP WITH TIME ZONE`입니다. 생성시각은 DB `now()`로 생성하며 UTC instant로 저장됩니다. 반환 offset은 DB 세션 timezone을 따르므로 외부 직렬화 시 UTC로 정규화해야 합니다. PostgreSQL 세션 timezone은 UTC를 권장합니다.
- Memo/AnalysisTask/AnalysisReport의 updated_at은 ORM UPDATE 시 `onupdate=now()`로 갱신합니다. raw SQL UPDATE는 작성자가 직접 갱신해야 하며 별도 trigger는 없습니다.
- 금액은 Python Decimal / `NUMERIC(24,4)`입니다. float 계산을 사용하지 않습니다. 20자리 정수부·4자리 소수부를 지원하며 통화 단위는 현재 필드에 추가하지 않았습니다. 소수점 초과 입력은 PostgreSQL Numeric의 반올림 규칙을 따릅니다.
- JSONB는 evidence_json, payload_json, metadata_json, report_json(기본 객체 `{}`), result_json(결과 미생성 시 NULL)입니다. ORM에서 중첩 객체를 제자리 수정하면 변경 추적이 보장되지 않으므로 새 dict를 대입하세요.
- Contract.counterparty/start_date/end_date는 미확정 정보를 위해 nullable이며 amount는 필수입니다. 금액 부호·계약 날짜 순서에 대한 추가 업무 규칙은 아직 강제하지 않습니다.
- after_text는 HOLD·INTERPRETATION_REVIEW 등 수정문이 없는 경우를 위해 nullable입니다. 영향 유형별 조건 검사는 향후 Service 책임입니다.
- AnalysisTask.started_at/completed_at/error_code/error_message는 아직 발생하지 않은 값이므로 nullable입니다. thread_id는 생성 시 호출자가 제공하는 필수 문자열입니다.

## 제약조건과 index

- User.email은 전역 unique이며 case-sensitive입니다. 로그인 도입 시 이메일 정규화 정책을 별도로 결정해야 합니다.
- Filing은 `(organization_id, receipt_no)` unique입니다. 같은 외부 공시를 여러 조직이 각각 관리할 수 있습니다.
- `(filing_id, version)`, `(memo_id, version)`, `(analysis_task_id, sequence)`는 unique입니다.
- AnalysisTask.thread_id는 전역 unique로, 한 작업의 재개·재시도는 같은 작업/thread를 재사용합니다.
- AnalysisReport.analysis_task_id는 unique입니다. 동일 작업 저장 retry에서 중복 row를 방지하며 실제 upsert/재저장 로직은 이후 Service에서 구현합니다.
- AnalysisPerspectiveTask는 `(analysis_task_id, perspective_type)` unique입니다. 이 index의 선두 컬럼으로 작업별 관점 조회를 지원하여 별도 중복 index는 만들지 않았습니다. 선택되지 않은 관점은 row를 만들지 않는 것이 호출 측 계약입니다.
- 버전·현재 버전·기준 버전·이벤트 순번은 모두 `>= 1` CHECK가 있습니다.
- PK/unique index를 조회에도 활용합니다. 조직별 공시·버전별 메모·작업별 이벤트 조회에는 복합 unique의 선두 컬럼을 사용하므로 중복 index를 만들지 않습니다.
- 별도 index: User.organization_id, Filing.receipt_no, Contract.filing_id, Memo.organization_id, AnalysisTask의 `(organization_id,status)`·status·memo_id·filing_id·disclosure_receipt_no 및 `(organization_id,memo_id,base_memo_version,disclosure_receipt_no,status)`, RevisionProposal.analysis_task_id, AuditLog의 `(organization_id,created_at)`. 중복 분석 조회 index는 검색을 지원하며 동시 중복 실행을 단독으로 차단하지는 않습니다.
- 모든 FK는 ON DELETE RESTRICT입니다. ORM relationship은 삭제 cascade/delete-orphan 없이 passive_deletes="all"을 사용합니다. 부모와 컬렉션이 로딩되어 있어도 ORM이 자식을 지우거나 FK를 NULL로 만들지 않으며 참조가 있으면 부모 삭제가 실패합니다.

현재 FK는 개별 참조 존재를 보장합니다. 조직 간 참조 일치와 current/base 버전이 해당 메모에 실제 존재하는지는 별도 복합 FK나 trigger로 강제하지 않습니다. 이 일관성 검사는 다음 Service 단계에서 반드시 구현해야 합니다. MemoVersion은 보존 대상으로 취급하지만 직접 UPDATE/DELETE를 DB trigger로 금지하지는 않습니다. 삭제 API나 변경 로직은 이번에 구현하지 않았습니다.

## Migration

`alembic/README.md` 참고. revision chain은 `0001_initial_core` → `0002_align_report_flow`입니다. initial migration은 커밋된 이력을 그대로 보존했습니다.

```bash
# 이 폴더에서 DATABASE_URL 설정 후
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
```

처음에는 core schema가 없는 DB가 필요합니다. migration 계정은 schema 생성 권한이 필요합니다. public.alembic_version은 기존 기반 설정과 호환되도록 유지합니다. RAG/checkpoint는 별도 migration 이력을 사용해야 합니다.

## 검증

```bash
# dependency 설치는 ../README.md(backend README)의 로컬 실행 절차 참고
.venv/bin/python -m pytest -q
# 반드시 별도 전용 PostgreSQL 테스트 DB 사용
TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest -q
# core schema downgrade를 허용하는 폐기 가능한 DB에서만 실행
TEST_DATABASE_URL="$DATABASE_URL" TEST_ALLOW_SCHEMA_RESET=1 .venv/bin/python -m pytest -q
```

모델 테스트는 Alembic upgrade로 schema를 준비하고 테스트별 데이터를 rollback합니다. schema 왕복 테스트는 downgrade와 재-upgrade를 수행하고 RAG/checkpoint를 흉내 낸 다른 schema 테이블의 보존도 검증합니다. 실제 개발/운영 DB에서는 실행하지 마세요. SQLite 또는 create_all로 PostgreSQL 검증을 대체하지 않습니다.

설계 참고: [SQLAlchemy 비네이티브 Enum](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Enum), [ORM 삭제 정책](https://docs.sqlalchemy.org/en/20/orm/cascades.html#passive-deletes), [Alembic schema 필터](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#omitting-schema-names-from-the-autogenerate-process).

## 분석 보고서 플로우 정렬 (0002)

기존 승인 및 메모 자동 수정 흐름을 제거했습니다. Approval, ApprovalItem, RevisionApplication과 ApprovalStatus는 현재 ORM/export에 없습니다. 역사적인 0001과 0002 downgrade 정의에는 이전 schema를 재현하기 위해 남아 있습니다. RevisionProposal은 분석 보고서에 포함될 수정 제안으로 AnalysisTask에만 연결됩니다. Memo/MemoVersion은 보존하며 보고서 생성으로 자동 버전을 생성하지 않습니다.

AnalysisTask의 필수 입력은 memo_id, base_memo_version, disclosure_receipt_no, company_name_snapshot, thread_id입니다. organization_id/requested_by도 기존대로 필수입니다. filing_id는 nullable RESTRICT FK로 남겨 OpenDART 캐시가 없어도 분석을 등록할 수 있습니다. corp_code는 기존 데이터에서 유추할 수 없고 조회 전 미확정일 수 있어 nullable String(8)로 둡니다. 실제 호출·코드 검증은 이번 범위에 없습니다.

AnalysisStatus는 CREATED, QUEUED, RUNNING, SAVING, COMPLETED, COMPLETED_WITH_WARNINGS, SAVE_FAILED, FAILED, CANCELLED입니다. current_stage와 error_stage는 AnalysisStage를 사용하며 NULL은 미시작/오류 없음 또는 과거 진행단계 불명확을 뜻합니다. has_warnings는 NOT NULL, 기본 false입니다. 단계별 전이와 warning 취합 로직은 없습니다.

AnalysisStage는 REQUEST_VALIDATION, INPUT_COLLECTION, RAG_PREPARATION, BASE_ANALYSIS, PERSPECTIVE_ANALYSIS, REPORT_GENERATION, REPORT_SAVE입니다.

PerspectiveType은 FINANCE, FX_HEDGE, INDUSTRY_CONTRACT입니다. PerspectiveStatus는 REGISTERED, RUNNING, COMPLETED, INSUFFICIENT_EVIDENCE, LIMIT_REACHED, FAILED입니다. selection_reason/question/max_tool_calls/timeout_seconds는 필수이며 max_tool_calls>=0, timeout_seconds>0 CHECK가 있습니다. 한도 기본값을 임의로 정하지 않아 호출자가 지정합니다. 0회 호출 한도는 외부 도구 없이 분석하는 경우를 허용합니다. result_json과 실패 정보·시작/종료 시각은 미발생 상태를 위해 nullable입니다.

AnalysisReport는 content/report_json/has_warnings/generated_at을 저장합니다. generated_at은 실제 생성 시각을 호출자가 제공해야 합니다. saved_at은 NULL일 수 있고 no_additional_analysis_reason도 관점 분석이 선택된 경우를 위해 nullable입니다. saved_at=NULL은 생성된 내용을 보존한 미확정 저장 상태를 표현할 수 있습니다. 이 모델만으로 DB 자체 쓰기 장애 중 생성 결과 보존까지 보장하지는 않습니다. 해당 장애 시 checkpoint 등 결과 보관과 재저장 정책은 후속 Agent/Service 단계에서 구현해야 합니다. 저장/retry Service는 미구현이며 상태 전이와 DB 조회 규칙은 아래 절을 참고하세요.

0002 upgrade는 기존 Filing의 receipt_no/company_name으로 Task 입력 snapshot을 backfill합니다. corp_code와 stage는 추측해서 채우지 않습니다. 제거된 대기 상태가 있는 경우 migration은 의미가 다른 상태로 자동 변환하지 않고 DDL 전에 중단합니다. 운영자가 기존 작업을 검토·정리한 후 재실행해야 합니다.

승인 관련 3개 테이블은 FK 의존 순서대로 실제 삭제됩니다. 이 테이블의 데이터는 유실되므로 적용 전 필요한 이력을 별도 보관해야 합니다. downgrade는 해당 schema를 빈 테이블로 복원하며 과거 승인 데이터를 복원하지 않습니다. 새 보고서/관점 row, filing_id 없는 작업, 새 전용 상태가 있으면 downgrade는 변경 전에 중단합니다. 결과를 별도 보관하고 구 schema와 호환되게 수동 정리한 뒤에만 downgrade할 수 있습니다. 호환 가능한 경우에도 새 snapshot/stage/warning 컬럼 데이터는 downgrade에서 소실됩니다. 원본 Memo/MemoVersion은 migration에서 수정하지 않습니다.

## 상태 머신과 Repository

Domain 함수는 `app/domain/analysis_state_machine.py`의 `transition_analysis`, `advance_analysis_stage`, `app/domain/perspective_state_machine.py`의 `transition_perspective`입니다. ORM 인스턴스를 메모리에서 변경하여 반환하며 DB flush·commit·이벤트 생성·HTTP 예외 변환은 하지 않습니다. 구조화 예외는 `app/domain/exceptions.py`에 있으며 현재/목표 상태 또는 stage와 code를 제공합니다.

### Task lifecycle 및 stage

| 현재 status | 허용 목표 status |
| --- | --- |
| CREATED | QUEUED, CANCELLED |
| QUEUED | RUNNING, CANCELLED |
| RUNNING | SAVING, FAILED, CANCELLED |
| SAVING | COMPLETED, COMPLETED_WITH_WARNINGS, SAVE_FAILED, CANCELLED |
| SAVE_FAILED | SAVING, CANCELLED |

COMPLETED/COMPLETED_WITH_WARNINGS/FAILED/CANCELLED는 terminal입니다. 자기 자신으로의 전이도 허용하지 않습니다. QUEUED→RUNNING에서 started_at이 없으면 UTC 현재시각을 기록하고 기존 값은 보존합니다. terminal 진입 시 completed_at을 기록하며 모든 non-terminal 진입에서는 NULL로 정리합니다. SAVE_FAILED는 분석 실패/완료가 아니므로 completed_at=NULL이고, retry는 started_at과 REPORT_SAVE stage 및 오류 정보를 보존합니다. 오류 해소 기록과 warning 내용·최종 완료 상태 선택은 Service의 책임입니다. 상태 머신은 has_warnings를 자동 분류하거나 바꾸지 않습니다.

RUNNING 진입 시 stage가 NULL이면 REQUEST_VALIDATION으로 초기화합니다. REQUEST_VALIDATION은 CREATED/QUEUED에도 최초 기록할 수 있고 실제 입력 수집 이후의 stage는 RUNNING에서만 진행합니다.

```text
REQUEST_VALIDATION → INPUT_COLLECTION → RAG_PREPARATION → BASE_ANALYSIS
BASE_ANALYSIS → PERSPECTIVE_ANALYSIS → REPORT_GENERATION → REPORT_SAVE
BASE_ANALYSIS → REPORT_GENERATION → REPORT_SAVE
INPUT_COLLECTION 또는 RAG_PREPARATION → REPORT_GENERATION (fallback)
```

REPORT_GENERATION→REPORT_SAVE는 status를 SAVING으로 함께 변경합니다. `transition_analysis(task, SAVING)`도 RUNNING일 때 REPORT_GENERATION을 요구하고 두 값을 함께 변경합니다. 따라서 RUNNING/REPORT_SAVE 중간 상태를 만들지 않습니다. SAVE_FAILED→SAVING은 REPORT_SAVE를 유지합니다. 이전 stage로 역행하거나 terminal 이후 stage를 변경할 수 없습니다. CANCELLED는 모든 non-terminal status에서 허용하며 legacy stage가 NULL인 경우도 취소할 수 있습니다.

Timestamp에는 timezone-aware UTC를 사용하고 주입한 `now`는 UTC로 정규화합니다. naive datetime은 변경 전에 거부합니다. 아직 flush하지 않은 ORM 객체의 SQLAlchemy default 값은 None일 수 있으므로 상태 머신 호출 전 명시적으로 status를 초기화하거나 Repository.add로 flush해야 합니다. 이 동작 때문에 모델이나 migration을 변경하지 않았습니다.

### Perspective lifecycle

REGISTERED→RUNNING→COMPLETED/INSUFFICIENT_EVIDENCE/LIMIT_REACHED/FAILED만 허용합니다. 뒤의 4개는 terminal입니다. 시작 시각은 최초 RUNNING 진입에서 설정·보존하고 terminal 진입 시 완료시각을 기록합니다. 도구 호출/응답이 반복되는 동안에는 상태를 RUNNING으로 유지하며 같은 상태로 재전이 함수를 호출하지 않습니다.

### Repository 계약

모든 Repository는 `app.repositories`에서 import할 수 있고 생성자로 기존 sync Session을 받습니다. `add`는 객체를 추가하고 Session을 flush하여 반환합니다. Session의 다른 pending 변경도 flush될 수 있습니다. Repository는 commit/rollback/close 및 상태 전이 판단을 하지 않습니다. 오류가 발생하면 상위 호출자가 transaction 또는 savepoint를 rollback해야 합니다.

| Repository | 제공 조회/추가 |
| --- | --- |
| UserRepository | id, email, id+organization |
| MemoRepository | id, id+organization, 현재 버전 번호, 특정 MemoVersion, 버전 목록 |
| FilingRepository | id, id+organization, 접수번호 목록, 접수번호+organization 단건, 최신 FilingVersion |
| AnalysisRepository | add, id, id+organization, thread_id, 조직별 목록, active duplicate |
| PerspectiveTaskRepository | add, id, task+type, task별 전체/active 목록 |
| RevisionRepository | add, id, task별 제안 목록 |
| AnalysisReportRepository | add, id, task별 보고서 및 존재 여부 |
| AnalysisEventRepository | add, task별 sequence 정렬 목록, 최신 sequence |
| AuditLogRepository | add, 조직과 resource_type/resource_id별 목록 |

`MemoRepository.get_current_version`은 int 또는 None을 반환합니다. `get_version`은 MemoVersion을 반환합니다. 버전 조회에도 선택적 organization_id를 전달할 수 있습니다. Filing 접수번호는 조직 내 unique이므로 조직 없는 `list_by_receipt_no`는 list를 반환하고 `get_by_receipt_no_and_organization`은 단건/None을 반환합니다. 캐시가 없으면 None/빈 목록으로 반환하며 분석 불가 여부를 판단하지 않습니다.

Task/Memo의 id 조회와 조직 범위 조회, Memo의 현재 버전 조회에는 `for_update=True`를 지원합니다. 잠금 획득·해제는 호출자의 transaction에 따릅니다. 객체 잠금 조회는 populate_existing으로 캐시를 갱신하므로 메모리 수정 전에 잠금 조회를 수행하고, 기존 변경이 있으면 먼저 flush하세요.

active duplicate는 organization_id/memo_id/base_memo_version/disclosure_receipt_no 4개가 모두 같고 CREATED/QUEUED/RUNNING/SAVING/SAVE_FAILED 상태인 기존 작업입니다. 여러 개가 이미 있으면 created_at/id 기준 첫 작업을 반환합니다. 이 조회는 없는 key를 잠그지 않으므로 동시 중복 생성 차단까지 보장하지 않습니다. 이후 Service가 transaction/동시성 정책을 정해야 합니다. 이벤트 최신 sequence도 조회일 뿐 번호를 예약·할당하지 않습니다. 이벤트가 없으면 0입니다.

Perspective active는 REGISTERED/RUNNING입니다. Report와 Perspective의 중복은 기존 DB unique가 차단하고 Repository는 IntegrityError를 숨기지 않습니다. 보고서 존재 확인과 add 사이의 동시성도 Service가 처리해야 합니다. AuditLog에는 update/delete 메서드가 없습니다.

사용자 요청에는 User/Memo/Filing/Analysis의 조직 범위 조회를 우선 사용해야 합니다. organization을 받지 않는 내부 조회는 JWT 권한을 보장하지 않습니다. Perspective/Revision/Report/Event 조회 전에는 부모 AnalysisTask의 조직 범위를 상위 계층에서 확인해야 합니다. AuditLog 자원 조회는 organization_id를 필수로 받습니다. 목록 조회는 현재 전체 목록이며 향후 서비스 규모에 맞춰 pagination을 추가할 수 있습니다.

기존 모델은 개별 FK와 양수 버전을 보장하지만 조직 일치와 고정한 MemoVersion의 실제 존재를 완전히 강제하지 않습니다. 이 검증은 후속 Service 범위이며 이번에는 schema를 변경하지 않았습니다. JWT/API/RabbitMQ/Agent/저장 retry Service는 구현하지 않았습니다.

실제 Business Service와 Analysis 처리에서 접수번호로 공시를 조회할 때는 JWT 또는 AnalysisTask에서 확정한 organization_id를 사용해 반드시 `get_by_receipt_no_and_organization`을 호출합니다. 조직 없는 단건 접수번호 조회 메서드나 이전 이름의 호환 alias는 제공하지 않습니다.
