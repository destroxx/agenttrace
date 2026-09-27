"""The `agenttrace` command: run a regression suite, export a recording.

    agenttrace run-suite PATH [--agent-version LABEL]
    agenttrace export RUN_ID -o PATH [--force]

Exit codes are part of the contract, because CI branches on them:

    0  every case passed
    1  at least one case failed -- the agent regressed
    2  the suite could not run -- a bad suite file, an agent that will not
       import, bad arguments, an export that could not be written, or a
       case that replay itself could not run (printed as ERROR)

1 and 2 are kept apart so a pipeline can tell "the agent regressed" from "the
suite is broken". The first needs the author of the change; the second needs
whoever owns the suite, and treating it as a regression would send the wrong
person looking. A case the tooling could not replay makes the whole run a 2
even when other cases FAILed: a suite with a broken case cannot vouch for its
verdict, and its failures may be the same breakage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

from agenttrace.comparison import SEVERITY_ERROR, SEVERITY_WARNING, ComparisonReport
from agenttrace.config import TracerConfig
from agenttrace.errors import AgentTraceAPIError, RecordingNotFound, SuiteError
from agenttrace.recording import Recording, fetch_payload
from agenttrace.suite import Suite, format_recording, import_agent, load_suite
from agenttrace.tracer import AgentTracer

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_UNUSABLE = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its exit code, so tests can call it directly."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits on --help (0) and on bad arguments (2). Returning the
        # code instead keeps main() callable from tests; nothing else is caught.
        return int(exc.code or 0)
    handler: Callable[[argparse.Namespace, TextIO, TextIO], int] = args.handler
    return handler(args, sys.stdout, sys.stderr)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttrace", description="Replay regression suites and export recordings."
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = commands.add_parser(
        "run-suite",
        help="replay every case in a suite and compare",
        description="Replay every case in a suite against the current agent code.",
    )
    run.add_argument("path", metavar="PATH", help="the suite's TOML file")
    run.add_argument(
        "--agent-version",
        metavar="LABEL",
        help="version label to put on the replay runs, e.g. a git SHA",
    )
    run.set_defaults(handler=_run_suite)

    export = commands.add_parser(
        "export",
        help="save a stored run as a recording file",
        description="Fetch a run from the API and write it as a recording file.",
    )
    export.add_argument("run_id", metavar="RUN_ID")
    export.add_argument("-o", "--output", required=True, metavar="PATH")
    export.add_argument(
        "--force", action="store_true", help="overwrite PATH if it already exists"
    )
    export.set_defaults(handler=_export)
    return parser


# --- run-suite ----------------------------------------------------------------


def _run_suite(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    # The working directory goes first on sys.path, as uvicorn and pytest do,
    # so a suite run from the repo root can name `examples.my_agent:run`
    # without the user installing their own code as a package.
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    try:
        suite = load_suite(args.path)
        agent = import_agent(suite)
    except SuiteError as exc:
        print(f"agenttrace: {exc}", file=err)
        return EXIT_UNUSABLE

    # One tracer for the whole run, built from the environment: uploading stays
    # off unless AGENTTRACE_PROJECT_ID is set. It need not be the agent's own
    # tracer -- the replay session is module-level, so the agent's tools are
    # answered from the recording whichever tracer decorated them.
    tracer = AgentTracer()
    reports = asyncio.run(_run_cases(tracer, suite, agent, args.agent_version, out, err))

    passed = sum(1 for report in reports if report is not None and report.passed)
    could_not_run = sum(1 for report in reports if report is None)
    failed = len(reports) - passed - could_not_run
    summary = f"suite {suite.name}: {passed} passed, {failed} failed"
    if could_not_run:
        # Not "errors": on a FAIL line that word already means error-severity findings.
        summary += f", {could_not_run} could not run"
    print(summary, file=out, flush=True)
    if could_not_run:
        return EXIT_UNUSABLE
    return EXIT_PASSED if failed == 0 else EXIT_FAILED


async def _run_cases(
    tracer: AgentTracer,
    suite: Suite,
    agent: Callable[..., Any],
    agent_version: str | None,
    out: TextIO,
    err: TextIO,
) -> list[ComparisonReport | None]:
    """Run the cases one at a time, printing each line as its verdict is known.

    Sequential on purpose: cases share the agent module, and a slow suite that
    prints as it goes is easier to follow in a CI log than a fast silent one.
    """
    width = max(len(case.name) for case in suite.cases)
    reports: list[ComparisonReport | None] = []
    for case in suite.cases:
        try:
            _, report = await tracer.replay_and_compare(
                case.recording, agent, agent_version=agent_version, policy=case.policy
            )
        except Exception as exc:  # noqa: BLE001 - one broken case must not hide the rest
            # The agent's own exceptions are already an AGENT_ERROR finding;
            # reaching here means replay itself could not run the case, which
            # says nothing about the agent -- so ERROR, not FAIL. "ERROR " is
            # as wide as "PASS  ", which keeps the case names in one column.
            print(f"ERROR {case.name:<{width}}  could not replay", file=out, flush=True)
            print(f"agenttrace: case {case.name!r}: {type(exc).__name__}: {exc}", file=err)
            reports.append(None)
            continue
        print(_case_lines(case.name, width, report), file=out, flush=True)
        reports.append(report)
    return reports


def _case_lines(name: str, width: int, report: ComparisonReport) -> str:
    """`PASS  name` or `FAIL  name  2 errors, 1 warning`, then a FAIL's errors."""
    counts = report.counts["by_severity"]
    tally = ", ".join(
        f"{counts[severity]} {severity}{'' if counts[severity] == 1 else 's'}"
        for severity in (SEVERITY_ERROR, SEVERITY_WARNING)
        if counts[severity]
    )
    head = f"{'PASS' if report.passed else 'FAIL'}  {name:<{width}}"
    lines = [f"{head}  {tally}".rstrip()]
    if not report.passed:
        errors = [f for f in report.findings if f.severity == SEVERITY_ERROR]
        code_width = max(len(f.code) for f in errors)
        indent = " " * len("FAIL  ")
        lines.extend(f"{indent}{f.code:<{code_width}}  {f.message}" for f in errors)
    return "\n".join(lines)


