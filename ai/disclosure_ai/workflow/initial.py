"""Compatibility import; implementation lives in analysis.inputs.service."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.analysis.inputs.service")
sys.modules[__name__] = _module
