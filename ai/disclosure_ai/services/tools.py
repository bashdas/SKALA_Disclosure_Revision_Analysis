"""Compatibility import; implementation lives in infrastructure.mcp.tool_gateway."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.infrastructure.mcp.tool_gateway")
sys.modules[__name__] = _module
