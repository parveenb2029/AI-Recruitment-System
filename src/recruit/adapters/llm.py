"""LLM adapter implementations.

Closes the gap deferred from Phase 2.

Two implementations ship:

- `AnthropicLLM` — the real one. Uses **tool use** (native structured output),
  never "please return JSON". The model is handed the schema and physically
  cannot return prose, which is what deletes the repair-prompt loop the original
  specs were built around.
- `OllamaLLM` — a model on the operator's own machine. Free, private, no key,
  and the reason someone who has bought nothing can still run this for real.
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


class OllamaLLM:
    """LLMAdapter backed by a model running on the operator's own machine.

    This is the adapter that makes the project usable by someone who has not
    bought anything. Until now the only working model was Anthropic's, which
    needs a paid key — so a stranger who cloned the repo could run the sample
    queue with `FakeLLM` and nothing else. That is a demo, not a product.

    Three reasons it is Ollama rather than one of the free hosted tiers:

    1. **Nothing leaves the machine.** Every free hosted tier pays for itself
       with your data — Google's Gemini free tier, for one, trains on it. A
       resume is a named person's employment history, address and phone number.
       Sending that to a training set because the tier was free is not a
       trade-off an operator can make on a candidate's behalf.
    2. **No key, no card, no quota.** There is nothing to run out of and
       nothing to bill.
    3. **It has real structured output.** `format` takes a JSON schema and
       constrains decoding to it. That is the same guarantee Anthropic's forced
       tool use gives, so hard rule 2 holds: the model is never asked to
       "return JSON" and hoped at.

    The honest trade-off, stated here because the README will state it too: a
    model small enough to run on a laptop extracts less accurately than a
    frontier one. This is the difference between free and good, and it is the
    operator's call — not something to bury.

    Talks HTTP with `urllib` from the standard library rather than the `ollama`
    package. Two calls against a documented local API do not justify a
    dependency, and hard rule 9 says the pipeline installs with no extras.
    """

    def __init__(
        self,
        *,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: int = 300,
        max_retries: int = 2,
    ) -> None:
        self._model = model
        self._host = host.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        # A local model is slow rather than flaky: there is no rate limit and no
        # shared infrastructure to fail. Retries exist for a restarted daemon,
        # not for congestion, so two is plenty.
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._digest: str | None = None

    # -- transport ---------------------------------------------------------
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            f"{self._host}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            if exc.code == 404 and "model" in body:
                # The single most likely failure, and the message says the fix.
                raise LLMError(
                    f"Ollama does not have the model '{self._model}'.",
                    detail=f"Run:  ollama pull {self._model}",
                ) from exc
            raise LLMError(
                f"Ollama rejected the request ({exc.code}).", detail=body,
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Cannot reach Ollama at {self._host}.",
                detail=(
                    "Is it running? Start it with  ollama serve  ,or install it "
                    "from https://ollama.com. Nothing is sent over the internet "
                    "— this is a program on this machine."
                ),
            ) from exc

    @property
    def model_id(self) -> str:
        """Name plus content digest, for the audit log (BR-05).

        `llama3.1:8b` is a moving tag exactly like a cloud alias: pull it again
        in six months and it is different weights under the same name. An audit
        asking which model rejected a candidate needs the digest, so it is
        looked up once and carried alongside the name.
        """
        if self._digest:
            return f"{self._model}@{self._digest}"
        return self._model

    def _get(self, path: str) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(f"{self._host}{path}", method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _resolve_digest(self) -> None:
        """Best effort. A missing digest must never fail a real extraction.

        **From `/api/tags`, not `/api/show`.** This was wrong in the first
        version and only a real Ollama could say so: `/api/show` returns the
        modelfile, template, parameters and a `details` block of family and
        quantisation, and no digest anywhere. The digest is per-tag, so it lives
        with the tag listing. Written against the documentation, corrected by
        running it — which is the whole reason the register carried this adapter
        as unverified.
        """
        if self._digest is not None:
            return
        self._digest = ""
        try:
            listing = self._get("/api/tags")
        except Exception:      # noqa: BLE001 - provenance is never load-bearing
            return
        for entry in listing.get("models") or []:
            if self._model in (entry.get("name"), entry.get("model")):
                self._digest = str(entry.get("digest") or "")[:19]
                return

    # -- the call ----------------------------------------------------------
    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # Native constrained decoding against the schema — not a request in
            # prose for JSON. This is the line that keeps hard rule 2.
            "format": schema,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_predict": max_tokens or self.max_tokens,
            },
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                answer = self._post("/api/chat", payload)
            except LLMError as exc:
                if not exc.retryable or attempt == self.max_retries - 1:
                    raise
                last_error = exc
                time.sleep(2 ** attempt)
                continue

            content = ((answer.get("message") or {}).get("content") or "").strip()
            if not content:
                raise LLMRefusedSchema(
                    "Ollama returned an empty answer.",
                    detail=f"done_reason={answer.get('done_reason')}",
                )
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                # Constrained decoding should make this impossible. When it
                # happens it means the model or the server ignored `format`,
                # which is a different failure from a network one and must not
                # be blind-retried.
                raise LLMRefusedSchema(
                    "Ollama did not honour the schema and returned prose.",
                    detail=content[:300],
                ) from exc

            self._resolve_digest()
            return LLMResponse(
                content=parsed,
                model_id=self.model_id,
                input_tokens=int(answer.get("prompt_eval_count") or 0),
                output_tokens=int(answer.get("eval_count") or 0),
                stop_reason=answer.get("done_reason") or "stop",
            )

        raise LLMTimeout(
            f"Ollama call failed after {self.max_retries} attempts.",
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
    if provider == "ollama":
        return OllamaLLM(
            model=config.get("adapters.llm.ollama.model", "llama3.1:8b"),
            host=config.get("adapters.llm.ollama.host", "http://localhost:11434"),
            temperature=float(config.get("adapters.llm.temperature", 0.1)),
            max_tokens=int(config.get("adapters.llm.max_output_tokens", 4096)),
            timeout_seconds=int(config.get("adapters.llm.ollama.timeout_seconds", 300)),
        )
    raise NotImplementedError(
        f"LLM provider '{provider}' is configured but not implemented. "
        f"Available: anthropic (paid, most accurate), ollama (free, private, "
        f"runs on this machine)."
    )
