"""Turning an email address into something that reads like a person.

This lives here, in the core package, rather than in `web/humanize.py` where it
started — because `recruit.web` imports FastAPI, and `bootstrap` needs the same
rule. Hard rule 9 says `pip install -e .` alone must run the pipeline: reaching
into the web package for one string function would have made creating the first
administrator depend on the console being installed.

One rule, one place. When the first-run banner, the people table and the
activity log derive a name from the same address, they must agree — a console
that calls someone "Priya.Nair" on one screen and "Priya Nair" on the next looks
like it is talking about two people.
"""

from __future__ import annotations

__all__ = ["display_name_for"]


def display_name_for(address: str | None) -> str:
    """`priya.nair@example.com` -> `Priya Nair`.

    Returns a non-address unchanged: it is already whatever the operator typed,
    and reformatting someone's actual name is worse than leaving it alone.
    """
    if not address:
        return "Someone"
    if "@" not in address:
        return address
    local = address.split("@")[0]
    return local.replace(".", " ").replace("_", " ").title()
