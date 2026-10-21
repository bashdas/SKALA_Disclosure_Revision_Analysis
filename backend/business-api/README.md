# Business API — Core Domain Schema

구현 담당자: 박다솔. 기존 SQLAlchemy 2.x sync + psycopg 3, Base 및 세션 관리 방식을 유지합니다. 현재 Domain schema, 상태 머신, sync Repository와 JWT 인증/인가 기반을 제공합니다. AuthService/로그인, Memo 텍스트 업로드 및 조직 범위 Filing/Memo 조회 API를 제공합니다. 분석 API와 Queue 연동은 아직 없습니다.

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
| MemoVersion | 메모·작성자 FK, 버전별 본문과 업로드 provenance |
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

- User.email은 전역 unique이며 case-sensitive입니다. 로그인은 기존 값을 정확히 조회하고 자동 lower-case/정규화를 적용하지 않습니다.
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

`alembic/README.md` 참고. revision chain은 `0001_initial_core` → `0002_align_report_flow` → `0003_memo_upload`입니다. initial migration은 커밋된 이력을 그대로 보존했습니다.

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

사용자 요청에는 User/Memo/Filing/Analysis의 조직 범위 조회를 우선 사용해야 합니다. organization을 받지 않는 내부 조회는 JWT 권한을 보장하지 않습니다. Perspective/Revision/Report/Event 조회 전에는 부모 AnalysisTask의 조직 범위를 상위 계층에서 확인해야 합니다. AuditLog 자원 조회는 organization_id를 필수로 받습니다. 기존 내부 목록 조회는 전체 목록이며 Filing/Memo 공개 목록 및 버전 목록에는 limit/offset pagination을 적용합니다.

기존 모델은 개별 FK와 양수 버전을 보장하지만 조직 일치와 고정한 MemoVersion의 실제 존재를 완전히 강제하지 않습니다. 이 검증은 후속 Service 범위이며 이번에는 schema를 변경하지 않았습니다. 분석 API/RabbitMQ/Agent/저장 retry Service는 구현하지 않았습니다. JWT 인증과 Filing/Memo 조회는 아래 절을 참고하세요.

실제 Business Service와 Analysis 처리에서 접수번호로 공시를 조회할 때는 JWT 또는 AnalysisTask에서 확정한 organization_id를 사용해 반드시 `get_by_receipt_no_and_organization`을 호출합니다. 조직 없는 단건 접수번호 조회 메서드나 이전 이름의 호환 alias는 제공하지 않습니다.

## JWT 인증 및 조직/역할 인가

Python dependency는 PyJWT 2.x와 argon2-cffi 23.1 이상입니다. argon2-cffi의 PasswordHasher 기본 Argon2id/RFC profile과 무작위 salt를 사용합니다. `app/core/security.py`는 hash_password/verify_password와 create_access_token/decode_access_token을 제공하며 DB/HTTP 로직은 포함하지 않습니다. 비밀번호 검증 실패나 손상된 hash는 False를 반환합니다. 사용자 비밀번호는 기존 User.password_hash에 해시로만 저장해야 하며 이번에는 회원가입/비밀번호 변경/계정 seed API를 만들지 않았습니다.

### 설정

`backend/.env.example`의 JWT 설정을 로컬 실행 환경에 맞게 지정합니다. 실제 secret을 커밋하지 마세요.

```dotenv
JWT_SECRET_KEY=change-me
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
```

change-me는 의도적으로 사용할 수 없는 placeholder입니다. 인증 기능은 무작위 secret을 최소 32 bytes 길이로 설정해야 동작합니다. Secret은 pydantic SecretStr로 감추고 repr에 포함하지 않습니다. 비밀키가 없거나 너무 짧거나 지원하지 않는 algorithm이면 인증 작업은 AUTH_CONFIGURATION_ERROR(503)로 실패하며 health는 인증 없이 유지합니다. HS256만 지원하며 JWT header의 algorithm은 신뢰하지 않습니다. 실제 환경에서는 HTTPS로 token을 전송해야 합니다.

현재 프로세스는 설정을 cache하므로 환경변수 변경 뒤 재시작해야 합니다. 기존 SecretStr 아닌 문자열로 설정을 직접 읽던 로컬 코드가 있다면 `.get_secret_value()`는 crypto 코드 안에서만 사용하세요. 앱 코드는 password/hash/token/Authorization/secret을 로그에 기록하지 않습니다.

### 로그인

