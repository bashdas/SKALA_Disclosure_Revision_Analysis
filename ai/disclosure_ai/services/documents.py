"""Compatibility import; implementation lives in infrastructure.documents.parser."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.infrastructure.documents.parser")
sys.modules[__name__] = _module
