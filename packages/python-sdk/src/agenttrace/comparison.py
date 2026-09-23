"""Turning a replay into a verdict.

Pure functions and frozen values: no I/O, no tracer, no clock, no randomness.
`compare(recording, replay_result)` reads what replay already established --
which live call matched which recorded one, at which tier, and what went
unused -- and never re-matches anything itself. Replay and comparison
therefore cannot disagree about what "the same call" means; there is one
definition of it, in `agenttrace.matching`.

Comparison is layered, strictest first:

1. **exact** -- the tool calls and the output are identical. No findings.
2. **behavioral** -- this module. Each difference becomes a `Finding` with a
   code and a severity: a skipped step, a call nothing recorded, a reordered
   call, a changed status, a changed output field.
3. **semantic** -- planned, not built: deciding whether two differently worded
   answers mean the same thing needs a model, and a model is neither
   deterministic nor free. Until it exists, a pure wording change is reported
   as `OUTPUT_TEXT_CHANGED` and is a warning, not an error.

The verdict is driven entirely by severity: FAIL if any finding is an error.
Which differences are errors is policy, not mechanism, so `ComparisonPolicy`
can raise or lower any code and mark output paths that are expected to vary.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from types import MappingProxyType
from typing import Any

from agenttrace.matching import TIER_NORMALIZED, TIER_UNMATCHED, canonical, normalize
from agenttrace.recording import Recording
from agenttrace.replay import ReplayResult, ToolCallMatch

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO)

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"

MISSING_TOOL_CALL = "MISSING_TOOL_CALL"
UNEXPECTED_TOOL_CALL = "UNEXPECTED_TOOL_CALL"
ARGUMENTS_NORMALIZED = "ARGUMENTS_NORMALIZED"
TOOL_ORDER_CHANGED = "TOOL_ORDER_CHANGED"
STATUS_CHANGED = "STATUS_CHANGED"
AGENT_ERROR = "AGENT_ERROR"
OUTPUT_STRUCTURE_CHANGED = "OUTPUT_STRUCTURE_CHANGED"
OUTPUT_TEXT_CHANGED = "OUTPUT_TEXT_CHANGED"
OUTPUT_MISSING = "OUTPUT_MISSING"

# Declaration order is also the order codes appear in `counts["by_code"]`.
DEFAULT_SEVERITIES: Mapping[str, str] = MappingProxyType(
    {
        AGENT_ERROR: SEVERITY_ERROR,
        STATUS_CHANGED: SEVERITY_ERROR,
        MISSING_TOOL_CALL: SEVERITY_ERROR,
        UNEXPECTED_TOOL_CALL: SEVERITY_ERROR,
        ARGUMENTS_NORMALIZED: SEVERITY_WARNING,
        TOOL_ORDER_CHANGED: SEVERITY_WARNING,
        OUTPUT_MISSING: SEVERITY_ERROR,
        OUTPUT_STRUCTURE_CHANGED: SEVERITY_ERROR,
        # A warning, not an error: exact text equality is brittle for agents
        # that answer in natural language -- a model rephrasing "arriving
        # tomorrow" as "due tomorrow" is not a regression -- and judging
        # whether two wordings mean the same thing is the planned semantic
        # layer's job, not a string comparison's. Teams that need exact text
        # raise it to "error" with `ComparisonPolicy(severity_overrides=...)`.
        OUTPUT_TEXT_CHANGED: SEVERITY_WARNING,
    }
)
CODES = tuple(DEFAULT_SEVERITIES)

# Findings sort by severity, then by what they are about: the run as a whole,
# then tool calls in recorded order, then output fields by path.
_SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}
_SCOPE_RUN, _SCOPE_TOOLS, _SCOPE_OUTPUT = 0, 1, 2

# Diff kinds. Only TEXT is a wording change; everything else is structural.
CHANGE_ADDED = "added"
CHANGE_REMOVED = "removed"
CHANGE_TYPE = "type_changed"
CHANGE_VALUE = "value_changed"
CHANGE_LENGTH = "length_changed"
CHANGE_TEXT = "text_changed"

_VALUE_WIDTH = 60
# Characters of unchanged text shown either side of a wording change.
_CONTEXT = 12

PathPart = str | int


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason a replay differs from its recording.

    `details` is structured and JSON-serialisable -- tool name, call ids,
    recorded vs new arguments, the output path and both values, as relevant to
    the code -- so a report can be stored and queried, not just read.
    `message` is the same fact for a human, on one line.
    """

    code: str
    severity: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "details": copy.deepcopy(dict(self.details)),
        }


