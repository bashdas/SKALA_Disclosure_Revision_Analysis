from disclosure_ai.analysis.perspectives.definitions.external_risk import DEFINITION as RISK
from disclosure_ai.analysis.perspectives.definitions.finance import DEFINITION as FINANCE
from disclosure_ai.analysis.perspectives.definitions.industry_contract import DEFINITION as INDUSTRY
from disclosure_ai.domain.models.perspective import PerspectiveDefinition


class PerspectiveRegistry:
    def __init__(self, definitions=()):
        self._definitions = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: PerspectiveDefinition):
        if definition.key in self._definitions:
            raise ValueError("DUPLICATE_PERSPECTIVE")
        self._definitions[definition.key] = definition

    def get(self, key):
        return self._definitions[key]

    def titles(self):
        return {key: definition.title for key, definition in self._definitions.items()}


DEFAULT_REGISTRY = PerspectiveRegistry((INDUSTRY, FINANCE, RISK))
