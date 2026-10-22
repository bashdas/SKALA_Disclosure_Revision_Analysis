from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ExecutionDependencies:
    repository: Callable
    harness: Callable
    tools: Callable
    checkpointer: Callable
    workflow: Callable
    internal_request: Callable
    fixed_request: Callable
