"""Deliberately biased fake models, used to test the harness itself.

A bias harness that reports "no bias found" is worthless unless you have shown
it *can* find bias. These fakes inject a known, measurable preference so the
test suite can assert the harness catches it.

They exist for testing only and are never wired into the pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..adapters.base import LLMResponse


class BiasedFakeLLM:
    """Scores a component lower when a disfavoured signal appears in the input.

    Crude on purpose: the point is a known ground truth, not realism.
    """

    def __init__(
        self,
        payload: dict[str, Any] | Path,
        *,
        penalise: dict[str, float],
        component: str = "domain_match",
        model_id: str = "biased-fake-v0",
    ) -> None:
        if isinstance(payload, Path):
            payload = json.loads(payload.read_text(encoding="utf-8"))
        self._payload = payload
        self._penalise = penalise
        self._component = component
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def complete_structured(
        self, *, system: str, user: str, schema: dict[str, Any],
        temperature: float | None = None, max_tokens: int | None = None,
    ) -> LLMResponse:
        content = json.loads(json.dumps(self._payload))
        penalty = 0.0
        haystack = user.lower()
        for token, amount in self._penalise.items():
            if token.lower() in haystack:
                penalty = max(penalty, amount)

        if penalty:
            for component in content.get("components", []):
                if component.get("component_id") == self._component:
                    component["raw_score"] = round(
                        max(0.0, float(component["raw_score"]) - penalty), 4)

        return LLMResponse(content=content, model_id=self._model_id,
                           stop_reason="tool_use")
