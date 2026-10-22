"""Compatibility import; implementation lives in infrastructure.persistence.sqlite_run_repository."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.infrastructure.persistence.sqlite_run_repository")
sys.modules[__name__] = _module
