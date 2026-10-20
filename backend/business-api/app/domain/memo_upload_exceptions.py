class MemoUploadError(Exception):
    code = "INVALID_MEMO_UPLOAD"
    message = "Invalid memo upload"
    status_code = 400

    def __init__(self):
        super().__init__(self.message)


class EmptyMemo(MemoUploadError):
    code = "EMPTY_MEMO"
    message = "Memo content must not be empty"


class UnsupportedMemoFormat(MemoUploadError):
    code = "UNSUPPORTED_MEMO_FORMAT"
    message = "Only .txt files with text/plain content type are supported"
    status_code = 415


class MemoFileTooLarge(MemoUploadError):
    code = "MEMO_FILE_TOO_LARGE"
    message = "Memo file exceeds the configured size limit"
    status_code = 413


class InvalidMemoEncoding(MemoUploadError):
    code = "INVALID_MEMO_ENCODING"
    message = "Memo must use valid UTF-8 encoding"


class InvalidMemoText(MemoUploadError):
    code = "INVALID_MEMO_TEXT"
    message = "Memo text must not contain null characters"


class InvalidMemoFilename(MemoUploadError):
    code = "INVALID_MEMO_FILENAME"
    message = "Invalid memo filename"


class InvalidMemoTitle(MemoUploadError):
    code = "INVALID_MEMO_TITLE"
    message = "Memo title must contain 1 to 500 characters"
