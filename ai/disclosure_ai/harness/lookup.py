"""Compatibility import; implementation lives in runtime.tool_executor."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.runtime.tool_executor")
sys.modules[__name__] = _module
