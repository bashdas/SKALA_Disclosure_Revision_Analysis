"""파일 캐시 (PostgreSQL 이전의 임시 저장소).

DATABASE 없이 live 조회를 하려고 쓰는 로컬 캐시이며, 05 문서 §4의 filings·filing_documents 저장을 대신하지 않습니다.
배치(DART_DATA_DIR):
  meta/{rcept_no}.json                      FilingMeta (list.json에서 본 최신 행)   → 후속: filings 테이블
  zips/{rcept_no}.zip (+ .sha256)           원문 ZIP                               → 후속: raw_zip_path + zip_sha256
  parsed/{rcept_no}.{parser_version}.json   ParsedDocument                         → 후속: filing_documents.parsed
  corp_codes.json                           고유번호 목록 + fetched_at              → 후속: companies 테이블
모든 쓰기는 같은 디렉터리의 임시 파일에 쓴 뒤 os.replace로 바꿔 끼웁니다(원자적).
"""

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path

from pydantic import ValidationError

from dart_core.models import FilingMeta, ParsedDocument

logger = logging.getLogger(__name__)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class FileStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ── 메타데이터 ──
    def _meta_path(self, rcept_no: str) -> Path:
        return self.root / "meta" / f"{rcept_no}.json"

    def get_meta(self, rcept_no: str) -> FilingMeta | None:
        p = self._meta_path(rcept_no)
        try:
            return FilingMeta.model_validate_json(p.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError, ValueError):
            logger.warning("메타 캐시 손상, 무시: %s", p.name)
            p.unlink(missing_ok=True)
            return None

    def put_meta(self, meta: FilingMeta) -> None:
        atomic_write(self._meta_path(meta.rcept_no), meta.model_dump_json().encode("utf-8"))

    # ── 원문 ZIP ──
    def _zip_path(self, rcept_no: str) -> Path:
        return self.root / "zips" / f"{rcept_no}.zip"

    def get_zip(self, rcept_no: str) -> tuple[bytes, str] | None:
        """(바이트, sha256). sha256 파일과 맞지 않으면 손상으로 보고 지운 뒤 None."""
        p = self._zip_path(rcept_no)
        sha_p = p.with_suffix(".zip.sha256")
        try:
            data, expected = p.read_bytes(), sha_p.read_text().strip()
        except FileNotFoundError:
            return None
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            logger.warning("원문 ZIP 캐시 해시 불일치, 다시 받습니다: %s", p.name)
            self.drop_zip(rcept_no)
            return None
        return data, digest

    def put_zip(self, rcept_no: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        p = self._zip_path(rcept_no)
        atomic_write(p, data)
        atomic_write(p.with_suffix(".zip.sha256"), digest.encode())
        return digest

    def drop_zip(self, rcept_no: str) -> None:
        p = self._zip_path(rcept_no)
        p.unlink(missing_ok=True)
        p.with_suffix(".zip.sha256").unlink(missing_ok=True)

    # ── 파싱 결과 ──
    def _parsed_path(self, rcept_no: str, parser_version: str) -> Path:
        return self.root / "parsed" / f"{rcept_no}.{parser_version}.json"

    def get_parsed(self, rcept_no: str, parser_version: str, zip_sha256: str) -> ParsedDocument | None:
        p = self._parsed_path(rcept_no, parser_version)
        try:
            payload = json.loads(p.read_bytes())
            if payload.get("zip_sha256") != zip_sha256:
                return None  # 원문이 바뀜 → 다시 파싱
            return ParsedDocument.model_validate(payload["document"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, ValidationError):
            logger.warning("파싱 캐시 손상, 다시 파싱합니다: %s", p.name)
            p.unlink(missing_ok=True)
            return None

    def put_parsed(self, doc: ParsedDocument, zip_sha256: str) -> None:
        payload = {"zip_sha256": zip_sha256, "parser_version": doc.parser_version, "document": doc.model_dump(mode="json")}
        atomic_write(self._parsed_path(doc.rcept_no, doc.parser_version),
                     json.dumps(payload, ensure_ascii=False).encode("utf-8"))
