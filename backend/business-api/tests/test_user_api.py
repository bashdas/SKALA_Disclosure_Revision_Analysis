from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.api.user import router as user_router
from app.api.exception_handlers import install_exception_handlers
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.domain.auth_exceptions import InvalidToken
from app.models import User
from app.models.enums import UserRole
from app.repositories import UserRepository
from app.schemas.auth import CurrentUser, TokenPayload
from app.services.user import UserService
from test_auth_security import TEST_PASSWORD, auth_settings, stored_password_hash
from test_domain import graph, migrated_engine
from sqlalchemy.orm import Session
from sqlalchemy import func, select

NEW_PASSWORD = "new-test-only-password-456!"


@pytest.fixture
def db(migrated_engine):
    # Each request commit/rollback affects its savepoint, never the seed transaction.
    with migrated_engine.connect() as connection:
        outer = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        outer.rollback()


@pytest.fixture
def user_client(db, graph, auth_settings, stored_password_hash):
    graph.user.password_hash = stored_password_hash
    graph.user.email = "analyst@example.com"
    # 요청의 rollback이 초기 자료를 되돌리지 않도록 바깥 트랜잭션 안의 준비용 savepoint를 마칩니다.
    db.commit()
    application = FastAPI()
    application.include_router(auth_router)
    application.include_router(user_router)
    install_exception_handlers(application)
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(application) as client:
        yield client


def headers(graph, settings):
    return {"Authorization": "Bearer " + create_access_token(graph.user, settings=settings)}


@pytest.mark.postgres
@pytest.mark.parametrize("role", [UserRole.RA, UserRole.ANALYST])
def test_get_own_profile(user_client, graph, db, auth_settings, role):
    graph.user.role = role
    db.flush()
    response = user_client.get("/api/v1/users/me", headers=headers(graph, auth_settings), params={"user_id": str(uuid4()), "organization_id": str(uuid4())})
    assert response.status_code == 200
    assert response.json()["id"] == str(graph.user.id)
    assert set(response.json()) == {"id", "email", "name", "role", "created_at"}


@pytest.mark.postgres
@pytest.mark.parametrize("path,method", [("/api/v1/users/me", "get"), ("/api/v1/users/me/password", "patch")])
def test_member_requires_auth(user_client, path, method):
    assert getattr(user_client, method)(path).status_code == 401


@pytest.mark.postgres
def test_password_change_invalidates_all_old_tokens(user_client, graph, db, auth_settings):
    token1 = headers(graph, auth_settings)
    token2 = headers(graph, auth_settings)
    response = user_client.patch("/api/v1/users/me/password", headers=token1,
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD})
    assert response.status_code == 204 and not response.content
    assert verify_password(NEW_PASSWORD, graph.user.password_hash)
    assert graph.user.token_version == 1
    assert user_client.get("/api/v1/users/me", headers=token1).status_code == 401
    assert user_client.get("/api/v1/users/me", headers=token2).status_code == 401
    assert user_client.post("/api/v1/auth/login", json={"email": graph.user.email, "password": TEST_PASSWORD}).status_code == 401
    login = user_client.post("/api/v1/auth/login", json={"email": graph.user.email, "password": NEW_PASSWORD})
    assert login.status_code == 200
    fresh = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert user_client.get("/api/v1/users/me", headers=fresh).status_code == 200


@pytest.mark.postgres
@pytest.mark.parametrize("current,new,code", [("wrong-password", NEW_PASSWORD, "INVALID_CURRENT_PASSWORD"), (TEST_PASSWORD, TEST_PASSWORD, "PASSWORD_UNCHANGED")])
def test_password_rejection_preserves_hash(user_client, graph, auth_settings, current, new, code):
    old = graph.user.password_hash
    response = user_client.patch("/api/v1/users/me/password", headers=headers(graph, auth_settings), json={"current_password": current, "new_password": new})
    assert response.status_code == 400 and response.json()["error"]["code"] == code
    assert graph.user.password_hash == old
    assert graph.user.token_version == 0
    assert current not in response.text and new not in response.text


@pytest.mark.postgres
@pytest.mark.parametrize("extra", [{"new_password": "short"}, {"role":"RA"}, {"organization_id":str(uuid4())}])
def test_password_validation_is_safe(user_client, graph, auth_settings, extra):
    response = user_client.patch("/api/v1/users/me/password", headers=headers(graph, auth_settings), json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD, **extra})
    assert response.status_code == 422
    assert TEST_PASSWORD not in response.text and NEW_PASSWORD not in response.text


@pytest.mark.postgres
def test_change_password_rollback(user_client, graph, db, auth_settings):
    old = graph.user.password_hash
    with patch.object(db, "commit", side_effect=RuntimeError("test-commit-failed")):
        with pytest.raises(RuntimeError, match="test-commit-failed"):
            user_client.patch("/api/v1/users/me/password", headers=headers(graph, auth_settings), json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD})
    assert graph.user.password_hash == old
    assert graph.user.token_version == 0
    assert user_client.get("/api/v1/users/me", headers=headers(graph, auth_settings)).status_code == 200


