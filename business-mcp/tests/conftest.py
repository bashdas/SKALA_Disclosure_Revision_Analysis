"""기본 pytest는 프로젝트 .env(live 설정·실제 키)를 읽지 않습니다. 실제 OpenDART 테스트만 .env를 다시 켭니다."""

import os

os.environ["BUSINESS_MCP_ENV_FILE"] = ""