@dataclass(frozen=True, slots=True)
class ComparisonPolicy:
    """What counts as a failure. The defaults suit a first regression suite.

    `severity_overrides` maps a finding code to "error", "warning" or "info",
    replacing its default (see `DEFAULT_SEVERITIES`):

    - error: MISSING_TOOL_CALL, UNEXPECTED_TOOL_CALL, STATUS_CHANGED,
      AGENT_ERROR, OUTPUT_STRUCTURE_CHANGED, OUTPUT_MISSING
    - warning: ARGUMENTS_NORMALIZED, TOOL_ORDER_CHANGED, OUTPUT_TEXT_CHANGED

    Raise `OUTPUT_TEXT_CHANGED` to "error" to require word-for-word output;
    lower `TOOL_ORDER_CHANGED` to "info" for an agent whose tool order is
    genuinely irrelevant, or raise it to "error" for one where it never is.

    `ignore_paths` are dot paths into the output that are expected to vary
    between runs -- `"timestamp"`, `"reply.generated_at"`. A difference at such
    a path, or anywhere beneath it, is still reported but as "info", so it
    never fails the verdict and is never silently hidden. A `*` segment matches
    any list index: `"items.*.id"` covers `items.0.id`, `items.1.id`, ...
    List indices are plain numbers in a path (`"items.0.id"`); a dict key that
    itself contains a dot cannot be addressed.

    A bad policy fails at construction -- an unknown code or severity with
    `ValueError`, a bare string for `ignore_paths` with `TypeError` -- because
    a misspelt override that silently did nothing would make a suite stricter
    or looser than its author believes.
    """

    severity_overrides: Mapping[str, str] = field(default_factory=dict)
    ignore_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for code, severity in self.severity_overrides.items():
            if code not in DEFAULT_SEVERITIES:
                raise ValueError(f"unknown finding code {code!r}; expected one of {CODES}")
            if severity not in SEVERITIES:
                raise ValueError(f"unknown severity {severity!r}; expected one of {SEVERITIES}")
        if isinstance(self.ignore_paths, str):
            raise TypeError("ignore_paths must be a sequence of paths, not one string")
        # Copied and frozen, so a caller mutating their dict or list afterwards
        # cannot change a policy that is already in use.
        object.__setattr__(
            self, "severity_overrides", MappingProxyType(dict(self.severity_overrides))
        )
        object.__setattr__(self, "ignore_paths", tuple(self.ignore_paths))

    def severity_of(self, code: str) -> str:
        return self.severity_overrides.get(code, DEFAULT_SEVERITIES[code])

    def is_ignored(self, path: tuple[PathPart, ...]) -> bool:
        """True if an ignore pattern matches `path` or one of its ancestors."""
        return any(_pattern_covers(pattern, path) for pattern in self.ignore_paths)


