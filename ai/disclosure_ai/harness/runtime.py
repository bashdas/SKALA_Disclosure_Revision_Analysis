"""Compatibility import; implementation lives in runtime.harness."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.runtime.harness")
sys.modules[__name__] = _module
