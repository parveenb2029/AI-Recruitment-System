"""Running the real pipeline without buying anything.

Before this adapter there was exactly one working model — Anthropic's, behind a
paid key. A stranger who cloned the repository could run the sample queue with
`FakeLLM` and go no further, which makes the project a demo rather than
something anyone can use. `OllamaLLM` closes that: a model on the operator's own
machine, no key, no card, no quota, and nothing about a candidate leaving the
building.

These tests run against a real HTTP server rather than a mocked client object.
The whole adapter *is* transport — a request body, a response shape, and the
failures in between — so a test that patched the request away would be checking
the parts that cannot break.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from recruit.adapters.base import LLMAdapter
from recruit.adapters.llm import (
    LLMError,
    LLMRefusedSchema,
    LLMTimeout,
    OllamaLLM,
    build_llm,
)

SCHEMA = {
    "type": "object",
    "properties": {"full_name": {"type": "string"}, "years": {"type": "number"}},
    "required": ["full_name"],
    "additionalProperties": False,
}


class FakeOllama(BaseHTTPRequestHandler):
    """Just enough of Ollama to be wrong in the ways Ollama is wrong."""

    # Set per test by the fixture.
    reply: dict = {}
    status: int = 200
    received: list = []

    def log_message(self, *args):     # noqa: A002 - silence the access log
        pass

    def _send(self, payload, code=200):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):                 # noqa: N802 - BaseHTTPRequestHandler's name
        FakeOllama.received.append({"path": self.path, "body": None})
        if self.path == "/api/tags":
            # The shape real Ollama returns. `/api/show` carries no digest at
            # all — the first version of the adapter asked it anyway, and only
            # a real daemon could say so.
            self._send({"models": [{
                "name": "llama3.1:8b",
                "model": "llama3.1:8b",
                "digest": "sha256:abc123def456789aaaa",
                "details": {"parameter_size": "8.0B", "quantization_level": "Q4_K_M"},
            }]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):                # noqa: N802 - BaseHTTPRequestHandler's name
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        FakeOllama.received.append({"path": self.path, "body": body})
        self._send(FakeOllama.reply, FakeOllama.status)


@pytest.fixture
def ollama():
    """A local Ollama that is not Ollama, on a port the OS picks."""
    FakeOllama.received = []
    FakeOllama.status = 200
    FakeOllama.reply = {
        "model": "llama3.1:8b",
        "message": {"content": json.dumps({"full_name": "Rahul Sharma", "years": 4.5})},
        "prompt_eval_count": 812,
        "eval_count": 96,
        "done_reason": "stop",
    }
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def adapter(host, **kw):
    return OllamaLLM(model="llama3.1:8b", host=host, max_retries=2, **kw)


# -- the contract -------------------------------------------------------------
def test_it_satisfies_the_same_protocol_as_the_paid_adapter():
    """Everything downstream must not know or care which model answered."""
    assert isinstance(adapter("http://x"), LLMAdapter)


def test_the_schema_is_sent_as_a_constraint_not_as_a_request(ollama):
    """Hard rule 2, checked rather than trusted.

    The schema has to arrive in `format`, where Ollama constrains decoding to
    it. Putting it in the prompt and asking nicely is the exact failure this
    project is built to avoid, and it would look identical from the outside
    until the day a model ignored it.
    """
    adapter(ollama).complete_structured(system="S", user="U", schema=SCHEMA)

    sent = FakeOllama.received[0]["body"]
    assert sent["format"] == SCHEMA
    assert sent["stream"] is False
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert sent["messages"][0]["content"] == "S"


def test_a_successful_call_returns_parsed_content_and_token_counts(ollama):
    result = adapter(ollama).complete_structured(system="S", user="U", schema=SCHEMA)

    assert result.content == {"full_name": "Rahul Sharma", "years": 4.5}
    assert (result.input_tokens, result.output_tokens) == (812, 96)
    assert result.stop_reason == "stop"


def test_the_model_id_carries_the_digest(ollama):
    """BR-05: an audit has to identify the model, and a tag is not an identity.

    `llama3.1:8b` is a moving pointer exactly like a cloud alias — pull it again
    next year and the weights differ under the same name. "Which model rejected
    this candidate" is only answerable with the digest.
    """
    a = adapter(ollama)
    a.complete_structured(system="S", user="U", schema=SCHEMA)

    assert a.model_id.startswith("llama3.1:8b@sha256:")
    # From the tag listing. `/api/show` has no digest in it, which is exactly
    # what the first version of this adapter got wrong.
    assert any(r["path"] == "/api/tags" for r in FakeOllama.received)
    assert not any(r["path"] == "/api/show" for r in FakeOllama.received)


def test_a_digest_lookup_that_fails_does_not_fail_the_extraction(ollama):
    """Provenance is worth having, not worth losing a run over."""
    a = adapter(ollama)
    a._digest = ""                      # as if the tag listing had errored
    result = a.complete_structured(system="S", user="U", schema=SCHEMA)

    assert result.content["full_name"] == "Rahul Sharma"
    assert a.model_id == "llama3.1:8b"


def test_a_model_missing_from_the_tag_listing_leaves_the_name_alone(ollama):
    """An unknown tag must not invent provenance or crash the run."""
    a = OllamaLLM(model="something-else:7b", host=ollama, max_retries=1)
    a.complete_structured(system="S", user="U", schema=SCHEMA)
    assert a.model_id == "something-else:7b"


# -- the failures a first-time user will actually hit -------------------------
def test_ollama_not_running_says_so_in_plain_words():
    """The single most likely failure on a first run.

    A raw `URLError: [Errno 111] Connection refused` tells someone who just
    wanted to read some resumes nothing at all.
    """
    a = adapter("http://127.0.0.1:1")   # nothing listens on port 1

    with pytest.raises(LLMError) as raised:
        a.complete_structured(system="S", user="U", schema=SCHEMA)

    message = f"{raised.value} {raised.value.detail}"
    assert "Cannot reach Ollama" in message
    assert "ollama serve" in message
    # It must also kill the reasonable fear that a local model is phoning home.
    assert "Nothing is sent over the internet" in message


def test_a_missing_model_tells_you_the_command_that_fixes_it(ollama):
    """Second most likely: Ollama installed, model never pulled."""
    FakeOllama.status = 404
    FakeOllama.reply = {"error": 'model "llama3.1:8b" not found'}

    with pytest.raises(LLMError) as raised:
        adapter(ollama).complete_structured(system="S", user="U", schema=SCHEMA)

    assert "ollama pull llama3.1:8b" in str(raised.value.detail)


def test_prose_instead_of_structure_is_its_own_failure_and_is_not_retried(ollama):
    """Constrained decoding makes this near-impossible, which is why it matters.

    If it happens, `format` was ignored — by an old server or a model that
    cannot honour it. That is not a blip, and retrying identically burns minutes
    of somebody's laptop to arrive at the same place.
    """
    FakeOllama.reply = {
        "message": {"content": "Sure! Here is the candidate you asked about:"},
        "done_reason": "stop",
    }

    with pytest.raises(LLMRefusedSchema) as raised:
        adapter(ollama).complete_structured(system="S", user="U", schema=SCHEMA)

    assert raised.value.retryable is False
    assert len([r for r in FakeOllama.received if r["path"] == "/api/chat"]) == 1


def test_an_empty_answer_is_not_mistaken_for_an_empty_result(ollama):
    FakeOllama.reply = {"message": {"content": "   "}, "done_reason": "length"}

    with pytest.raises(LLMRefusedSchema) as raised:
        adapter(ollama).complete_structured(system="S", user="U", schema=SCHEMA)
    assert "length" in str(raised.value.detail)


# -- configuration ------------------------------------------------------------
class Config:
    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


def test_choosing_ollama_in_config_builds_it():
    built = build_llm(Config(**{
        "adapters.llm.provider": "ollama",
        "adapters.llm.ollama.model": "qwen2.5:7b",
    }))
    assert isinstance(built, OllamaLLM)
    assert built.model_id == "qwen2.5:7b"


def test_an_unknown_provider_names_both_real_options():
    """The error is where someone finds out a free option exists."""
    with pytest.raises(NotImplementedError) as raised:
        build_llm(Config(**{"adapters.llm.provider": "openai"}))

    message = str(raised.value)
    assert "anthropic" in message and "ollama" in message
    assert "free" in message


# -- slow is not broken -------------------------------------------------------
def test_a_slow_model_produces_advice_rather_than_a_traceback():
    """A CPU model that runs long is the normal case, not a fault.

    `socket.timeout` is `TimeoutError`, which is NOT a subclass of `URLError` —
    so it walked past the connection handler and reached the operator as
    "Unexpected failure: timed out". True, useless, and indistinguishable from
    a crash. Found by the operator's own run, not by this file.
    """
    import socket
    import threading
    import time

    # A server that accepts the connection and then says nothing at all. The
    # accepted socket is kept alive deliberately: letting it be collected closes
    # the connection, which is a reset rather than a timeout — a different bug.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    held = []

    def accept_and_stall():
        conn, _ = listener.accept()
        held.append(conn)
        time.sleep(10)

    threading.Thread(target=accept_and_stall, daemon=True).start()

    a = OllamaLLM(model="llama3.1:8b", host=f"http://127.0.0.1:{port}",
                  timeout_seconds=1, max_retries=1)
    try:
        with pytest.raises(LLMTimeout) as raised:
            a.complete_structured(system="S", user="U", schema=SCHEMA)
    finally:
        listener.close()

    detail = str(raised.value.detail)
    assert "timeout_seconds" in detail
    assert "smaller model" in detail


# -- what the model is actually shown -----------------------------------------
def test_a_regex_never_reaches_the_grammar():
    """A pattern in a schema becomes a state machine the model decodes inside.

    `^(/[^/]*)+$` — a repeated group around a repeated character class — did not
    finish in five minutes on a 3B model. The same schema without it answers
    normally. The pointer's format is taught by the worked example and enforced
    afterwards by validation, where being wrong costs a clear finding instead of
    an unexplained stall.
    """
    from recruit.prompts import without_regex_constraints

    schema = {
        "type": "object",
        "properties": {
            "field_confidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pointer": {"type": "string", "pattern": "^(/[^/]*)+$"},
                        "confidence": {"type": "number", "minimum": 0},
                    },
                    "required": ["pointer", "confidence"],
                },
            },
            "when": {"type": "string", "format": "date"},
        },
    }
    stripped = without_regex_constraints(schema)

    assert "pattern" not in json.dumps(stripped)
    # The SHAPE survives untouched - that is the part worth enforcing.
    item = stripped["properties"]["field_confidence"]["items"]
    assert item["required"] == ["pointer", "confidence"]
    assert item["properties"]["pointer"]["type"] == "string"
    assert item["properties"]["confidence"]["minimum"] == 0
    # `format` is a cheap hint, not a compiled expression. It stays.
    assert stripped["properties"]["when"]["format"] == "date"
    # And the original is not mutated - it is still what validation uses.
    assert schema["properties"]["field_confidence"]["items"]["properties"]["pointer"]["pattern"]