# --- export -------------------------------------------------------------------


def _export(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    target = Path(args.output)
    # Checked before the fetch as well as at the write, so a refusal costs
    # nothing. A recording is a frozen fixture: silently replacing one would
    # change what a test asserts without anyone seeing it happen.
    if target.exists() and not args.force:
        print(
            f"agenttrace: {target} already exists; recordings are not overwritten "
            "without --force",
            file=err,
        )
        return EXIT_UNUSABLE

    config = TracerConfig.from_env()
    try:
        payload = fetch_payload(args.run_id, config)
    except RecordingNotFound:
        print(f"agenttrace: run {args.run_id} not found at {config.api_url}", file=err)
        return EXIT_UNUSABLE
    except AgentTraceAPIError as exc:
        print(f"agenttrace: could not fetch run {args.run_id}: {exc}", file=err)
        return EXIT_UNUSABLE

    if payload.get("status") == "running":
        print(
            f"agenttrace: run {args.run_id} is still running; only a finished run "
            "is a complete recording",
            file=err,
        )
        return EXIT_UNUSABLE
    try:
        # Proves the file will load in a suite before it is written.
        Recording.from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - any failure means an unusable fixture
        print(f"agenttrace: run {args.run_id} is not a usable recording: {exc}", file=err)
        return EXIT_UNUSABLE

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # "x" refuses to replace a file that appeared since the check above.
        with target.open("w" if args.force else "x", encoding="utf-8") as handle:
            handle.write(format_recording(payload))
    except FileExistsError:
        print(f"agenttrace: {target} already exists; pass --force to overwrite", file=err)
        return EXIT_UNUSABLE
    except OSError as exc:
        print(f"agenttrace: could not write {target}: {exc}", file=err)
        return EXIT_UNUSABLE

    print(f"wrote {target}", file=out)
    print("\nadd it to suite.toml:\n", file=out)
    print(_case_snippet(target), file=out)
    return EXIT_PASSED


def _case_snippet(target: Path) -> str:
    """The `[[cases]]` entry for a new recording file.

    The path in a suite is relative to suite.toml, which export does not know.
    It assumes the conventional layout -- recordings/ next to suite.toml --
    and otherwise prints the path as given, for the user to adjust.
    """
    relative = f"recordings/{target.name}" if target.parent.name == "recordings" else str(target)
    return "\n".join(
        [
            "[[cases]]",
            f"name = {_toml_string(target.stem)}",
            f"recording = {_toml_string(relative)}",
        ]
    )


def _toml_string(value: str) -> str:
    # A JSON string is a valid TOML basic string for everything a file name holds.
    return json.dumps(value, ensure_ascii=False)
