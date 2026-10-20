from dataclasses import dataclass
from email.message import Message
from hashlib import sha256
from pathlib import PurePosixPath
from typing import BinaryIO, Protocol

from app.domain.memo_upload_exceptions import (
    EmptyMemo, InvalidMemoEncoding, InvalidMemoFilename, InvalidMemoText,
    MemoFileTooLarge, UnsupportedMemoFormat,
)


@dataclass(frozen=True)
class ExtractedMemo:
    content: str
    original_filename: str
    content_type: str
    size_bytes: int
    content_hash: str


class MemoTextExtractor(Protocol):
    def extract(self, stream: BinaryIO, *, filename: str | None, content_type: str | None, max_bytes: int) -> ExtractedMemo: ...


class PlainTextMemoExtractor:
    def extract(self, stream: BinaryIO, *, filename: str | None, content_type: str | None, max_bytes: int) -> ExtractedMemo:
        # Metadata only: never use the client name as a filesystem path or company identity.
        name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not name or len(name) > 255 or any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise InvalidMemoFilename()
        if PurePosixPath(name).suffix.lower() != ".txt" or not content_type or len(content_type) > 255:
            raise UnsupportedMemoFormat()
        if content_type.split(";", 1)[0].strip().lower() != "text/plain":
            raise UnsupportedMemoFormat()
        header = Message()
        header["content-type"] = content_type
        charset = header.get_content_charset()
        if charset is not None and charset.lower() not in ("utf-8", "utf8", "utf-8-sig"):
            raise InvalidMemoEncoding()

        data = bytearray()
        digest = sha256()
        # Read at most limit+1 bytes; do not trust the Content-Length or file.size header.
        while True:
            chunk = stream.read(min(65536, max_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise MemoFileTooLarge()
            digest.update(chunk)
        try:
            content = data.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            raise InvalidMemoEncoding() from None
        if not content.strip():
            raise EmptyMemo()
        if "\x00" in content:
            raise InvalidMemoText()
        return ExtractedMemo(content, name, "text/plain", len(data), digest.hexdigest())
