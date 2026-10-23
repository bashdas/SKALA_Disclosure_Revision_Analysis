from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    RA = "RA"
    ANALYST = "ANALYST"


class AnalysisStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SAVING = "SAVING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    SAVE_FAILED = "SAVE_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ImpactType(StrEnum):
    FACT_UPDATE = "FACT_UPDATE"
    CALCULATION_UPDATE = "CALCULATION_UPDATE"
    INTERPRETATION_REVIEW = "INTERPRETATION_REVIEW"
    NO_IMPACT = "NO_IMPACT"
    HOLD = "HOLD"


class AnalysisStage(StrEnum):
    REQUEST_VALIDATION = "REQUEST_VALIDATION"
    INPUT_COLLECTION = "INPUT_COLLECTION"
    RAG_PREPARATION = "RAG_PREPARATION"
    BASE_ANALYSIS = "BASE_ANALYSIS"
    PERSPECTIVE_ANALYSIS = "PERSPECTIVE_ANALYSIS"
    REPORT_GENERATION = "REPORT_GENERATION"
    REPORT_SAVE = "REPORT_SAVE"


class PerspectiveType(StrEnum):
    FINANCE = "FINANCE"
    FX_HEDGE = "FX_HEDGE"
    INDUSTRY_CONTRACT = "INDUSTRY_CONTRACT"
    MARKET_NEWS = "MARKET_NEWS"


class PerspectiveStatus(StrEnum):
    REGISTERED = "REGISTERED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    LIMIT_REACHED = "LIMIT_REACHED"
    FAILED = "FAILED"


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
