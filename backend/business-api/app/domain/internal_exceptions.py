from app.domain.analysis_exceptions import AnalysisError


class InternalAPIError(AnalysisError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__()