```http
POST /api/v1/auth/login
Content-Type: application/json

{"email":"analyst@example.test","password":"<local password>"}
```

성공 응답은 access_token, token_type="bearer", expires_in(초)입니다. JSON 로그인만 지원하며 OAuth password form은 아닙니다. AuthService가 UserRepository.get_by_email로 조회하고 password를 검증한 뒤 token을 발급합니다. 사용자 없음과 비밀번호 오류는 모두 동일한 401 INVALID_CREDENTIALS를 반환하고, 없는 사용자도 dummy Argon2 hash를 검증합니다. 로그인은 read-only이며 commit이나 자동 password rehash를 하지 않습니다. RequestValidationError 응답에서는 입력값과 context를 제거해 password를 되돌려주지 않습니다.

### Access token과 current_user

Claims는 sub(UUID user id), organization_id(UUID), role(RA/ANALYST), iat/exp(UTC NumericDate 정수)입니다. 발급 시 설정한 만료 분을 사용하고 검증 시 signature/고정 algorithm/expiry/iat와 5개 필수 claim 및 UUID·role·정수 타입/만료 순서를 확인합니다. 만료/미래 iat/손상된 token/alg none/잘못된 signature·claim은 거부합니다.

`app/api/dependencies.py`의 get_current_user는 먼저 HTTP Bearer token을 검증하고 UserRepository.get_by_id로 현재 사용자를 DB에서 조회합니다. User가 없거나 DB organization/role과 token claim이 다르면 401입니다. 조직 이동/역할 변경 이후에는 새로 로그인해야 합니다. CurrentUser는 id/organization_id/email/role만 담는 frozen Pydantic principal이며 password_hash를 포함하지 않습니다. active 필드는 추가하지 않았습니다.

### Organization과 RBAC

`get_current_organization_id`는 검증된 current_user.organization_id만 반환합니다. 이후 Business API/Service의 조직 범위 조회는 client의 body/query/path 조직 값 대신 이 값을 사용해야 합니다. 특히 Filing은 UNIQUE(organization_id,receipt_no)를 유지하고 단건 조회에 `get_by_receipt_no_and_organization(receipt_no,current_user.organization_id)`를 사용합니다. 조직 미지정 `list_by_receipt_no`는 내부 목록 조회용이며 단건으로 대체하지 않습니다.

`require_roles(UserRole.RA)` 또는 `require_roles(UserRole.RA,UserRole.ANALYST)`는 재사용 가능한 FastAPI dependency를 반환합니다. 역할 불일치는 403이며 빈 허용 역할 목록은 구성 오류로 즉시 거부합니다. RA와 ANALYST 사이에 암묵적 상하 권한 관계는 두지 않습니다. Filing/Memo 읽기 endpoint에는 두 역할 허용 정책을 적용했으며 나머지 업무 정책은 미구현입니다. production에는 테스트용 protected endpoint를 추가하지 않았습니다. /health 및 /health/db는 공개 상태로 유지합니다.

### 오류와 범위

| 내부 오류 코드 | HTTP | 외부 노출 |
| --- | --- | --- |
| INVALID_CREDENTIALS | 401 | 동일한 로그인 실패 메시지 |
| UNAUTHENTICATED | 401 | 인증 필요 |
| INVALID_TOKEN | 401 | token 무효 |
| TOKEN_EXPIRED | 401 | token 만료 |
| USER_NOT_FOUND | 401 | INVALID_TOKEN으로 감춤 |
| FORBIDDEN | 403 | 권한 부족 |
| AUTH_CONFIGURATION_ERROR | 503 | 세부 secret 없는 인증 불가 |

401에는 WWW-Authenticate: Bearer를 포함합니다. crypto/Service/dependency는 구조화 AuthError를 사용하고 HTTP 매핑은 app/api/exception_handlers.py에 분리했습니다. 기존 상태 전이 예외는 변경하지 않았습니다.

Refresh/rotation/logout blacklist/비밀번호 reset/signup/계정 CRUD/MCP·internal 인증/분석 API/RabbitMQ/Agent는 아직 구현하지 않았습니다. 인증 단계에서는 DB schema와 기존 Repository를 수정하지 않았습니다. 인증 테스트는 별도 test secret과 임시 PostgreSQL을 사용하며 테스트 앱에서만 protected routes를 구성합니다.

