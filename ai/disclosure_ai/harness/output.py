"""Compatibility import; implementation lives in analysis.reporting.grounding_review."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.analysis.reporting.grounding_review")
sys.modules[__name__] = _module
