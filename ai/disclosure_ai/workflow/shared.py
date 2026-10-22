"""Legacy import path. New graph code uses workflow.nodes and workflow.routing."""

import sys
from importlib import import_module

from disclosure_ai.workflow import routing as _routing

_module = import_module("disclosure_ai.analysis.evidence.service")
_module.resume = _routing.resume
_module.status = _routing.status
sys.modules[__name__] = _module
