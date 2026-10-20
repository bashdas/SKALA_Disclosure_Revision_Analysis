from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog


class AuditLogRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, log: AuditLog) -> AuditLog:
        self.session.add(log)
        self.session.flush()
        return log

    def list_by_resource(self, resource_type: str, resource_id: str, *, organization_id: UUID) -> list[AuditLog]:
        return list(self.session.scalars(select(AuditLog).where(AuditLog.organization_id == organization_id, AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id).order_by(AuditLog.created_at, AuditLog.id)))
