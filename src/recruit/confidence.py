"""Reading per-field confidence, whichever shape it was stored in.

`results.field_confidence` changed from an object keyed by JSON Pointer to a
list of `{pointer, confidence}` pairs. The reason is in the schema's own
description: constrained decoding builds a grammar from the schema, and a
grammar can constrain a value but not an arbitrary object key. Keyed by
pointer, the `propertyNames` pattern was advisory — the first real model run
returned plain field names and failed validation 31 times on an extraction
that was otherwise correct.

**Both shapes are read, forever.** The audit log is append-only and extraction
envelopes are kept as evidence; a run recorded last month is a record of what
happened, not a file to be migrated. A console that could not open it would
make the older half of the archive unreadable — which is the opposite of what
an evidence trail is for. So this module accepts either and every caller goes
through it, rather than five call sites each growing their own `isinstance`
check and drifting apart.

New envelopes are written in the list shape. Nothing writes the old one.
"""

from __future__ import annotations

from typing import Any

__all__ = ["as_pairs", "read"]


def read(results: Any) -> dict[str, float]:
    """Return {pointer: confidence} from either shape.

    Bad entries are skipped rather than raising. This is model output on the
    way to a reviewer, and one malformed row must not take down the screen
    that exists to catch malformed rows.
    """
    if not isinstance(results, dict):
        return {}
    raw = results.get("field_confidence")

    if isinstance(raw, dict):          # the original shape, still in the archive
        return {str(k): float(v) for k, v in raw.items()
                if isinstance(v, (int, float))}

    if isinstance(raw, list):          # the shape everything writes now
        out: dict[str, float] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            pointer = entry.get("pointer")
            value = entry.get("confidence")
            if isinstance(pointer, str) and isinstance(value, (int, float)):
                out[pointer] = float(value)
        return out

    return {}


def as_pairs(mapping: dict[str, float]) -> list[dict[str, Any]]:
    """The inverse, for building an envelope. Sorted, so runs diff cleanly."""
    return [{"pointer": p, "confidence": c} for p, c in sorted(mapping.items())]
