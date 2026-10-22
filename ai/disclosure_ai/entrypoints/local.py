"""Compatibility import; implementation lives in presentation.cli.local."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.presentation.cli.local")
if __name__ == "__main__":
    _module.main()
else:
    sys.modules[__name__] = _module
