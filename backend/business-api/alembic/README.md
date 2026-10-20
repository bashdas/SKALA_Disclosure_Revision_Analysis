# Alembic — Business Core

Business API 폴더에서 실행합니다. DATABASE_URL은 앱과 동일한 Settings에서 읽습니다.
`env.py`는 `app.models`를 import하고 기존 `Base.metadata`를 참조합니다.
새 ORM 모델은 `app/models/__init__.py`에서 명시적으로 import해야 합니다.

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
# 향후 변경 생성 후 반드시 수동 검토
# .venv/bin/alembic revision --autogenerate -m "change description"
```

`0001_initial_core`는 core schema 및 14개 업무 테이블을 생성합니다.
첫 적용은 core schema가 아직 없는 DB를 전제로 합니다. 기존 core가 있다면 이름 충돌과 소유권을 먼저 검토하세요.
앱 계정 또는 migration 계정은 schema 생성 권한이 필요합니다.
`alembic_version`은 기존 호환성을 위해 public에 유지합니다. 다른 서비스는 별도 version table 또는 별도 schema로 migration 이력을 관리해야 합니다.

Autogenerate는 `include_schemas=True`와 schema 필터로 core만 비교하므로 rag/checkpoint/public 업무 테이블을 건드리지 않습니다.
Enum은 VARCHAR + 이름 있는 CHECK를 사용합니다. Alembic은 CHECK 정의 변경을 완전히 자동 검출하지 않으므로 Enum 값 변경 시 CHECK 교체 migration을 명시적으로 작성하고 검토하세요.

테스트 전용 DB에서 `alembic downgrade base` 후 `alembic upgrade head`로 왕복할 수 있습니다.
Downgrade는 업무 테이블과 데이터를 제거하고 마지막에 `DROP SCHEMA core RESTRICT`를 실행합니다. CASCADE를 사용하지 않아 예상 밖의 객체가 있으면 실패합니다.
정상 서비스의 부모 row 삭제 RESTRICT 정책과 schema rollback은 별개입니다.
운영 데이터가 있는 DB에 downgrade를 실행하기 전에는 별도 백업 및 변경 계획이 필요합니다.
`create_all`은 앱 시작이나 테스트에 사용하지 않습니다.

## 0002_align_report_flow

커밋된 0001은 변경하지 않습니다. 0002는 Approval 관련 3개 테이블을 삭제하고 Task 입력 snapshot·stage·warning을 추가하며 filing_id를 nullable로 변경합니다. 관점 작업과 보고서 테이블 및 unique/index/CHECK를 생성합니다. VARCHAR+CHECK Enum 방식이므로 PostgreSQL enum TYPE은 변경하지 않습니다. status CHECK는 명시적으로 교체하며 migration은 앱 Enum을 import하지 않고 당시 값을 고정합니다.

기존 Task의 접수번호와 기업명은 Filing에서 backfill하고 corp_code는 NULL로 둡니다. 기존 WAITING_CONTRACT_CONFIRMATION/WAITING_APPROVAL/RESUME_QUEUED 작업이 있으면 자동 상태 변환 없이 upgrade 전에 중단합니다. 수동 조정 기준을 결정하고 정리한 뒤 재실행하세요.

Approval 테이블 데이터는 삭제되며 downgrade로 복구되지 않습니다. 필요한 데이터는 적용 전에 별도로 보관하세요. Memo/MemoVersion은 update하지 않습니다.

`alembic downgrade 0001_initial_core`는 새 보고서·관점 데이터가 있거나 filing_id가 NULL인 작업·새 전용 상태가 있으면 사전 guard로 중단합니다. 보호 대상 결과를 보관하고 호환성을 확보한 경우에만 되돌릴 수 있습니다. 성공해도 신규 snapshot/stage/warning 컬럼은 삭제되며 승인 테이블은 빈 상태로만 재생성됩니다. 완전한 데이터 복구를 제공하는 downgrade가 아닙니다.

빈 DB에서는 `upgrade head → downgrade base → upgrade head`가 가능합니다. 테스트는 빈 DB 왕복 외에도 이전 승인 이력이 있는 DB의 upgrade/backfill, 실패 시 transaction rollback, 안전한 downgrade 거부 및 호환 데이터의 재-upgrade를 검증합니다.
