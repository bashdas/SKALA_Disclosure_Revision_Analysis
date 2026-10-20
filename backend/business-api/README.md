# Business API — Core Domain Schema

구현 담당자: 박다솔. 기존 SQLAlchemy 2.x sync + psycopg 3, Base 및 세션 관리 방식을 유지합니다. 이번 단계는 Enum·ORM·DB constraint·migration만 포함하며 Service, Repository 업무 기능, API, 상태 전이 로직은 없습니다.

## 모델과 관계

모든 모델은 `app.models`에서 import할 수 있습니다. 모델 구현은 `app/models/domain.py`, Enum은 `app/models/enums.py`에 있습니다. 14개 테이블은 PostgreSQL `core` schema에 한정합니다.

| Model | 책임 / 최소 relationship |
| --- | --- |
| Organization | users, filings, memos, analysis_tasks |
| User | 조직 FK, 전역 unique email, password_hash, UserRole |
| Filing | 조직별 접수번호, 회사·공시 종류·공시시각 |
| FilingVersion | 공시 FK, 버전과 원문·content_hash |
| Contract | 공시 FK, 계약 금액과 날짜 |
| Memo | 조직 FK, 현재 버전; memo_versions |
| MemoVersion | 메모·작성자 FK, 버전별 본문 |
| AnalysisTask | 조직·요청자·공시·메모 FK; revision_proposals, analysis_events, approval |
| RevisionProposal | 작업 FK, 주장 식별자, 영향·수정안·검증상태·근거 |
| Approval | 작업별 1개 승인 기록; approval_items |
| ApprovalItem | 승인·제안 FK, 항목별 approved |
| AnalysisEvent | 작업별 sequence, event_type, payload_json |
| AuditLog | 조직·사용자 FK, 행위·대상·metadata_json |
| RevisionApplication | 작업·승인·제안 FK, 적용 결과 버전과 중복 방지 |

relationship은 필요한 부모→자식 방향만 추가했습니다. 컬렉션 이름은 `memo_versions`, `revision_proposals`, `analysis_events`, `approval_items`이며 버전과 이벤트는 번호순으로 탐색합니다.

## 타입과 선택 사항

- PK/FK는 UUID입니다. ORM에서 UUID4를 생성합니다. raw SQL INSERT 시에는 id를 직접 전달해야 합니다.
- 5개 Enum은 StrEnum + SQLAlchemy Enum(`native_enum=False`, `validate_strings=True`)으로 매핑합니다. DB에는 VARCHAR + 이름 있는 CHECK가 생성됩니다. PostgreSQL enum TYPE 변경·삭제 순서를 피하면서 DB에서도 잘못된 값을 차단합니다. Enum 값 변경은 CHECK 변경 migration을 수동 검토해야 합니다.
- 모든 `*_at`는 `TIMESTAMP WITH TIME ZONE`입니다. 생성시각은 DB `now()`로 생성하며 UTC instant로 저장됩니다. 반환 offset은 DB 세션 timezone을 따르므로 외부 직렬화 시 UTC로 정규화해야 합니다. PostgreSQL 세션 timezone은 UTC를 권장합니다.
- Memo/AnalysisTask의 updated_at은 ORM UPDATE 시 `onupdate=now()`로 갱신합니다. raw SQL UPDATE는 작성자가 직접 갱신해야 하며 별도 trigger는 없습니다.
- 금액은 Python Decimal / `NUMERIC(24,4)`입니다. float 계산을 사용하지 않습니다. 20자리 정수부·4자리 소수부를 지원하며 통화 단위는 현재 필드에 추가하지 않았습니다. 소수점 초과 입력은 PostgreSQL Numeric의 반올림 규칙을 따릅니다.
- JSONB는 evidence_json, payload_json, metadata_json이며 기본값은 객체 `{}`입니다. ORM에서 중첩 객체를 제자리 수정하면 변경 추적이 보장되지 않으므로 새 dict를 대입하세요.
- Contract.counterparty/start_date/end_date는 미확정 정보를 위해 nullable이며 amount는 필수입니다. 금액 부호·계약 날짜 순서에 대한 추가 업무 규칙은 아직 강제하지 않습니다.
- after_text는 HOLD·INTERPRETATION_REVIEW 등 수정문이 없는 경우를 위해 nullable입니다. 영향 유형별 조건 검사는 향후 Service 책임입니다.
- Approval.approved_by/approved_at은 PENDING 상태의 미결정 값을 위해 nullable입니다. 상태별 필수 여부는 향후 Service에서 검증합니다.
- AnalysisTask.started_at/completed_at/error_code/error_message는 아직 발생하지 않은 값이므로 nullable입니다. thread_id는 생성 시 호출자가 제공하는 필수 문자열입니다.

## 제약조건과 index

- User.email은 전역 unique이며 case-sensitive입니다. 로그인 도입 시 이메일 정규화 정책을 별도로 결정해야 합니다.
- Filing은 `(organization_id, receipt_no)` unique입니다. 같은 외부 공시를 여러 조직이 각각 관리할 수 있습니다.
- `(filing_id, version)`, `(memo_id, version)`, `(analysis_task_id, sequence)`, `(approval_id, revision_proposal_id)`는 unique입니다.
- AnalysisTask.thread_id는 전역 unique로, 한 작업의 재개·재시도는 같은 작업/thread를 재사용합니다.
- Approval.analysis_task_id는 unique입니다. 이 모델은 작업당 승인 기록 1개를 표현하며 별도 재승인 라운드는 아직 없습니다.
- RevisionApplication.revision_proposal_id는 unique로 중복 적용을 차단합니다.
- 버전·현재 버전·기준 버전·결과 버전·이벤트 순번은 모두 `>= 1` CHECK가 있습니다.
- PK/unique index를 조회에도 활용합니다. 조직별 공시·버전별 메모·작업별 이벤트 조회에는 복합 unique의 선두 컬럼을 사용하므로 중복 index를 만들지 않습니다.
- 별도 index: User.organization_id, Filing.receipt_no, Contract.filing_id, Memo.organization_id, AnalysisTask의 `(organization_id,status)`·status·memo_id·filing_id, RevisionProposal.analysis_task_id, AuditLog의 `(organization_id,created_at)`, RevisionApplication.analysis_task_id.
- 모든 FK는 ON DELETE RESTRICT입니다. ORM relationship은 삭제 cascade/delete-orphan 없이 passive_deletes="all"을 사용합니다. 부모와 컬렉션이 로딩되어 있어도 ORM이 자식을 지우거나 FK를 NULL로 만들지 않으며 참조가 있으면 부모 삭제가 실패합니다.

현재 FK는 개별 참조 존재를 보장합니다. 조직 간 참조 일치, 승인/제안/적용 기록이 같은 작업인지, current/base/result 버전이 해당 메모에 실제 존재하는지는 별도 복합 FK나 trigger로 강제하지 않습니다. 이 일관성 검사는 다음 Service/Repository 단계에서 반드시 구현해야 합니다. MemoVersion은 보존 대상으로 취급하지만 직접 UPDATE/DELETE를 DB trigger로 금지하지는 않습니다. 삭제 API나 변경 로직은 이번에 구현하지 않았습니다.

## Migration

`alembic/README.md` 참고. initial revision은 `0001_initial_core`입니다.

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
