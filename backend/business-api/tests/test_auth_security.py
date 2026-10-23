from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.domain.auth_exceptions import AuthConfigurationError, InvalidToken, TokenExpired
from app.models import User
from app.models.enums import UserRole
from app.schemas.auth import LoginRequest, TokenResponse

TEST_SECRET = "test-only-jwt-secret-not-for-production-0123456789"
TEST_PASSWORD = "test-only-password-123!"


@pytest.fixture
def auth_settings():
    return Settings(_env_file=None, jwt_secret_key=TEST_SECRET, jwt_algorithm="HS256", jwt_access_token_expire_minutes=30)


@pytest.fixture(scope="module")
def stored_password_hash():
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def token_user():
    return User(id=uuid4(), email="auth@example.test", password_hash="not-read-by-token-logic", role=UserRole.RA)


def claims(user):
    now = int(datetime.now(timezone.utc).timestamp())
    return {"sub": str(user.id), "role": user.role.value, "iat": now, "exp": now + 1800}


def test_argon2_password_hash_and_verify(stored_password_hash):
    assert stored_password_hash != TEST_PASSWORD
    assert stored_password_hash.startswith("$argon2id$")
    assert verify_password(TEST_PASSWORD, stored_password_hash)
    assert not verify_password("wrong-password", stored_password_hash)
    assert not verify_password(TEST_PASSWORD, "not-a-hash")
    assert hash_password(TEST_PASSWORD) != stored_password_hash


def test_create_and_decode_access_token(auth_settings, token_user):
    token = create_access_token(token_user, settings=auth_settings)
    payload = decode_access_token(token, settings=auth_settings)
    assert payload.sub == token_user.id
    assert "organization_id" not in payload.model_dump()
    assert payload.role is UserRole.RA
    assert payload.exp - payload.iat == 1800
    assert isinstance(payload.iat, int)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"


def test_expiration_uses_config(auth_settings, token_user):
    auth_settings.jwt_access_token_expire_minutes = 7
    payload = decode_access_token(create_access_token(token_user, settings=auth_settings), settings=auth_settings)
    assert payload.exp - payload.iat == 420


def test_expired_token(auth_settings, token_user):
    token = create_access_token(token_user, settings=auth_settings, now=datetime.now(timezone.utc) - timedelta(hours=1))
    with pytest.raises(TokenExpired):
        decode_access_token(token, settings=auth_settings)


@pytest.mark.parametrize("case", ["signature", "malformed", "none-alg", "wrong-alg", "future-iat"])
def test_invalid_tokens(auth_settings, token_user, case):
    data = claims(token_user)
    if case == "signature":
        token = jwt.encode(data, "another-test-secret-with-at-least-32-bytes", algorithm="HS256")
    elif case == "none-alg":
        token = jwt.encode(data, "", algorithm="none")
    elif case == "wrong-alg":
        token = jwt.encode(data, TEST_SECRET * 2, algorithm="HS512")
    elif case == "future-iat":
        data["iat"] += 3600
        data["exp"] += 7200
        token = jwt.encode(data, TEST_SECRET, algorithm="HS256")
    else:
        token = "malformed-token"
    with pytest.raises(InvalidToken):
        decode_access_token(token, settings=auth_settings)


@pytest.mark.parametrize("missing", ["sub", "role", "iat", "exp"])
def test_required_claims(auth_settings, token_user, missing):
    data = claims(token_user)
    del data[missing]
    with pytest.raises(InvalidToken):
        decode_access_token(jwt.encode(data, TEST_SECRET, algorithm="HS256"), settings=auth_settings)


@pytest.mark.parametrize("field,value", [
    ("sub", "not-a-uuid"), ("role", "ADMIN"),
    ("iat", "1700000000"), ("exp", "9999999999"), ("exp", 9999999999.5),
    ("iat", []), ("exp", {}), ("iat", True), ("exp", None),
])
def test_claim_formats(auth_settings, token_user, field, value):
    data = claims(token_user)
    data[field] = value
    with pytest.raises(InvalidToken):
        decode_access_token(jwt.encode(data, TEST_SECRET, algorithm="HS256"), settings=auth_settings)


def test_lifetime_order(auth_settings, token_user):
    data = claims(token_user)
    data["iat"] -= 2
    data["exp"] = data["iat"] + 1
    with pytest.raises(TokenExpired):
        decode_access_token(jwt.encode(data, TEST_SECRET, algorithm="HS256"), settings=auth_settings)


@pytest.mark.parametrize("secret", ["", "change-me", "short"])
def test_unusable_secret_rejected(token_user, secret):
    settings = Settings(_env_file=None, jwt_secret_key=secret, jwt_algorithm="HS256", jwt_access_token_expire_minutes=30)
    with pytest.raises(AuthConfigurationError):
        create_access_token(token_user, settings=settings)
    with pytest.raises(AuthConfigurationError):
        decode_access_token("untrusted", settings=settings)


def test_algorithm_is_pinned(auth_settings, token_user):
    auth_settings.jwt_algorithm = "none"
    with pytest.raises(AuthConfigurationError):
        create_access_token(token_user, settings=auth_settings)


def test_auth_settings_and_schema_repr_do_not_expose_secrets(auth_settings):
    assert TEST_SECRET not in repr(auth_settings)
    assert TEST_PASSWORD not in repr(LoginRequest(email="a@example.test", password=TEST_PASSWORD))
    assert "example-token-secret" not in repr(TokenResponse(access_token="example-token-secret", expires_in=1800))
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_access_token_expire_minutes=0)
