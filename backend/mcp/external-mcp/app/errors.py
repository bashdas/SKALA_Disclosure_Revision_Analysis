class OpenDartError(Exception):
    MESSAGES = {
        "INVALID_RECEIPT_NO": "receipt_no must contain exactly 14 ASCII digits",
        "DISCLOSURE_NOT_FOUND": "Disclosure document not found",
        "OPENDART_AUTH_FAILED": "OpenDART authentication failed or key is not configured",
        "OPENDART_RATE_LIMITED": "OpenDART request limit exceeded",
        "OPENDART_TIMEOUT": "OpenDART request timed out",
        "OPENDART_UNAVAILABLE": "OpenDART is unavailable or returned an invalid response",
        "DISCLOSURE_PARSE_FAILED": "Disclosure document could not be parsed safely",
    }

    def __init__(self, code: str, *, provider_status: str | None = None):
        self.code, self.provider_status = code, provider_status
        super().__init__(self.MESSAGES[code])

    def as_dict(self):
        return {"code": self.code, "message": str(self), "provider_status": self.provider_status}


def check_status(status: str, *, allow_empty=False):
    if status == "000":
        return
    if allow_empty and status in ("013", "014"):
        return
    if status in ("010", "011", "012", "901"):
        code = "OPENDART_AUTH_FAILED"
    elif status in ("013", "014"):
        code = "DISCLOSURE_NOT_FOUND"
    elif status == "020":
        code = "OPENDART_RATE_LIMITED"
    else:
        code = "OPENDART_UNAVAILABLE"
    raise OpenDartError(code, provider_status=status if status.isascii() and status.isdigit() and len(status) == 3 else None)
