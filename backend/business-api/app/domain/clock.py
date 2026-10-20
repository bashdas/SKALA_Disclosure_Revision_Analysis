from datetime import datetime, timezone


def utc_timestamp(value: datetime | None = None) -> datetime:
    """Allow an injected aware clock value; never accept an ambiguous naive time."""
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Transition timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)
