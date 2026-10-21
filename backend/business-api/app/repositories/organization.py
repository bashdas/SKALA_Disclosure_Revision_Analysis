from sqlalchemy.orm import Session

from app.models import Organization


class OrganizationRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        self.session.flush()
        return organization
