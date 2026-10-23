from datetime import datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.domain.auth_exceptions import AuthConfigurationError, InvalidToken, TokenExpired
from app.domain.clock import utc_timestamp
from app.models import User
from app.schemas.auth import TokenPayload

_password_hasher = PasswordHasher()  # Argon2id; library-managed random salts and RFC profile.
# Verify a real-cost dummy hash when the email does not exist.
DUMMY_PASSWORD_HASH = _password_hasher.hash("dummy-auth-verification-not-a-user-password")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerificationError, InvalidHashError):
        return False


def _jwt_key(settings: Settings) -> str:
    key = settings.jwt_secret_key.get_secret_value()
    # Pin the algorithm on the server, never derive it from the untrusted JWT header.
    if settings.jwt_algorithm != "HS256" or len(key.encode("utf-8")) < 32:
        raise AuthConfigurationError()
    return key


def create_access_token(user: User, *, settings: Settings | None = None, now: datetime | None = None) -> str:
    settings = settings if settings is not None else get_settings()
    key = _jwt_key(settings)
    issued = utc_timestamp(now)
    expires = issued + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = TokenPayload(
        sub=user.id, role=user.role,
        token_version=user.token_version or 0,
        iat=int(issued.timestamp()), exp=int(expires.timestamp()),
    )
    return jwt.encode(payload.model_dump(mode="json"), key, algorithm="HS256")


def decode_access_token(token: str, *, settings: Settings | None = None) -> TokenPayload:
    settings = settings if settings is not None else get_settings()
    key = _jwt_key(settings)
    try:
        claims = jwt.decode(
            token, key, algorithms=["HS256"],
            options={"require": ["sub", "role", "exp", "iat"]},
        )
        return TokenPayload.model_validate(claims)
    except jwt.ExpiredSignatureError:
        raise TokenExpired() from None
    except (jwt.InvalidTokenError, ValidationError, TypeError, ValueError, OverflowError):
        raise InvalidToken() from None
