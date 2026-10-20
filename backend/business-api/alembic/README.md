# Alembic

Business API 폴더에서 실행합니다. DATABASE_URL은 앱과 동일한 Settings에서 읽습니다.
`env.py`는 `app.models`를 import하고 `Base.metadata`를 참조합니다.
새 ORM 모델은 `app/models/__init__.py`에서 명시적으로 import해야 합니다.
모델 추가 후 `alembic revision --autogenerate -m "설명"`으로 생성하고 수동 검토합니다.
현재 업무 모델과 initial migration은 없으며, 자동 create_all은 사용하지 않습니다.
공유 PostgreSQL의 RAG/checkpoint 소유권 및 schema 분리는 실제 모델 도입 전에 결정해야 합니다.
현재 autogenerate는 기본 schema 기준이므로 다른 소유자의 테이블이 존재하는 공유 DB에서는 실행하지 마세요.
