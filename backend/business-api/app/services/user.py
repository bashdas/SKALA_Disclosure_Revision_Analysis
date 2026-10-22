from app.core.security import hash_password, verify_password
from app.domain.auth_exceptions import EmailAlreadyRegistered, InvalidCurrentPassword, InvalidToken, PasswordUnchanged
from sqlalchemy.exc import IntegrityError
from app.models import Organization, User, CompanyFavorite
from sqlalchemy import delete
from secrets import token_urlsafe
from app.models.enums import UserRole
from app.repositories.organization import OrganizationRepository
from app.repositories import UserRepository
from app.schemas.auth import CurrentUser, TokenPayload
from app.schemas.user import SignupResponse, UserResponse


class UserService:
    def __init__(self, users: UserRepository):
        self.users = users

    def get_me(self, principal: CurrentUser) -> UserResponse:
        user = self.users.get_by_id_and_organization(principal.id, principal.organization_id)
        if user is None:
            raise InvalidToken()
        return UserResponse.model_validate(user)

    def change_password(self, principal: CurrentUser, payload: TokenPayload, current_password: str, new_password: str) -> None:
        session = self.users.session
        try:
            user = self._active_user(principal, payload)
            if not verify_password(current_password, user.password_hash):
                raise InvalidCurrentPassword()
            if verify_password(new_password, user.password_hash):
                raise PasswordUnchanged()
            user.password_hash = hash_password(new_password)
            user.token_version += 1
            session.flush()
            session.commit()
        except Exception:
            session.rollback()
            raise

    def signup(self, email: str, password: str, organization_name: str, name: str = "") -> SignupResponse:
        session = self.users.session
        try:
            if self.users.get_by_email(email) is not None:
                raise EmailAlreadyRegistered()
            organization = OrganizationRepository(session).add(Organization(name=organization_name))
            user = self.users.add(User(organization_id=organization.id, email=email,
                name=name, password_hash=hash_password(password), role=UserRole.ANALYST, token_version=0))
            result = SignupResponse(**UserResponse.model_validate(user).model_dump(), organization_name=organization.name)
            session.commit()
            return result
        except IntegrityError as error:
            session.rollback()
            # Concurrent signups are arbitrated by PostgreSQL's existing unique constraint.
            if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == "uq_users_email":
                raise EmailAlreadyRegistered() from None
            raise
        except Exception:
            session.rollback()
            raise

    def update_name(self, principal: CurrentUser, payload: TokenPayload, name: str) -> UserResponse:
        session = self.users.session
        try:
            user = self._active_user(principal, payload)
            user.name = name
            session.flush()
            result = UserResponse.model_validate(user)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise

    def _active_user(self, principal: CurrentUser, payload: TokenPayload) -> User:
        user = self.users.get_by_id_for_update(principal.id)
        if (user is None or not user.is_active or user.organization_id != principal.organization_id
                or user.role != payload.role or user.token_version != payload.token_version):
            raise InvalidToken()
        return user

    def delete_account(self, principal: CurrentUser, payload: TokenPayload, password: str) -> None:
        session = self.users.session
        try:
            user = self._active_user(principal, payload)
            if not verify_password(password, user.password_hash):
                raise InvalidCurrentPassword()
            # 작성자 참조를 보존하면서 개인정보와 로그인 권한을 제거합니다.
            user.name = ""
            user.email = f"deleted-{user.id}@invalid.example"
            user.password_hash = hash_password(token_urlsafe(48))
            user.is_active = False
            user.token_version += 1
            session.execute(delete(CompanyFavorite).where(CompanyFavorite.user_id == user.id))
            session.commit()
        except Exception:
            session.rollback()
            raise
