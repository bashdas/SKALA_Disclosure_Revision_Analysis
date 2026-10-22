"""Compatibility import; implementation lives in analysis.reporting.service."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.analysis.reporting.service")
sys.modules[__name__] = _module
