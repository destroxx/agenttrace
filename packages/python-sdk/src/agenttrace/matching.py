"""Deciding which recorded tool call a new call corresponds to.

Pure functions: no I/O, no tracer, no session. Replay uses them to pick the
recorded answer for a live call, and comparison will use the same functions
to line a replay up against its recording, so the two can never disagree about
what "the same call" means.

The ladder, strictest first:

1. **exact** -- same tool name, and the arguments serialise to identical
   canonical JSON (keys sorted, no whitespace).
2. **normalized** -- same tool name, and the arguments are equal after
   `normalize`, which forgives differences that cannot change what a tool
   does: surrounding whitespace, `2.0` for `2`, and an explicit `None` for an
   omitted keyword.
3. An LLM-judged fallback is planned and deliberately not here: it is slow,
   non-deterministic, and a matcher that guesses would let a real regression
   pass as a match.

Tier 1 is tried across every candidate before tier 2 is tried at all, so a
loose match never steals the call an exact match was waiting for.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Any

from agenttrace.models import snapshot_object

TIER_EXACT = "exact"
TIER_NORMALIZED = "normalized"
TIER_UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """A tool call reduced to what matching compares: its name and two keys."""

    tool_name: str
    exact: str
    normalized: str


def canonical(value: Any) -> str:
    """One string per JSON value, independent of key order and spacing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def normalize(value: Any) -> Any:
    """Erase differences that cannot matter to a tool, and nothing else.

    Recursive, and conservative on purpose -- every rule here makes two calls
    the matcher would otherwise tell apart indistinguishable, so each one has
    to be safe for any tool:

    - **Strings are stripped** of leading and trailing whitespace. A model
      emitting `" A-1"` or `"A-1\\n"` means `"A-1"`; inner whitespace is left
      alone because it can be content (`"New  York"` vs a search phrase).
    - **Integer-valued floats become ints.** `2.0` and `2` are the same
      number, but serialise differently; LLMs and JSON round trips switch
      between them freely. Non-integral floats are untouched.
    - **Dict keys whose value is None are dropped.** Passing `limit=None` and
      omitting `limit` are the same call for almost every tool, and a default
      argument recorded via `apply_defaults` shows up as an explicit None.
    - **List order is preserved.** `["a", "b"]` and `["b", "a"]` can be
      different requests (a ranking, a path, positional values).
    - **No case folding.** Identifiers like `"A-1"` and `"a-1"` may name
      different things, and a matcher that merged them would hand one
      customer's order to another's lookup.
    - Dict keys themselves are not normalised: a key is a parameter name, and
      a renamed parameter is a real change.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def fingerprint(tool_name: str, arguments: dict[str, Any] | None) -> Fingerprint:
    """Reduce a call to its matching keys.

    The arguments go through the same `snapshot_object` recording applies, so
    a live call and a recorded one are compared in the same form -- a tuple
    and a list, or a datetime and its string, would otherwise never match
    what was recorded.
    """
    arguments = snapshot_object(arguments) or {}
    return Fingerprint(
        tool_name=tool_name,
        exact=canonical(arguments),
        normalized=canonical(normalize(arguments)),
    )


def find_match(
    call: Fingerprint, recorded: Sequence[Fingerprint], consumed: AbstractSet[int]
) -> tuple[int, str] | None:
    """Pick the recorded call that answers `call`, or None.

    `recorded` must be in recorded sequence order; the result is an index
    into it and the tier that matched. Indexes in `consumed` are skipped, so
    each recorded answer is handed out once -- which is what gives three
    identical polling calls the three recorded answers in order, rather than
    the first answer three times. Among equal candidates the earliest wins.
    """
    for tier in (TIER_EXACT, TIER_NORMALIZED):
        key = call.exact if tier == TIER_EXACT else call.normalized
        for index, candidate in enumerate(recorded):
            if index in consumed or candidate.tool_name != call.tool_name:
                continue
            candidate_key = candidate.exact if tier == TIER_EXACT else candidate.normalized
            if candidate_key == key:
                return index, tier
    return None
