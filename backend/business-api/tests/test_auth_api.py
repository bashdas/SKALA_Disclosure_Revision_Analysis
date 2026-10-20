from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.api.dependencies import get_current_organization_id, get_current_user, require_roles
from app.api.exception_handlers import install_exception_handlers
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token
from app.models import Organization, User
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser
from test_auth_security import TEST_PASSWORD, TEST_SECRET, auth_settings, stored_password_hash
from test_domain import db, graph, migrated_engine


def build_test_app():
    # These routes exist only inside the test app, not in the production API.
    app = FastAPI()
    app.include_router(auth_router)
    install_exception_handlers(app)

    @app.get("/protected")
    def protected(user: Annotated[CurrentUser, Depends(get_current_user)]):
        return user

    @app.get("/organization")
    def organization(organization_id: Annotated[UUID, Depends(get_current_organization_id)]):
        return {"organization_id": str(organization_id)}

    @app.get("/ra")
    def ra(user: Annotated[CurrentUser, Depends(require_roles(UserRole.RA))]):
        return {"role": user.role}

    @app.get("/analyst")
    def analyst(user: Annotated[CurrentUser, Depends(require_roles(UserRole.ANALYST))]):
        return {"role": user.role}

    @app.get("/both")
    def both(user: Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST))]):
        return {"role": user.role}

    return app


@pytest.fixture
def client(db, graph, auth_settings, stored_password_hash):
    graph.user.password_hash = stored_password_hash
    db.flush()
    app = build_test_app()

    def session_override():
        yield db

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as client:
        yield client


def bearer(user, settings, **options):
    return {"Authorization": "Bearer " + create_access_token(user, settings=settings, **options)}


@pytest.mark.postgres
def test_login_success(client, graph, auth_settings):
    response = client.post("/api/v1/auth/login", json={"email": graph.user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert decode_access_token(body["access_token"], settings=auth_settings).sub == graph.user.id
    assert "password" not in body and "password_hash" not in body


@pytest.mark.postgres
def test_login_failures_are_indistinguishable(client, graph):
    missing = client.post("/api/v1/auth/login", json={"email": "absent@example.test", "password": TEST_PASSWORD})
    wrong = client.post("/api/v1/auth/login", json={"email": graph.user.email, "password": "wrong-password"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid credentials"}}
    assert missing.headers["www-authenticate"] == wrong.headers["www-authenticate"] == "Bearer"


@pytest.mark.postgres
def test_current_user_and_organization_come_from_db(client, graph, auth_settings):
    headers = bearer(graph.user, auth_settings)
    response = client.get("/protected", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"id": str(graph.user.id), "organization_id": str(graph.org.id), "email": graph.user.email, "role": "ANALYST"}
    response = client.get("/organization", headers=headers, params={"organization_id": str(uuid4())})
    assert response.json() == {"organization_id": str(graph.org.id)}


@pytest.mark.postgres
@pytest.mark.parametrize("header", [None, "Basic ignored", "Bearer malformed", "Bearer"])
def test_missing_or_invalid_authorization(client, header):
    response = client.get("/protected", headers={} if header is None else {"Authorization": header})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.postgres
def test_expired_token_http(client, graph, auth_settings):
    response = client.get("/protected", headers=bearer(graph.user, auth_settings, now=datetime.now(timezone.utc) - timedelta(hours=1)))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.postgres
def test_missing_user_is_masked_as_invalid_token(client, graph, auth_settings):
    deleted = User(id=uuid4(), organization_id=graph.org.id, role=graph.user.role)
    response = client.get("/protected", headers=bearer(deleted, auth_settings))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"
    assert "USER_NOT_FOUND" not in response.text


@pytest.mark.postgres
@pytest.mark.parametrize("field", ["organization", "role"])
def test_stale_claims_rejected_against_current_db_user(client, db, graph, auth_settings, field):
    headers = bearer(graph.user, auth_settings)
    if field == "organization":
        org = Organization(name="Moved org")
        db.add(org)
        db.flush()
        graph.user.organization_id = org.id
    else:
        graph.user.role = UserRole.RA
    db.flush()
    response = client.get("/protected", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.postgres
@pytest.mark.parametrize("role,allowed,denied", [(UserRole.RA, "/ra", "/analyst"), (UserRole.ANALYST, "/analyst", "/ra")])
def test_role_authorization(client, db, graph, auth_settings, role, allowed, denied):
    graph.user.role = role
    db.flush()
    headers = bearer(graph.user, auth_settings)
    assert client.get(allowed, headers=headers).status_code == 200
    assert client.get("/both", headers=headers).status_code == 200
    response = client.get(denied, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.postgres
def test_login_is_read_only(client, db, graph, stored_password_hash, caplog):
    def no_transaction_control(*args, **kwargs):
        raise AssertionError("Login must not commit, rollback or close the caller session")

    from unittest.mock import patch
    with patch.object(db, "commit", no_transaction_control), patch.object(db, "rollback", no_transaction_control), patch.object(db, "close", no_transaction_control):
        assert client.post("/api/v1/auth/login", json={"email": graph.user.email, "password": TEST_PASSWORD}).status_code == 200
    assert graph.user.password_hash == stored_password_hash
    assert TEST_PASSWORD not in caplog.text
    assert stored_password_hash not in caplog.text
    assert TEST_SECRET not in caplog.text


def test_missing_auth_does_not_open_database(auth_settings):
    app = build_test_app()
    app.dependency_overrides[get_settings] = lambda: auth_settings

    def forbidden_database_access():
        raise AssertionError("Unauthenticated request must not open database")

    app.dependency_overrides[get_db] = forbidden_database_access
    with TestClient(app) as client:
        response = client.get("/protected")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_validation_does_not_echo_password():
    app = build_test_app()
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"password": TEST_PASSWORD})
        assert response.status_code == 422
        assert TEST_PASSWORD not in response.text
        response = client.post("/api/v1/auth/login", json={"email": "user@example.test", "password": "x" * 1025})
        assert response.status_code == 422
        assert "x" * 1025 not in response.text


def test_health_without_secret_or_auth(monkeypatch):
    from app.main import app
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert not set(app.openapi()["paths"]) & {"/protected", "/ra", "/both"}


def test_empty_roles_rejected():
    with pytest.raises(ValueError, match="at least one"):
        require_roles()


@pytest.mark.postgres
def test_production_app_login_registration(db, graph, stored_password_hash, auth_settings):
    from app.main import app
    graph.user.password_hash = stored_password_hash
    db.flush()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: auth_settings
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/login", json={"email": graph.user.email, "password": TEST_PASSWORD})
            assert response.status_code == 200
            assert decode_access_token(response.json()["access_token"], settings=auth_settings).sub == graph.user.id
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_unconfigured_auth_returns_safe_service_unavailable():
    app = build_test_app()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, jwt_secret_key="", jwt_algorithm="HS256", jwt_access_token_expire_minutes=30)

    def forbidden_database_access():
        raise AssertionError("Invalid auth configuration must fail before DB access")

    app.dependency_overrides[get_db] = forbidden_database_access
    with TestClient(app) as client:
        response = client.get("/protected", headers={"Authorization": "Bearer untrusted"})
        assert response.status_code == 503
        assert response.json() == {"error": {"code": "AUTH_CONFIGURATION_ERROR", "message": "Authentication unavailable"}}
