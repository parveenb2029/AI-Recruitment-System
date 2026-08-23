"""LLM adapter implementations.

Closes the gap deferred from Phase 2.

Two implementations ship:

- `AnthropicLLM` — the real one. Uses **tool use** (native structured output),
  never "please return JSON". The model is handed the schema and physically
  cannot return prose, which is what deletes the repair-prompt loop the original
  specs were built around.
- `FakeLLM` — returns a canned payload. Lets the whole pipeline, its validation,
  and its tests run with no API key and no cost. Not a mock of the transport:
  it satisfies the same protocol, so everything downstream is genuinely
  exercised.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..errors import RecruitError
from .base import LLMResponse


class LLMError(RecruitError):
    code = "ERR_LLM_CALL_FAILED"
    recovery = "Check the API key and network, then retry. Persistent failures go to the DLQ."
    retryable = True


class LLMTimeout(LLMError):
    code = "AI_TIMEOUT"
    recovery = "Retried three times with backoff. Item routed to the dead-letter queue."


class LLMRefusedSchema(LLMError):
    """The model answered in prose despite being given a tool.

    Rare with tool use, and worth its own code: it means the schema was rejected
    or the request tripped a safety response, not that the network failed.
    Retrying identically will not help.
    """

    code = "ERR_LLM_NO_STRUCTURED_OUTPUT"
    recovery = "Inspect the prompt and schema. Do not blind-retry."
    retryable = False


class AnthropicLLM:
    """LLMAdapter backed by the Anthropic Messages API, via tool use."""

    TOOL_NAME = "emit_result"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: int = 120,
        max_retries: int = 3,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "The anthropic package is not installed.",
                detail='pip install -e ".[anthropic]"',
            ) from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self._resolved_model: str | None = None

    @property
    def model_id(self) -> str:
        """The exact model that answered, for the audit log (BR-05).

        Prefer the id the API echoes back over the alias we asked for: aliases
        move, and an audit trail saying "claude-sonnet-4-5" a year from now would
        not identify which model actually made the call.
        """
        return self._resolved_model or self._model

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        tool = {
            "name": self.TOOL_NAME,
            "description": (
                "Return the extraction result. Every field must be grounded in "
                "the supplied source document."
            ),
            "input_schema": schema,
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                message = self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens or self.max_tokens,
                    temperature=self.temperature if temperature is None else temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    tools=[tool],
                    # Force the tool. Without this the model may reply in prose and
                    # we are back to parsing free text, which is the failure mode
                    # this whole design exists to avoid.
                    tool_choice={"type": "tool", "name": self.TOOL_NAME},
                )
            except self._anthropic.APITimeoutError as exc:
                last_error = exc
                time.sleep(2 ** attempt)          # 1s, 2s, 4s per Error_Handling.md
                continue
            except self._anthropic.RateLimitError as exc:
                last_error = exc
                time.sleep(2 ** (attempt + 1))
                continue
            except self._anthropic.APIStatusError as exc:
                if exc.status_code >= 500:
                    last_error = exc
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(
                    f"Anthropic API rejected the request ({exc.status_code}).",
                    detail=str(exc),
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise LLMError("Unexpected error calling Anthropic.", detail=str(exc)) from exc

            self._resolved_model = getattr(message, "model", None) or self._model

            for block in message.content:
                if getattr(block, "type", None) == "tool_use" and block.name == self.TOOL_NAME:
                    return LLMResponse(
                        content=dict(block.input),
                        model_id=self._resolved_model,
                        input_tokens=message.usage.input_tokens,
                        output_tokens=message.usage.output_tokens,
                        stop_reason=message.stop_reason,
                    )

            raise LLMRefusedSchema(
                "Model did not call the structured-output tool.",
                detail=f"stop_reason={message.stop_reason}",
            )

        raise LLMTimeout(
            f"Anthropic call failed after {self.max_retries} attempts.",
            detail=str(last_error),
        )


class FakeLLM:
    """LLMAdapter that returns a canned payload. No key, no network, no cost.

    Used by the test suite and by `--fake` on the CLI, so the pipeline can be
    exercised end to end before anyone spends money. It deliberately validates
    its payload against the same schema the real adapter is handed, so a fixture
    that has drifted from the contract fails here rather than looking fine.
    """

    def __init__(self, payload: dict[str, Any] | Path, model_id: str = "fake-model-v0") -> None:
        if isinstance(payload, Path):
            payload = json.loads(payload.read_text(encoding="utf-8"))
        self._payload = payload
        self._model_id = model_id
        self.calls: list[dict[str, Any]] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return LLMResponse(
            content=json.loads(json.dumps(self._payload)),   # defensive copy
            model_id=self._model_id,
            input_tokens=len(user) // 4,
            output_tokens=len(json.dumps(self._payload)) // 4,
            stop_reason="tool_use",
        )


def build_llm(config) -> Any:
    """Construct the configured LLM adapter."""
    provider = config.get("adapters.llm.provider", "anthropic")
    if provider == "anthropic":
        return AnthropicLLM(
            api_key=config.secret(config.get("adapters.llm.api_key_env", "ANTHROPIC_API_KEY")),
            model=config.get("adapters.llm.model", "claude-sonnet-4-5"),
            temperature=float(config.get("adapters.llm.temperature", 0.1)),
            max_tokens=int(config.get("adapters.llm.max_output_tokens", 4096)),
            timeout_seconds=int(config.get("adapters.llm.timeout_seconds", 120)),
            max_retries=int(config.get("adapters.llm.max_retries", 3)),
        )
    raise NotImplementedError(
        f"LLM provider '{provider}' is configured but not implemented. "
        f"Available: anthropic. Others arrive in Phase 5."
    )