@pytest.mark.postgres
def test_concurrent_revoked_request_cannot_change_password(user_client, graph, db, auth_settings):
    from app.core.security import decode_access_token
    payload = decode_access_token(create_access_token(graph.user, settings=auth_settings), settings=auth_settings)
    principal = CurrentUser(id=graph.user.id, email=graph.user.email, role=graph.user.role)
    graph.user.token_version = 1
    db.flush()
    with pytest.raises(InvalidToken):
        UserService(UserRepository(db)).change_password(principal, payload, TEST_PASSWORD, NEW_PASSWORD)


@pytest.mark.postgres
@pytest.mark.parametrize("role", ["ANALYST", "RA"])
def test_signup_login_and_profile(user_client, db, role):
    response = user_client.post("/api/v1/auth/signup", json={"email":"signup@example.com", "password":NEW_PASSWORD, "name":"건민", "role":role})
    assert response.status_code == 201
    body = response.json()
    assert "organization_id" not in body and "organization_name" not in body
    assert body["role"] == role
    assert "password" not in body and "password_hash" not in body and "token_version" not in body
    registered = UserRepository(db).get_by_email("signup@example.com")
    assert verify_password(NEW_PASSWORD, registered.password_hash)
    login = user_client.post("/api/v1/auth/login", json={"email":"signup@example.com", "password":NEW_PASSWORD})
    assert login.status_code == 200
    own = user_client.get("/api/v1/users/me", headers={"Authorization":"Bearer " + login.json()["access_token"]})
    assert own.status_code == 200 and own.json()["id"] == body["id"]


@pytest.mark.postgres
def test_duplicate_signup_does_not_create_user(user_client, db, graph):
    count = db.scalar(select(func.count()).select_from(User))
    response = user_client.post("/api/v1/auth/signup", json={"email":graph.user.email, "password":NEW_PASSWORD, "name":"건민"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"
    assert db.scalar(select(func.count()).select_from(User)) == count


@pytest.mark.postgres
@pytest.mark.parametrize("changes", [
    {"role":"ADMIN"}, {"organization_id":str(uuid4())}, {"user_id":str(uuid4())},
    {"email":"invalid-email"}, {"password":"short"}, {"password":" " * 12},
    {"name":"건민", "organization_name":" "}, {"name":"건민", "organization_name":"x" * 256},
    {"name":"건민", "organization_name":"bad\x00name"}, {"password":"abc\x00defghijklmnop"},
])
def test_signup_rejects_invalid_or_privileged_inputs(user_client, changes):
    response = user_client.post("/api/v1/auth/signup", json={"email":"valid@example.com", "password":NEW_PASSWORD, "name":"건민", **changes})
    assert response.status_code == 422
    assert NEW_PASSWORD not in response.text


@pytest.mark.postgres
def test_signup_atomic_rollback(user_client, db):
    before = db.scalar(select(func.count()).select_from(User))
    with patch.object(UserRepository, "add", side_effect=RuntimeError("insert-failed")):
        with pytest.raises(RuntimeError, match="insert-failed"):
            user_client.post("/api/v1/auth/signup", json={"email":"rollback@example.com", "password":NEW_PASSWORD, "name":"건민"})
    assert db.scalar(select(func.count()).select_from(User)) == before
    assert UserRepository(db).get_by_email("rollback@example.com") is None


@pytest.mark.postgres
def test_concurrent_signup_unique_email(migrated_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.domain.auth_exceptions import EmailAlreadyRegistered

    email = f"race-{uuid4().hex}@example.com"
    name = f"Race-{uuid4().hex}"
    barrier = Barrier(2)

    class ConcurrentUsers(UserRepository):
        def get_by_email(self, email):
            result = super().get_by_email(email)
            barrier.wait(timeout=5)
            return result

    def signup_once():
        with Session(migrated_engine) as session:
            try:
                return UserService(ConcurrentUsers(session)).signup(email, NEW_PASSWORD, name=name).id
            except EmailAlreadyRegistered:
                return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: signup_once(), range(2)))
        assert sum(result is not None for result in results) == 1
        with Session(migrated_engine) as session:
            assert session.scalar(select(func.count()).select_from(User).where(User.email == email)) == 1
    finally:
        with Session(migrated_engine) as session:
            user = session.scalar(select(User).where(User.email == email))
            if user is not None:
                session.delete(user)
                session.flush()
                session.commit()


@pytest.mark.postgres
def test_name_update_and_withdraw_preserve_auth_boundary(user_client, request, db):
    context = request.getfixturevalue("graph")
    settings = request.getfixturevalue("auth_settings")
    token = headers(context, settings)
    response = user_client.patch("/api/v1/users/me", headers=token, json={"name": "  박건민  "})
    assert response.status_code == 200 and response.json()["name"] == "박건민"
    assert user_client.patch("/api/v1/users/me", headers=token, json={"name": "  "}).status_code == 422
    old_email = context.user.email
    rejected = user_client.request("DELETE", "/api/v1/users/me", headers=token, json={"password": "wrong"})
    assert rejected.status_code == 400 and context.user.is_active
    response = user_client.request("DELETE", "/api/v1/users/me", headers=token, json={"password": TEST_PASSWORD})
    assert response.status_code == 204
    assert not context.user.is_active and context.user.name == "" and context.user.email != old_email
    assert db.get(type(context.memo), context.memo.id) is not None
    assert user_client.get("/api/v1/users/me", headers=token).status_code == 401
    assert user_client.post("/api/v1/auth/login", json={"email": old_email, "password": TEST_PASSWORD}).status_code == 401
