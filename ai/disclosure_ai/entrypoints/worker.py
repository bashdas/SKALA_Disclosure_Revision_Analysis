"""Compatibility import; implementation lives in presentation.queue.consumer."""

import sys
from importlib import import_module

_module = import_module("disclosure_ai.presentation.queue.consumer")
if __name__ == "__main__":
    _module.main()
else:
    sys.modules[__name__] = _module
