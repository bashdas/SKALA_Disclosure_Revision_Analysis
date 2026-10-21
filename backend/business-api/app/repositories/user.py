from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def get_by_id_and_organization(self, user_id: UUID, organization_id: UUID) -> User | None:
        return self.session.scalar(select(User).where(User.id == user_id, User.organization_id == organization_id))

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_id_for_update(self, user_id: UUID) -> User | None:
        return self.session.scalar(select(User).where(User.id == user_id)
            .with_for_update().execution_options(populate_existing=True))
