import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSettings:
    name: str

    @classmethod
    def from_environment(cls):
        return cls(name=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"))
