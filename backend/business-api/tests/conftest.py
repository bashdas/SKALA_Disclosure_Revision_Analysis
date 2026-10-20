from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.database import get_engine, get_session_factory


@pytest.fixture(autouse=True)
def isolated_database_settings(monkeypatch):
    # Tests must not use a developer's real DATABASE_URL or .env.
    monkeypatch.chdir(Path(__file__).parent)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()