def _pattern_covers(pattern: str, path: tuple[PathPart, ...]) -> bool:
    parts = pattern.split(".")
    if len(parts) > len(path):
        return False
    for want, have in zip(parts, path, strict=False):
        if want == "*":
            if not isinstance(have, int):
                return False
        elif want != str(have):
            return False
    return True


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """The verdict on one replay, and every finding behind it.

    `findings` are in a stable order: errors, then warnings, then info; within
    a severity, run-level findings first, then tool calls in recorded
    sequence, then output fields by path. The same inputs always produce the
    same report, byte for byte from `to_dict`.
    """

    verdict: str
    findings: tuple[Finding, ...]
    counts: Mapping[str, Mapping[str, int]]
    recording_run_id: str
    replay_run_id: str | None

    @property
    def passed(self) -> bool:
        return self.verdict == VERDICT_PASS

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable form with a fixed key order, for storing reports."""
        return {
            "verdict": self.verdict,
            "recording_run_id": self.recording_run_id,
            "replay_run_id": self.replay_run_id,
            "counts": {
                "by_severity": dict(self.counts["by_severity"]),
                "by_code": dict(self.counts["by_code"]),
            },
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def format(self) -> str:
        """A plain-text report: the verdict, then one line per finding."""
        by_severity = self.counts["by_severity"]
        tally = ", ".join(
            f"{by_severity[s]} {s}{'' if by_severity[s] == 1 or s == SEVERITY_INFO else 's'}"
            for s in SEVERITIES
        )
        lines = [
            (
                f"{self.verdict.upper()}  {tally}  "
                f"(recording {self.recording_run_id} -> replay {self.replay_run_id or '-'})"
            )
        ]
        width = max((len(f.code) for f in self.findings), default=0)
        for finding in self.findings:
            lines.append(
                f"  {finding.severity:<7}  {finding.code:<{width}}  {finding.message}"
            )
        return "\n".join(lines)


# --- JSON diff ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Difference:
    """One place two JSON values differ. `recorded`/`new` are None when absent."""

    path: tuple[PathPart, ...]
    change: str
    recorded: Any = None
    new: Any = None


def format_path(path: Iterable[PathPart]) -> str:
    """`("items", 0, "id")` -> `"items.0.id"`; the root is `""`."""
    return ".".join(str(part) for part in path)


def json_type(value: Any) -> str:
    """The JSON type name of a value; ints and floats are both `number`."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def diff_json(recorded: Any, new: Any, path: tuple[PathPart, ...] = ()) -> list[Difference]:
    """Every difference between two JSON values, in a deterministic order.

    Dicts are compared key by key in sorted order: a key only on one side is
    `added` or `removed`, a key on both is compared recursively. A list whose
    length changed gets one `length_changed` at the list's own path, and the
    indexes both sides have are compared one by one -- so an appended item is
    one difference, not one per shifted element. Two different strings are
    `text_changed`; any other change of a leaf is `type_changed` (JSON types
    differ) or `value_changed`.

    The values are compared as given. `compare` normalises them first.
    """
    if json_type(recorded) != json_type(new):
        return [Difference(path, CHANGE_TYPE, recorded, new)]
    if isinstance(recorded, dict):
        differences: list[Difference] = []
        for key in sorted(recorded.keys() | new.keys()):
            here = (*path, key)
            if key not in new:
                differences.append(Difference(here, CHANGE_REMOVED, recorded=recorded[key]))
            elif key not in recorded:
                differences.append(Difference(here, CHANGE_ADDED, new=new[key]))
            else:
                differences.extend(diff_json(recorded[key], new[key], here))
        return differences
    if isinstance(recorded, list):
        differences = []
        if len(recorded) != len(new):
            differences.append(Difference(path, CHANGE_LENGTH, len(recorded), len(new)))
        for index, (old_item, new_item) in enumerate(zip(recorded, new, strict=False)):
            differences.extend(diff_json(old_item, new_item, (*path, index)))
        return differences
    if recorded == new:
        return []
    if isinstance(recorded, str):
        return [Difference(path, CHANGE_TEXT, recorded, new)]
    return [Difference(path, CHANGE_VALUE, recorded, new)]


# --- comparison ---------------------------------------------------------------


def compare(
    recording: Recording,
    replay_result: ReplayResult,
    policy: ComparisonPolicy | None = None,
) -> ComparisonReport:
    """Judge `replay_result` against the `recording` it replayed.

    Deterministic: the report depends only on the two arguments and the
    policy, never on the clock or on the order concurrent calls happened to
    finish in.
    """
    policy = policy or ComparisonPolicy()
    keyed: list[tuple[tuple[Any, ...], Finding]] = []

    def add(code: str, message: str, details: dict[str, Any], key: tuple[Any, ...],
            *, ignored: bool = False) -> None:
        severity = SEVERITY_INFO if ignored else policy.severity_of(code)
        if ignored:
            details["ignored"] = True
        keyed.append(((_SEVERITY_RANK[severity], *key), Finding(code, severity, message, details)))

    _run_findings(recording, replay_result, add)
    _tool_findings(replay_result, add)
    _output_findings(recording.output, replay_result.output, policy, add)

    keyed.sort(key=lambda item: item[0])
    findings = tuple(finding for _, finding in keyed)
    by_severity = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    by_code = {
        code: count for code in CODES if (count := sum(1 for f in findings if f.code == code))
    }
    return ComparisonReport(
        verdict=VERDICT_FAIL if by_severity[SEVERITY_ERROR] else VERDICT_PASS,
        findings=findings,
        counts=MappingProxyType(
            {
                "by_severity": MappingProxyType(by_severity),
                "by_code": MappingProxyType(by_code),
            }
        ),
        recording_run_id=recording.run_id,
        replay_run_id=replay_result.trace.id if replay_result.trace is not None else None,
    )


