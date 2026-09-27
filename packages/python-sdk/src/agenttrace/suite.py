"""Regression suites: a TOML file in the developer's repo, listing recorded cases.

A suite names the agent's entry point and a set of cases, each a recording
saved as a JSON file next to it. `agenttrace run-suite` replays every case
against the agent code as it is now and compares; nothing here needs the API,
because in CI there is none.

    name = "support"
    agent = "examples.async_support_agent:run_agent"

    [policy]                              # optional, applies to every case
    severity_overrides = { TOOL_ORDER_CHANGED = "info" }
    ignore_paths = ["generated_at"]

    [[cases]]
    name = "two-orders"
    recording = "recordings/two-orders.json"   # relative to this file
    [cases.policy]                        # optional, extends the suite's
    ignore_paths = ["reply.id"]

Everything is loaded and validated before any case runs, and any problem is
one `SuiteError` naming the file and case. A suite that ran the cases it could
load would report a verdict on part of itself, and CI would read that as the
agent's result.
"""

from __future__ import annotations

import importlib
import json
import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agenttrace.comparison import ComparisonPolicy
from agenttrace.errors import SuiteError
from agenttrace.recording import Recording

_SUITE_KEYS = {"name", "agent", "policy", "cases"}
_CASE_KEYS = {"name", "recording", "policy"}
_POLICY_KEYS = {"severity_overrides", "ignore_paths"}


@dataclass(frozen=True, slots=True)
class SuiteCase:
    """One recorded case, with the policy it is judged by (the suite's, extended)."""

    name: str
    recording_path: Path
    recording: Recording
    policy: ComparisonPolicy


@dataclass(frozen=True, slots=True)
class Suite:
    """A loaded, fully validated suite."""

    name: str
    path: Path
    agent: str
    policy: ComparisonPolicy
    cases: tuple[SuiteCase, ...]


def format_recording(payload: Mapping[str, Any]) -> str:
    """Serialise a recording the one way it is ever written to disk.

    Recordings are committed, so the file must be byte-stable: sorted keys and
    a fixed indent keep a re-export of the same run a zero-line diff, and a
    real change a readable one. `ensure_ascii=False` keeps non-English text
    reviewable rather than a wall of escapes.
    """
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def merge_policy(suite: ComparisonPolicy, case: ComparisonPolicy | None) -> ComparisonPolicy:
    """A case's policy extends the suite's; it never replaces it.

    `ignore_paths` are the union, suite's first, so a case cannot un-ignore a
    path the suite ignores. `severity_overrides` are merged with the case
    winning per code: the case is the more specific statement of intent.
    """
    if case is None:
        return suite
    paths = list(suite.ignore_paths)
    paths.extend(path for path in case.ignore_paths if path not in paths)
    return ComparisonPolicy(
        severity_overrides={**suite.severity_overrides, **case.severity_overrides},
        ignore_paths=tuple(paths),
    )


