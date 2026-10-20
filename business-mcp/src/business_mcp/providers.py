"""데이터 공급원 교체 지점 — mock ↔ live는 이 파일에서만 결정합니다.

- get_dart_core(): dart_core.interface.DartCore 구현
    mock → business_mcp.mock.MockDartCore (가상 데이터)
    live → dart_core.live.LiveDartCore (OpenDART + DART_DATA_DIR 파일 캐시)
- get_memo_repository(): services.memos.MemoRepository 구현
    mock → MockMemoRepository (가상 메모)
    live → 아직 없음: NOT_IMPLEMENTED (가상 메모를 live 결과에 섞지 않음)
        TODO(live-memo): business_mcp/db/repository.py에 PostgreSQL 구현을 만들고 여기서 생성

live 실패 시 mock으로 조용히 대체하지 않습니다. 설정 오류는 Tool 오류 JSON으로 그대로 보입니다.
"""

import re

from business_mcp.config import get_settings
from business_mcp.errors import NotImplementedYet, UpstreamNotConfigured
from business_mcp.services.memos import MemoRepository
from dart_core.interface import DartCore

_dart: DartCore | None = None
_memo: MemoRepository | None = None


def api_key_problem() -> str | None:
    """키 상태 설명 (값은 절대 담지 않음). 문제가 없으면 None."""
    key = get_settings().opendart_api_key
    if key is None or not key.get_secret_value().strip():
        return "OPENDART_API_KEY가 설정되지 않았습니다."
    if not re.fullmatch(r"[0-9A-Za-z]{40}", key.get_secret_value().strip()):
        return "OPENDART_API_KEY 형식이 올바르지 않습니다(영문·숫자 40자)."
    return None


def get_dart_core() -> DartCore:
    global _dart
    if _dart is None:
        _dart = _build_dart()
    return _dart


def _build_dart() -> DartCore:
    s = get_settings()
    if s.data_backend == "mock":
        from business_mcp.mock import MockDartCore

        return MockDartCore.from_dir()
    if problem := api_key_problem():
        raise UpstreamNotConfigured(f"DATA_BACKEND=live인데 {problem} 프로젝트 .env를 확인해 주세요.",
                                    setting="OPENDART_API_KEY")
    from dart_core.client import DartClient
    from dart_core.corp_codes import CorpCodeIndex
    from dart_core.live import LiveDartCore
    from dart_core.store import FileStore

    client = DartClient(
        s.opendart_api_key.get_secret_value().strip(), base_url=s.dart_base_url, timeout=s.dart_timeout_seconds,
        max_concurrency=s.dart_max_concurrency, rate_limit_cooldown=s.dart_rate_limit_cooldown_seconds,
    )
    root = s.dart_data_dir.expanduser()
    return LiveDartCore(
        client, FileStore(root),
        CorpCodeIndex(client, root / "corp_codes.json", ttl_seconds=s.dart_corp_code_ttl_hours * 3600),
        find_max_pages=s.dart_find_max_pages,
    )


def get_memo_repository() -> MemoRepository:
    global _memo
    if _memo is None:
        if get_settings().data_backend == "mock":
            from business_mcp.mock import MockMemoRepository

            _memo = MockMemoRepository.from_dir()
        else:
            raise NotImplementedYet(
                "DATA_BACKEND=live에서는 메모 저장소(PostgreSQL)가 아직 연결되지 않았습니다.",
                tool="get_analysis_memo", depends_on="PostgreSQL analysis_memos, memo_versions",
            )
    return _memo


async def aclose() -> None:
    """서버 종료·테스트 정리용: live 클라이언트를 닫고 캐시된 공급원을 비웁니다."""
    global _dart, _memo
    closer = getattr(_dart, "aclose", None)
    _dart, _memo = None, None
    if closer:
        await closer()


def reset() -> None:
    """설정을 바꾼 테스트에서 공급원과 설정 캐시를 비웁니다 (live 클라이언트는 aclose()로 닫을 것)."""
    global _dart, _memo
    _dart, _memo = None, None
    get_settings.cache_clear()
