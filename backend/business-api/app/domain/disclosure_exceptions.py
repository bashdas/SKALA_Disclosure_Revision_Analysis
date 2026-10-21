class DisclosureError(Exception):
    def __init__(self, code="DISCLOSURE_UNAVAILABLE", message="공시를 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.", status_code=502):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)
