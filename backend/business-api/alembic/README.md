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
