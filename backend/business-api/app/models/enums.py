from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    RA = "RA"
    ANALYST = "ANALYST"


class AnalysisStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_CONTRACT_CONFIRMATION = "WAITING_CONTRACT_CONFIRMATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RESUME_QUEUED = "RESUME_QUEUED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ImpactType(StrEnum):
    FACT_UPDATE = "FACT_UPDATE"
    CALCULATION_UPDATE = "CALCULATION_UPDATE"
    INTERPRETATION_REVIEW = "INTERPRETATION_REVIEW"
    NO_IMPACT = "NO_IMPACT"
    HOLD = "HOLD"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"


class ValidationStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


def enum_column(enum: type[StrEnum], constraint_name: str) -> SAEnum:
    """Persist values as VARCHAR with a named database CHECK constraint."""
    return SAEnum(
        enum, name=constraint_name, native_enum=False, create_constraint=True,
        validate_strings=True, values_callable=lambda values: [item.value for item in values],
    )
