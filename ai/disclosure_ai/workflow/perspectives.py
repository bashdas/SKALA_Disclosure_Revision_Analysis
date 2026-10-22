"""Legacy import path. New graph code uses workflow.nodes and workflow.routing."""

import sys
from importlib import import_module

from disclosure_ai.workflow import routing as _routing

_module = import_module("disclosure_ai.analysis.perspectives.service")
_module.selected = _routing.selected
sys.modules[__name__] = _module
