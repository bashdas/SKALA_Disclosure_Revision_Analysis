class ResourceNotFound(Exception):
    code = "RESOURCE_NOT_FOUND"
    message = "Resource not found"

    def __init__(self):
        super().__init__(self.message)


class FilingNotFound(ResourceNotFound):
    code = "FILING_NOT_FOUND"
    message = "Filing not found"


class FilingVersionNotFound(ResourceNotFound):
    code = "FILING_VERSION_NOT_FOUND"
    message = "Filing version not found"


class MemoNotFound(ResourceNotFound):
    code = "MEMO_NOT_FOUND"
    message = "Memo not found"


class MemoVersionNotFound(ResourceNotFound):
    code = "MEMO_VERSION_NOT_FOUND"
    message = "Memo version not found"
