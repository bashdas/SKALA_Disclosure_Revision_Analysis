"""Compatibility import; implementation lives in application.services.analysis_service."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.application.services.analysis_service")
sys.modules[__name__] = _module