def _run_findings(recording: Recording, result: ReplayResult, add: Any) -> None:
    run_key = (_SCOPE_RUN,)
    if result.error is not None:
        error_type = str(result.error.get("type", "Error"))
        error_message = str(result.error.get("message", ""))
        add(
            AGENT_ERROR,
            f"the agent raised {error_type}: {_short(error_message)}",
            {"type": error_type, "message": error_message},
            (*run_key, 0),
        )
    if recording.status != result.status:
        add(
            STATUS_CHANGED,
            f"run status changed from {recording.status!r} to {result.status!r}",
            {"recorded": recording.status, "new": result.status},
            (*run_key, 1),
        )


def _tool_findings(result: ReplayResult, add: Any) -> None:
    for unused in result.unused:
        add(
            MISSING_TOOL_CALL,
            f"{_call(unused.tool_name, unused.arguments)} was recorded "
            f"(seq {unused.recorded_sequence}) but never called",
            {
                "tool_name": unused.tool_name,
                "recorded_call_id": unused.recorded_call_id,
                "recorded_sequence": unused.recorded_sequence,
                "recorded_arguments": unused.arguments,
            },
            (_SCOPE_TOOLS, unused.recorded_sequence, 0),
        )

    for match in result.matches:
        if match.tier == TIER_UNMATCHED:
            # No recorded position to sort by; ordering by content rather than
            # by when the call happened keeps parallel calls in a stable order.
            add(
                UNEXPECTED_TOOL_CALL,
                f"{_call(match.tool_name, match.new_arguments)} matches no recorded call",
                {
                    "tool_name": match.tool_name,
                    "new_call_id": match.new_call_id,
                    "new_arguments": match.new_arguments,
                },
                (_SCOPE_TOOLS, float("inf"), 0, match.tool_name,
                 canonical(match.new_arguments), match.new_call_id or ""),
            )
        elif match.tier == TIER_NORMALIZED:
            changed = [
                format_path(d.path)
                for d in diff_json(match.recorded_arguments or {}, match.new_arguments)
            ]
            add(
                ARGUMENTS_NORMALIZED,
                f"{match.tool_name} (seq {match.recorded_sequence}) matched only after "
                f"normalizing {', '.join(changed) or 'its arguments'}",
                {
                    "tool_name": match.tool_name,
                    "recorded_call_id": match.recorded_call_id,
                    "new_call_id": match.new_call_id,
                    "recorded_sequence": match.recorded_sequence,
                    "recorded_arguments": match.recorded_arguments,
                    "new_arguments": match.new_arguments,
                    "paths": changed,
                },
                (_SCOPE_TOOLS, match.recorded_sequence, 1),
            )

    for earlier, later in _order_inversions(result.matches):
        add(
            TOOL_ORDER_CHANGED,
            f"{later.tool_name} (seq {later.recorded_sequence}) now runs after "
            f"{earlier.tool_name} (seq {earlier.recorded_sequence}); it was recorded before it",
            {
                "tool_name": later.tool_name,
                "recorded_call_id": later.recorded_call_id,
                "new_call_id": later.new_call_id,
                "recorded_sequence": later.recorded_sequence,
                "after_tool_name": earlier.tool_name,
                "after_recorded_call_id": earlier.recorded_call_id,
                "after_recorded_sequence": earlier.recorded_sequence,
            },
            (_SCOPE_TOOLS, later.recorded_sequence, 2),
        )


