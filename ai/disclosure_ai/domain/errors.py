class BusinessError(RuntimeError):
    def __init__(self, code: str, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


class RunCancelled(BusinessError):
    pass


class LimitReached(RuntimeError):
    pass
