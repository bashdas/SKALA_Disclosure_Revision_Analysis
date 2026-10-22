TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


def is_transient_status(status: int) -> bool:
    return status in TRANSIENT_STATUSES
