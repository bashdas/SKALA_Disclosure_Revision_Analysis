"""Compatibility import; implementation lives in infrastructure.mcp.client."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.infrastructure.mcp.client")
sys.modules[__name__] = _module
