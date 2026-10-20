import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_backend: Literal["mock", "live"] = "mock"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8100
    log_level: str = "INFO"

    # live 전용. mock 모드에서는 키가 필요 없습니다.
    opendart_api_key: SecretStr | None = None
    dart_data_dir: Path = Path("data/dart")  # 프로젝트 기준 상대 경로(.gitignore의 data/). Docker는 /data/dart
    dart_max_concurrency: int = Field(2, ge=1, le=8)
    dart_timeout_seconds: float = Field(30.0, gt=0, le=120)
    dart_rate_limit_cooldown_seconds: float = Field(300.0, ge=0, le=86400)
    dart_corp_code_ttl_hours: float = Field(24.0, gt=0, le=24 * 30)
    dart_find_max_pages: int = Field(30, ge=1, le=200)
    # 기본은 공식 주소. 로컬 재생 서버(scripts/replay_e2e.py) 검증용으로만 127.0.0.1/localhost를 허용(DartClient가 검사)
    dart_base_url: str = "https://opendart.fss.or.kr"

    # 키 형식 검사는 여기서 하지 않습니다: pydantic 검증 오류는 input_value(원래 값)를 메시지에 담기 때문.
    # → providers.api_key_problem()에서 값 없이 사유만 보고합니다.


@lru_cache
def get_settings() -> Settings:
    # BUSINESS_MCP_ENV_FILE="" 이면 .env를 읽지 않음 (기본 pytest·replay 검증을 로컬 .env의 live 설정·키와 분리)
    return Settings(_env_file=os.environ.get("BUSINESS_MCP_ENV_FILE", ".env") or None)