def _order_inversions(
    matches: list[ToolCallMatch],
) -> list[tuple[ToolCallMatch, ToolCallMatch]]:
    """Where the replay stepped backwards through the recorded order.

    Order can matter as much as the calls themselves: an agent that now
    confirms a booking *after* making it, or refunds before checking
    eligibility, makes exactly the recorded calls and is still broken.

    The matched calls are taken in the order the replay made them, and each
    adjacent pair whose recorded sequences go down is one inversion. Adjacent
    pairs rather than every inverted pair, so moving one step from first to
    last is one finding ("X now runs after Z"), not one per step it jumped
    over. Unmatched calls have no recorded position and are skipped; they are
    reported as unexpected instead.
    """
    matched = [(m.recorded_sequence, m) for m in matches if m.recorded_sequence is not None]
    return [
        (earlier, later)
        for (earlier_seq, earlier), (later_seq, later) in pairwise(matched)
        if later_seq < earlier_seq
    ]


def _output_findings(
    recorded: dict[str, Any] | None,
    new: dict[str, Any] | None,
    policy: ComparisonPolicy,
    add: Any,
) -> None:
    if recorded is None and new is None:
        return
    if recorded is None or new is None:
        side = "the replay" if new is None else "the recording"
        add(
            OUTPUT_MISSING,
            f"{side} has no output",
            {"recorded": recorded, "new": new},
            (_SCOPE_OUTPUT, ()),
        )
        return
    # Compared after `normalize`, the same function tool matching uses, so an
    # output differing only in surrounding whitespace, `2` vs `2.0`, or a key
    # set to None vs left out is not reported at all -- if that difference
    # cannot tell two tool calls apart, it should not fail an output either.
    for difference in diff_json(normalize(recorded), normalize(new)):
        path = format_path(difference.path)
        code = OUTPUT_TEXT_CHANGED if difference.change == CHANGE_TEXT else OUTPUT_STRUCTURE_CHANGED
        add(
            code,
            _describe(difference, path),
            {
                "path": path,
                "change": difference.change,
                "recorded": difference.recorded,
                "new": difference.new,
            },
            (_SCOPE_OUTPUT, difference.path),
            ignored=policy.is_ignored(difference.path),
        )


def _describe(difference: Difference, path: str) -> str:
    where = f"output.{path}" if path else "output"
    change = difference.change
    if change == CHANGE_ADDED:
        return f"{where} was added: {_value(difference.new)}"
    if change == CHANGE_REMOVED:
        return f"{where} was removed (was {_value(difference.recorded)})"
    if change == CHANGE_LENGTH:
        return f"{where} length changed from {difference.recorded} to {difference.new}"
    if change == CHANGE_TYPE:
        return (
            f"{where} changed type from {json_type(difference.recorded)} to "
            f"{json_type(difference.new)}: {_value(difference.recorded)} -> "
            f"{_value(difference.new)}"
        )
    if change == CHANGE_TEXT:
        old, new = _text_window(difference.recorded, difference.new)
        return f"{where} text changed: {old} -> {new}"
    return f"{where} changed: {_value(difference.recorded)} -> {_value(difference.new)}"


def _text_window(old: str, new: str) -> tuple[str, str]:
    """The part of two strings that differs, with a little context.

    Long replies usually share most of their text, and a message that shows
    each side's first sixty characters would show two identical openings.
    """
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(old), len(new)) - prefix
        and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]
    ):
        suffix += 1
    start = max(0, prefix - _CONTEXT)
    lead = "…" if start else ""
    tail = "…" if suffix > _CONTEXT else ""
    end = max(0, suffix - _CONTEXT)
    return (
        lead + _value(old[start : len(old) - end]) + tail,
        lead + _value(new[start : len(new) - end]) + tail,
    )


def _value(value: Any) -> str:
    """A value as one line of JSON, cut short -- for messages, never for details."""
    return _short(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _short(text: str) -> str:
    text = text.replace("\n", "\\n")
    return text if len(text) <= _VALUE_WIDTH else text[: _VALUE_WIDTH - 1] + "…"


def _call(tool_name: str, arguments: Mapping[str, Any] | None) -> str:
    rendered = ", ".join(
        f"{key}={_value(value)}" for key, value in sorted((arguments or {}).items())
    )
    return f"{tool_name}({_short(rendered)})"
