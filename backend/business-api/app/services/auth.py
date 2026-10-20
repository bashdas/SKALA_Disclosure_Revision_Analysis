from app.core.config import Settings, get_settings
from app.core.security import DUMMY_PASSWORD_HASH, create_access_token, verify_password
from app.domain.auth_exceptions import InvalidCredentials
from app.models import User
from app.repositories import UserRepository
from app.schemas.auth import TokenResponse


class AuthService:
    def __init__(self, users: UserRepository, settings: Settings | None = None):
        self.users = users
        self.settings = settings if settings is not None else get_settings()

    def authenticate(self, email: str, password: str) -> User:
        user = self.users.get_by_email(email)
        valid = verify_password(password, user.password_hash if user is not None else DUMMY_PASSWORD_HASH)
        if user is None or not valid:
            raise InvalidCredentials()
        return user

    def create_token(self, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=create_access_token(user, settings=self.settings),
            expires_in=self.settings.jwt_access_token_expire_minutes * 60,
        )