def load_suite(path: str | Path) -> Suite:
    """Load and validate a suite and every recording it names. Raises `SuiteError`."""
    suite_path = Path(path)
    where = str(suite_path)
    try:
        raw = tomllib.loads(suite_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SuiteError(f"cannot read suite: {exc.strerror or exc}", path=where) from exc
    except tomllib.TOMLDecodeError as exc:
        raise SuiteError(f"invalid TOML: {exc}", path=where) from exc

    _reject_unknown(raw, _SUITE_KEYS, "suite", where)
    name = _required_string(raw, "name", where)
    agent = _required_string(raw, "agent", where)
    _split_agent(agent, where)
    policy = _policy(raw.get("policy"), where) or ComparisonPolicy()

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        # An empty suite would pass vacuously -- green CI that tested nothing.
        raise SuiteError("needs at least one [[cases]] entry", path=where)

    cases: list[SuiteCase] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise SuiteError(f"cases[{index}] must be a table", path=where)
        label = raw_case.get("name") if isinstance(raw_case.get("name"), str) else None
        case_name = _required_string(raw_case, "name", where, case=label or f"#{index + 1}")
        if case_name in seen:
            raise SuiteError("duplicate case name", path=where, case=case_name)
        seen.add(case_name)
        _reject_unknown(raw_case, _CASE_KEYS, "case", where, case=case_name)
        relative = _required_string(raw_case, "recording", where, case=case_name)
        recording_path = suite_path.parent / relative
        recording = _load_recording(recording_path, case_name)
        case_policy = _policy(raw_case.get("policy"), where, case=case_name)
        try:
            merged = merge_policy(policy, case_policy)
        except (ValueError, TypeError) as exc:
            raise SuiteError(f"invalid policy: {exc}", path=where, case=case_name) from exc
        cases.append(
            SuiteCase(
                name=case_name,
                recording_path=recording_path,
                recording=recording,
                policy=merged,
            )
        )

    return Suite(name=name, path=suite_path, agent=agent, policy=policy, cases=tuple(cases))


def import_agent(suite: Suite) -> Callable[..., Any]:
    """Import the suite's `module:function` entry point. Raises `SuiteError`.

    Any exception while importing the module counts: an agent module that
    fails at import time is a broken suite, not a regressed agent.
    """
    module_name, function_name = _split_agent(suite.agent, str(suite.path))
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if not _is_the_agent_module(module_name, exc.name):
            # A dependency the agent imports is missing: today's message says
            # which, and the working directory is not the problem.
            raise SuiteError(
                f"cannot import agent module {module_name!r}: {type(exc).__name__}: {exc}",
                path=str(suite.path),
            ) from exc
        # The usual cause is running from the wrong directory, so say where
        # the module was looked for.
        raise SuiteError(
            f"cannot import agent module {module_name!r} from {os.getcwd()}: {exc}. "
            "run-suite imports the agent relative to the current directory -- "
            "usually your repo root.",
            path=str(suite.path),
        ) from exc
    except Exception as exc:  # whatever the module raised, the suite cannot run
        raise SuiteError(
            f"cannot import agent module {module_name!r}: {type(exc).__name__}: {exc}",
            path=str(suite.path),
        ) from exc
    agent = getattr(module, function_name, None)
    if agent is None:
        raise SuiteError(
            f"agent module {module_name!r} has no attribute {function_name!r}",
            path=str(suite.path),
        )
    if not callable(agent):
        raise SuiteError(f"agent {suite.agent!r} is not callable", path=str(suite.path))
    return agent


def _is_the_agent_module(module_name: str, missing: str | None) -> bool:
    """True when the module not found is the agent's own module or a parent package."""
    return missing is not None and (
        module_name == missing or module_name.startswith(f"{missing}.")
    )


def _split_agent(spec: str, where: str) -> tuple[str, str]:
    module_name, sep, function_name = spec.partition(":")
    if not sep or not module_name or not function_name:
        raise SuiteError(f"agent must be 'module:function', got {spec!r}", path=where)
    return module_name, function_name


def _load_recording(path: Path, case: str) -> Recording:
    """Read one recording file through `Recording.from_payload`, the only format there is."""
    where = str(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SuiteError(
            f"cannot read recording: {exc.strerror or exc}", path=where, case=case
        ) from exc
    except ValueError as exc:
        raise SuiteError(f"recording is not valid JSON: {exc}", path=where, case=case) from exc
    if not isinstance(payload, dict):
        raise SuiteError("recording must be a JSON object", path=where, case=case)
    try:
        return Recording.from_payload(payload)
    except Exception as exc:  # any malformed payload is the file's fault
        raise SuiteError(
            f"not a recording: {type(exc).__name__}: {exc}", path=where, case=case
        ) from exc


def _policy(raw: Any, where: str, case: str | None = None) -> ComparisonPolicy | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SuiteError("policy must be a table", path=where, case=case)
    _reject_unknown(raw, _POLICY_KEYS, "policy", where, case=case)
    overrides = raw.get("severity_overrides", {})
    if not isinstance(overrides, dict):
        raise SuiteError(
            "policy.severity_overrides must be a table", path=where, case=case
        )
    paths = raw.get("ignore_paths", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise SuiteError(
            "policy.ignore_paths must be a list of strings", path=where, case=case
        )
    try:
        return ComparisonPolicy(severity_overrides=overrides, ignore_paths=tuple(paths))
    except (ValueError, TypeError) as exc:
        raise SuiteError(f"invalid policy: {exc}", path=where, case=case) from exc


def _reject_unknown(
    table: Mapping[str, Any], allowed: set[str], what: str, where: str, case: str | None = None
) -> None:
    """Refuse keys the loader does not know. A misspelt key would otherwise be ignored."""
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise SuiteError(
            f"unknown {what} key(s) {', '.join(unknown)}; expected {', '.join(sorted(allowed))}",
            path=where,
            case=case,
        )


def _required_string(
    table: Mapping[str, Any], key: str, where: str, case: str | None = None
) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        problem = "missing" if key not in table else "must be a non-empty string"
        raise SuiteError(f"{key!r} {problem}", path=where, case=case)
    return value
