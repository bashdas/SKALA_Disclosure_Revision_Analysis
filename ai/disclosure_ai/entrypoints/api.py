"""Compatibility import; implementation lives in presentation.http.controllers.analysis_controller."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.presentation.http.controllers.analysis_controller")
sys.modules[__name__] = _module
