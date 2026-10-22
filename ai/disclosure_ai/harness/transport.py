"""Compatibility import; implementation lives in runtime.transport."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.runtime.transport")
sys.modules[__name__] = _module