구현 참고: [PyJWT 검증 API](https://pyjwt.readthedocs.io/en/stable/api.html), [argon2-cffi PasswordHasher](https://argon2-cffi.readthedocs.io/en/stable/api.html).

## Filing / Memo 조직 범위 조회 API

모든 endpoint는 Bearer 인증과 require_roles(RA, ANALYST)를 적용합니다. JWT를 DB User와 대조한 current_user.organization_id만 Service로 넘깁니다. 클라이언트가 organization_id query를 추가해도 조회 범위에 영향을 주지 않습니다. DTO에는 organization_id나 relationship을 노출하지 않습니다.

| Method | Endpoint | 응답 |
| --- | --- | --- |
| GET | /api/v1/filings | FilingSummaryResponse 배열 |
| GET | /api/v1/filings/by-receipt/{receipt_no} | 조직 범위 FilingDetailResponse |
| GET | /api/v1/filings/{filing_id} | FilingDetailResponse |
| GET | /api/v1/filings/{filing_id}/versions | FilingVersionSummaryResponse 배열 |
| GET | /api/v1/filings/{filing_id}/versions/{version} | raw_content 포함 버전 상세 |
| GET | /api/v1/memos | MemoSummaryResponse 배열 |
| GET | /api/v1/memos/{memo_id} | MemoDetailResponse |
| GET | /api/v1/memos/{memo_id}/versions | MemoVersionSummaryResponse 배열 |
| GET | /api/v1/memos/{memo_id}/versions/{version} | content 포함 버전 상세 |

모든 목록은 limit 기본 20, 범위 1~100, offset 기본 0/최소 0을 사용합니다. 응답은 JSON 배열이며 total count를 별도로 조회하지 않습니다. Filing은 filed_at DESC, id DESC, Memo는 updated_at DESC, id DESC입니다. 버전 목록은 version ASC이며 같은 pagination을 적용합니다. Filing 목록은 company_name/filing_type, Memo 목록은 company_name의 선택적 정확 일치 필터를 지원합니다. 대소문자 정규화·부분 검색·외부 API 조회는 하지 않습니다.

FilingRepository의 UNIQUE(organization_id,receipt_no), list_by_receipt_no 다건 조회와 get_by_receipt_no_and_organization 단건 조회는 유지했습니다. Business API의 접수번호 조회는 단건 조직 범위 메서드만 사용합니다. 다른 조직에만 있는 receipt_no나 ID는 없는 리소스와 동일한 404를 반환합니다. 조직 미지정 단건 메서드나 호환 alias는 없습니다.

FilingService/MemoService가 조직 범위 부모 조회·존재 판단을 담당하고, 버전 조회 전에 부모를 반드시 확인합니다. 버전 Repository query에도 organization_id를 전달해 부모 join scope를 추가합니다. 다른 조직 부모는 FILING_NOT_FOUND/MEMO_NOT_FOUND, 현재 조직 부모의 없는 버전은 FILING_VERSION_NOT_FOUND/MEMO_VERSION_NOT_FOUND로 처리하며, 모두 기존 error envelope의 HTTP 404입니다. Repository는 None을 반환하고 HTTP 예외를 만들지 않습니다.

요약과 상세는 명시적인 Pydantic DTO를 사용합니다. Filing/Memo 일반 상세에는 전체 원문이나 버전 relationship을 포함하지 않고 버전 목록에도 raw_content/content를 포함하지 않습니다. 정확한 버전 상세 endpoint에서만 본문을 반환합니다. 생성자 ID와 content_hash 등 명세에 필요한 필드는 버전 DTO에 포함합니다.

MemoService.get_current_version은 조직 범위 Memo를 조회한 뒤 current_version에 해당하는 MemoVersion을 반환합니다. 참조 버전이 실제로 없으면 MEMO_VERSION_NOT_FOUND입니다. 별도 /current-version endpoint는 versions/{version}와 중복이므로 추가하지 않았습니다.

Filing은 저장된 OpenDART cache/snapshot만 조회합니다. 없으면 404이며 OpenDART 호출이나 cache 생성은 없습니다. 향후 AnalysisTask의 disclosure_receipt_no 입력에 Filing row 존재를 강제하지 않습니다. GET은 commit/rollback/close나 데이터 생성을 수행하지 않으며 기존 Session lifecycle을 재사용합니다. 모델/migration 변경은 없습니다.

실행 예시는 token을 로그에 남기지 않는 로컬 환경에서 사용하세요.

```bash
# Business API 실행 후 로컬 환경에 ACCESS_TOKEN을 설정한 상태
curl -H "Authorization: Bearer $ACCESS_TOKEN" 'http://localhost:8080/api/v1/filings?limit=20&offset=0'
curl -H "Authorization: Bearer $ACCESS_TOKEN" 'http://localhost:8080/api/v1/memos?limit=20&offset=0'
```

PostgreSQL 검증은 test_read_api.py에 있으며 기존 JWT·상태 머신·Repository·migration 회귀 테스트와 함께 실행합니다. 다음 단계의 Analysis 생성 API/RabbitMQ는 이번에 구현하지 않았습니다.

## Memo 텍스트 업로드 및 최초 버전

사용자 입력은 file과 선택적 title뿐입니다. organization_id/created_by는 검증된 current_user에서 가져오며, 회사명/corp_code/receipt_no/버전 번호는 입력 schema에 없습니다. 클라이언트가 추가 form 필드로 전달하더라도 사용하지 않습니다. 파일명은 표시 제목에만 사용하며 Memo.company_name은 항상 NULL로 생성합니다.

```http
POST /api/v1/memos
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file=<UTF-8 .txt file>
title=<optional display title>
```

RA/ANALYST 모두 업로드할 수 있으며 성공 시 HTTP 201입니다. 응답은 Memo 요약(id/title/company_name/current_version/created_at/updated_at)과 original_filename/content_type/size_bytes/content_hash이며 content와 조직 ID는 포함하지 않습니다.

### 파일 정책과 parser 경계

- 실제 지원은 `.txt`(확장자 대소문자 무관)와 `text/plain` MIME의 조합뿐입니다. PDF/DOCX/OCR/Markdown parser는 추가하지 않았습니다.
- `MEMO_UPLOAD_MAX_BYTES` 기본값은 5242880(5 MiB), 양수 설정입니다. 전송 파일 bytes 기준이며 헤더의 크기를 신뢰하지 않고 Service에서 최대 limit+1 bytes만 읽어 초과를 판정합니다.
- UTF-8 strict decode를 사용합니다. UTF-8 BOM은 텍스트에서 제거하되 bytes 기준 size/hash에는 포함합니다. UTF-8 외 charset 선언, 잘못된 UTF-8, 빈/공백 원문과 PostgreSQL Text에 저장할 수 없는 NUL 문자는 거부합니다. 나머지 원문의 공백/줄바꿈은 보존합니다.
- 파일명은 클라이언트 경로를 제거한 basename만 보관하며 255자 이내의 유효한 이름이어야 합니다. 서버 파일 경로로 사용하지 않습니다. MIME은 검증 후 text/plain으로 정규화해 저장합니다.
- 제목은 입력값의 앞뒤 공백을 제거하여 사용하고 1~500자를 요구합니다. 미입력은 basename의 마지막 확장자만 제거합니다. 회사 식별 값은 추론하지 않습니다.
- MemoTextExtractor Protocol과 PlainTextMemoExtractor를 분리했습니다. 이후 parser 구현을 주입할 수 있지만 plugin framework나 PDF/DOCX 처리는 없습니다.
- 원본 binary는 DB/Object Storage에 보존하지 않습니다. FastAPI의 요청 처리용 임시 UploadFile과 별개로 영구 보관하는 것은 추출 text와 metadata/hash뿐입니다. 이 설정은 app의 파일 payload 한도이며 ingress 전체 multipart 요청 제한과는 별개입니다.

### Transaction과 보존

MemoService.create_from_upload가 검증/추출 후 Memo(current_version=1, company_name=NULL)를 add_memo/flush하고 MemoVersion(version=1, created_by=current_user.id)를 add_version/flush한 뒤 한 번 commit합니다. 인증 DB 조회로 이미 autobegin된 요청 Session을 사용하며 다시 session.begin()을 열지 않습니다. 실패하면 Service가 rollback합니다. 이 쓰기 메서드는 요청 transaction을 소유하므로 다른 미커밋 작업과 혼합 호출하지 마세요. Repository는 flush만 수행하며 commit/rollback/close하지 않습니다.

Metadata는 MemoVersion에 original_filename/content_type/size_bytes/content_hash로 보관합니다. SHA-256은 hashlib로 원본 bytes에서 계산하고 global unique를 두지 않아 동일 파일 재업로드를 허용합니다. 기존 버전의 원본 bytes는 없으므로 metadata는 NULL로 유지하고 text에서 raw hash를 추측해 채우지 않습니다.

GET /api/v1/memos와 단건은 company_name=NULL을 반환할 수 있습니다. 버전 목록/상세에 metadata 4개를 추가했으며 오래된 기록은 NULL입니다. 목록에는 content가 없고 특정 버전 상세에만 있습니다. 기존 limit/offset·조직 격리·404 정책은 유지합니다. 새 버전을 기존 Memo에 추가하는 endpoint는 없습니다.

### Migration 적용

`0003_memo_upload`가 Memo.company_name nullable과 MemoVersion metadata 4개 nullable 컬럼, size_bytes>=0 CHECK를 추가합니다. 기존 migration은 수정하지 않았습니다.

```bash
# Business API 폴더 / DATABASE_URL 설정 후
.venv/bin/alembic upgrade head
.venv/bin/alembic check
```

NULL 회사명이 있거나 metadata가 하나라도 저장되어 있으면 downgrade를 시작 전에 차단합니다. 없는 회사명을 만들어 채우거나 provenance를 자동 삭제하지 않습니다. 필요한 데이터를 보관하고 구 schema로 돌아갈 수 있는 상태로 정리한 경우에만 downgrade할 수 있습니다. 기존 기록처럼 회사명 non-NULL/metadata NULL이면 downgrade 후 재-upgrade가 가능합니다.

| Error code | HTTP |
| --- | --- |
| EMPTY_MEMO | 400 |
| INVALID_MEMO_ENCODING | 400 |
| INVALID_MEMO_TEXT / INVALID_MEMO_FILENAME / INVALID_MEMO_TITLE | 400 |
| MEMO_FILE_TOO_LARGE | 413 |
| UNSUPPORTED_MEMO_FORMAT | 415 |

누락된 file이나 schema 길이 검증 등은 기존 422 응답입니다. MEMO_NOT_FOUND/MEMO_VERSION_NOT_FOUND는 기존 404를 유지합니다.

검증은 test_memo_upload.py와 test_migrations.py에 있습니다. 실제로 독립된 Session에서 commit된 두 레코드의 가시성, 각 flush/commit 실패의 rollback, 조직 간 접근, legacy metadata 및 downgrade 보호를 확인합니다. 테스트 DB와 TEST_ALLOW_SCHEMA_RESET=1은 반드시 폐기 가능한 DB에만 지정하세요.

다음 Analysis 입력은 memo_id와 disclosure_receipt_no입니다. 현재 AnalysisTask.company_name_snapshot은 아직 NOT NULL이므로 기업명을 Agent가 나중에 확정하는 새 플로우에 맞춘 처리는 다음 Analysis 생성 단계에서 별도로 검토해야 합니다. 이번에는 AnalysisTask/RabbitMQ/OpenDART를 변경하거나 구현하지 않았습니다.

구현 참고: [FastAPI UploadFile](https://fastapi.tiangolo.com/tutorial/request-files/), [SQLAlchemy flush/rollback](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#flushing).

## 회원 API

- `POST /api/v1/auth/signup`: email, password(12~128자), organization_name. 신규 조직과 ANALYST 사용자를 한 transaction으로 생성합니다. 기존 조직 ID/역할 입력은 허용하지 않습니다. 성공 201, 중복 이메일 409입니다. 이메일은 domain 정규화 외 기존 case-sensitive 정책을 유지합니다.
- `POST /api/v1/auth/login`: 기존 email/password 로그인, Bearer Access Token 발급.
- `GET /api/v1/users/me`: Bearer 인증 사용자 본인 정보만 반환합니다.
- `PATCH /api/v1/users/me/password`: current_password/new_password로 변경, 성공 204. 기존 토큰을 모두 무효화하므로 다시 로그인합니다.

```json
{"email":"user@example.com","password":"example-password-123!","organization_name":"새 조직"}
```

새 dependency를 설치하고 `alembic upgrade head`를 적용해야 합니다. revision `0005_user_token_version`은 core.users.token_version을 기본 0으로 추가합니다.
기존 token_version claim이 없는 JWT는 0으로 해석하여 migration 직후 호환성을 유지합니다.
비밀번호 변경 후에는 DB 버전과 불일치하는 토큰을 401로 거부합니다. 비밀번호를 변경한 사용자가 있으면 downgrade를 차단하며, JWT signing key 교체 및 인증 버전 정리 후 수행해야 합니다.
회원 탈퇴·역할 변경·기존 조직 초대·이메일 변경·refresh token API는 이번 범위에 포함하지 않습니다.
