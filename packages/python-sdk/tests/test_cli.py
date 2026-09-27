"""Tests for the `agenttrace` command: run-suite and export.

`main([...])` is called directly and returns the exit code, so these exercise
exactly what the console script runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from fake_api import closed_port, fake_api

from agenttrace import AgentTracer, Recording, TracerConfig
from agenttrace.cli import main
from agenttrace.suite import format_recording
from agenttrace.transport import build_payload

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ID = "3f1d9c88-5b7a-4f2e-9f6c-1b2a3c4d5e6f"

AGENT_MODULE = '''
from agenttrace import AgentTracer, TracerConfig

# The agent's own tracer. The CLI builds a different one; replay must still
# answer these tools from the recording.
tracer = AgentTracer(TracerConfig())
REAL_CALLS = []


@tracer.tool
def lookup(key: str) -> str:
    REAL_CALLS.append(key)
    return f"value-{key}"


def run(request: dict) -> str:
    with tracer.trace("agent", input=request) as trace:
        if request["key"] == "boom":
            raise ValueError("the agent blew up")
        value = lookup(request["key"])
        trace.set_output({"value": value})
    return value
'''


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No uploads unless a test asks, and no sys.path leaking between tests."""
    for name in ("AGENTTRACE_PROJECT_ID", "AGENTTRACE_API_URL", "AGENTTRACE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(tmp_path)


def _agent_module(tmp_path: Path) -> str:
    """Write the agent under a fresh module name, so no test sees another's import."""
    name = f"agent_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(AGENT_MODULE, encoding="utf-8")
    return name


def _record(tmp_path: Path, case: str, key: str, calls: list[str]) -> str:
    """A recording of an agent that called `lookup` once per entry in `calls`."""
    tracer = AgentTracer(TracerConfig())

    @tracer.tool(name="lookup")
    def lookup(key: str) -> str:
        return f"value-{key}"

    with tracer.trace("agent", input={"key": key}) as trace:
        value = None
        for call in calls:
            value = lookup(call)
        if value is not None:
            trace.set_output({"value": value})
    folder = tmp_path / "recordings"
    folder.mkdir(exist_ok=True)
    (folder / f"{case}.json").write_text(format_recording(build_payload(trace)))
    return f"recordings/{case}.json"


def _suite(tmp_path: Path, module: str, cases: dict[str, str]) -> str:
    lines = ['name = "demo"', f'agent = "{module}:run"']
    for case, recording in cases.items():
        lines += ["[[cases]]", f'name = "{case}"', f'recording = "{recording}"']
    path = tmp_path / "suite.toml"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


# --- run-suite ----------------------------------------------------------------


def test_run_suite_exits_0_when_every_case_passes(tmp_path: Path, capsys) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(
        tmp_path,
        module,
        {"alpha": _record(tmp_path, "alpha", "a", ["a"]),
         "beta": _record(tmp_path, "beta", "b", ["b"])},
    )

    code = main(["run-suite", suite])

    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines() == ["PASS  alpha", "PASS  beta", "suite demo: 2 passed, 0 failed"]
    assert sys.modules[module].REAL_CALLS == []


def test_run_suite_exits_1_and_lists_a_failing_cases_errors(tmp_path: Path, capsys) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(
        tmp_path,
        module,
        {
            "same": _record(tmp_path, "same", "a", ["a"]),
            # recorded when the agent made a second lookup; today it makes one
            "skipped-step": _record(tmp_path, "skipped-step", "a", ["a", "b"]),
        },
    )

    code = main(["run-suite", suite])

    lines = capsys.readouterr().out.splitlines()
    assert code == 1
    assert lines[0] == "PASS  same"
    assert lines[1] == "FAIL  skipped-step  1 error, 1 warning"
    assert lines[2].startswith("      MISSING_TOOL_CALL  ")
    assert 'lookup(key="b")' in lines[2]
    # warnings are counted on the FAIL line but not listed
    assert "OUTPUT_TEXT_CHANGED" not in "\n".join(lines)
    assert lines[-1] == "suite demo: 1 passed, 1 failed"


def test_an_agent_that_raises_fails_its_case_and_the_suite_finishes(
    tmp_path: Path, capsys
) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(
        tmp_path,
        module,
        {"boom": _record(tmp_path, "boom", "boom", []),
         "after": _record(tmp_path, "after", "a", ["a"])},
    )

    code = main(["run-suite", suite])

    lines = capsys.readouterr().out.splitlines()
    assert code == 1
    assert lines[0].startswith("FAIL  boom ")
    assert any("AGENT_ERROR" in line and "the agent blew up" in line for line in lines)
    assert "PASS  after" in lines
    assert lines[-1] == "suite demo: 1 passed, 1 failed"


def test_run_suite_exits_2_on_a_suite_error_and_runs_nothing(tmp_path: Path, capsys) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(tmp_path, module, {"missing": "recordings/missing.json"})

    code = main(["run-suite", suite])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "case 'missing'" in captured.err and "cannot read recording" in captured.err


def test_run_suite_exits_2_when_the_agent_cannot_be_imported(tmp_path: Path, capsys) -> None:
    suite = _suite(tmp_path, "no_such_agent_module", {"a": _record(tmp_path, "a", "a", ["a"])})

    code = main(["run-suite", suite])

    captured = capsys.readouterr()
    assert code == 2
    assert "cannot import agent module 'no_such_agent_module'" in captured.err
    assert captured.out == ""


def test_a_case_replay_could_not_run_prints_error_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The tooling breaking is not the agent regressing, even beside a real FAIL."""
    module = _agent_module(tmp_path)
    suite = _suite(
        tmp_path,
        module,
        {
            "skipped-step": _record(tmp_path, "skipped-step", "a", ["a", "b"]),
            "broken": _record(tmp_path, "broken", "x", ["x"]),
            "fine": _record(tmp_path, "fine", "c", ["c"]),
        },
    )
    real = AgentTracer.replay_and_compare

    async def breaks_for_one_case(self, recording, agent_fn, **kwargs):
        if recording.input == {"key": "x"}:
            raise RuntimeError("replay machinery broke")
        return await real(self, recording, agent_fn, **kwargs)

    monkeypatch.setattr(AgentTracer, "replay_and_compare", breaks_for_one_case)

    code = main(["run-suite", suite])

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert code == 2
    assert lines[0].startswith("FAIL  skipped-step  ")
    error_line = next(line for line in lines if line.startswith("ERROR"))
    assert error_line == "ERROR broken        could not replay"
    assert "PASS  fine" in lines  # the cases after the broken one still ran
    # the case names stay in one column whatever the status word
    assert lines[0].index("skipped-step") == error_line.index("broken") == len("PASS  ")
    assert lines[-1] == "suite demo: 1 passed, 1 failed, 1 could not run"
    assert "replay machinery broke" in captured.err


def test_the_summary_omits_could_not_run_when_every_case_ran(tmp_path: Path, capsys) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(tmp_path, module, {"a": _record(tmp_path, "a", "a", ["a"])})

    assert main(["run-suite", suite]) == 0
    assert "could not run" not in capsys.readouterr().out


def test_an_agent_module_not_found_names_the_directory_searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Run from the wrong directory, the package is not importable: say where we looked."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    module = _agent_module(tmp_path)
    suite = _suite(tmp_path, f"pkg_{module}.agent", {"a": _record(tmp_path, "a", "a", ["a"])})
    monkeypatch.chdir(elsewhere)

    code = main(["run-suite", suite])

    err = capsys.readouterr().err
    assert code == 2
    assert f"from {os.getcwd()}:" in err
    assert "No module named" in err
    assert "usually your repo root" in err


def test_a_missing_dependency_of_the_agent_keeps_the_plain_message(
    tmp_path: Path, capsys
) -> None:
    """The agent module was found; a package it imports was not. The cwd is not the cause."""
    name = f"agent_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text("import a_dependency_that_is_not_installed\n")
    suite = _suite(tmp_path, name, {"a": _record(tmp_path, "a", "a", ["a"])})

    code = main(["run-suite", suite])

    err = capsys.readouterr().err
    assert code == 2
    assert "a_dependency_that_is_not_installed" in err
    assert "repo root" not in err


def test_run_suite_exits_2_when_the_function_is_missing(tmp_path: Path, capsys) -> None:
    module = _agent_module(tmp_path)
    path = Path(_suite(tmp_path, module, {"a": _record(tmp_path, "a", "a", ["a"])}))
    path.write_text(path.read_text().replace(f"{module}:run", f"{module}:nope"))

    assert main(["run-suite", str(path)]) == 2
    assert "has no attribute 'nope'" in capsys.readouterr().err


def test_bad_arguments_exit_2(capsys) -> None:
    assert main(["run-suite"]) == 2
    assert main(["no-such-command"]) == 2
    assert main(["--help"]) == 0


def test_the_agent_version_label_reaches_the_replay_trace(tmp_path: Path) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(tmp_path, module, {"a": _record(tmp_path, "a", "a", ["a"])})

    assert main(["run-suite", suite, "--agent-version", "sha-123"]) == 0

    traces = sys.modules[module].tracer.completed_traces
    assert traces[-1].agent_version == "sha-123"


def test_replay_answers_the_agents_tools_when_the_cli_tracer_is_not_the_agents() -> None:
    """The replay session is module-level, so any tracer's @tool is replayed."""
    agents_tracer = AgentTracer(TracerConfig())
    cli_tracer = AgentTracer(TracerConfig())
    real_calls: list[str] = []

    @agents_tracer.tool
    def lookup(key: str) -> str:
        real_calls.append(key)
        return f"value-{key}"

    def agent(request: dict) -> str:
        with agents_tracer.trace("agent", input=request) as trace:
            value = lookup(request["key"])
            trace.set_output({"value": value})
        return value

    agent({"key": "a"})
    recording = Recording.from_trace(agents_tracer.completed_traces[-1])
    real_calls.clear()

    result, report = asyncio.run(cli_tracer.replay_and_compare(recording, agent))

    assert agents_tracer is not cli_tracer
    assert real_calls == []
    assert result.return_value == "value-a"
    assert report.passed, report.format()
    # the replay trace belongs to the agent's tracer, which opened it
    assert result.trace in agents_tracer.completed_traces


def test_run_suite_makes_no_http_request_when_uploading_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(tmp_path, module, {"a": _record(tmp_path, "a", "a", ["a"])})
    with fake_api() as api:
        # an API is reachable, but without a project id nothing may be sent to it
        monkeypatch.setenv("AGENTTRACE_API_URL", api.url)

        assert main(["run-suite", suite]) == 0

        assert api.requests == []
        assert api.gets == []


def test_a_failed_upload_does_not_change_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    module = _agent_module(tmp_path)
    suite = _suite(tmp_path, module, {"a": _record(tmp_path, "a", "a", ["a"])})
    with fake_api(status=422) as api:
        # uploading is on, and the API refuses the report: its recording is not
        # a run in the project
        monkeypatch.setenv("AGENTTRACE_API_URL", api.url)
        monkeypatch.setenv("AGENTTRACE_PROJECT_ID", PROJECT_ID)

        code = main(["run-suite", suite])

        assert code == 0
        assert "PASS  a" in capsys.readouterr().out
        # The CLI's tracer uploads the report. The replay trace is the agent's
        # own tracer's to upload, and this agent's tracer has uploading off.
        paths = [request.path for request in api.requests]
        assert paths and all(path.endswith("/comparison") for path in paths)


def test_the_example_suite_passes_end_to_end(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.chdir(REPO_ROOT)

    code = main(["run-suite", "examples/suites/support/suite.toml"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.splitlines() == ["PASS  two-orders", "suite support: 1 passed, 0 failed"]
    assert sum(sys.modules["examples.async_support_agent"].REAL_CALLS.values()) == 0


# --- export -------------------------------------------------------------------

RUN_ID = "0b7c1a52-0000-4000-8000-00000000abcd"


def _stored_run(status: str = "completed") -> dict:
    """What GET /runs/{id} and GET /runs/{id}/events answer, as the real API shapes them."""
    run = {
        "id": RUN_ID,
        "project_id": PROJECT_ID,
        "agent_name": "support-agent",
        "agent_version": "v1",
        "input": {"message": "Wo ist meine Bestellung?"},
        "output": {"reply": "Grüße — bald da"},
        "metadata": None,
        "status": status,
        "started_at": "2026-09-18T10:00:00Z",
        "completed_at": "2026-09-18T10:00:01Z",
        "created_at": "2026-09-18T10:00:02Z",
        "replay_of_run_id": None,
    }
    events = [
        {"id": "e1", "run_id": RUN_ID, "sequence": 0, "event_type": "agent_start",
         "call_id": None, "tool_name": None, "arguments": None, "response": None,
         "duration_ms": None, "created_at": "2026-09-18T10:00:02Z"},
        {"id": "e2", "run_id": RUN_ID, "sequence": 1, "event_type": "tool_call",
         "call_id": "c1", "tool_name": "get_order", "arguments": {"order_id": "A-1"},
         "response": None, "duration_ms": None, "created_at": "2026-09-18T10:00:02Z"},
        {"id": "e3", "run_id": RUN_ID, "sequence": 2, "event_type": "tool_response",
         "call_id": "c1", "tool_name": "get_order", "arguments": None,
         "response": {"status": "shipped"}, "duration_ms": 5,
         "created_at": "2026-09-18T10:00:02Z"},
    ]
    return {"run": run, "events": events}


def _serve(api, status: str = "completed") -> dict:
    stored = _stored_run(status)
    api.routes[f"/api/v1/runs/{RUN_ID}"] = (200, stored["run"])
    api.routes[f"/api/v1/runs/{RUN_ID}/events"] = (200, stored["events"])
    return stored


def test_export_writes_the_run_and_its_events_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "recordings" / "order-lookup.json"
    with fake_api() as api:
        monkeypatch.setenv("AGENTTRACE_API_URL", api.url)
        stored = _serve(api)

        code = main(["export", RUN_ID, "-o", str(target)])

    assert code == 0
    expected = {**stored["run"], "events": stored["events"]}
    text = target.read_text(encoding="utf-8")
    assert text == json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert "Grüße" in text
    out = capsys.readouterr().out
    assert "[[cases]]" in out
    assert 'name = "order-lookup"' in out
    assert 'recording = "recordings/order-lookup.json"' in out


def test_an_exported_file_reads_back_as_the_same_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "run.json"
    with fake_api() as api:
        monkeypatch.setenv("AGENTTRACE_API_URL", api.url)
        _serve(api)
        assert main(["export", RUN_ID, "-o", str(target)]) == 0
        fetched = Recording.from_api_sync(RUN_ID, TracerConfig(api_url=api.url))

    from_file = Recording.from_payload(json.loads(target.read_text(encoding="utf-8")))

    assert from_file == fetched
    assert from_file.tool_calls[0].response == {"status": "shipped"}


def test_export_refuses_to_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "run.json"
    target.write_text("the reviewed fixture\n")
    with fake_api() as api:
        monkeypatch.setenv("AGENTTRACE_API_URL", api.url)
        _serve(api)

        refused = main(["export", RUN_ID, "-o", str(target)])
        untouched = target.read_text()
        requests_before_force = list(api.gets)
        forced = main(["export", RUN_ID, "-o", str(target), "--force"])

    assert refused == 2
    assert untouched == "the reviewed fixture\n"
    assert requests_before_force == []  # refused before asking the API anything
    assert "--force" in capsys.readouterr().err
    assert forced == 0
    assert json.loads(target.read_text())["id"] == RUN_ID


def test_export_refuses_a_run_that_is_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "run.json"
    with fake_api() as api:
        monkeypatch.setenv("AGENTTRACE_API_URL", api.url)
        _serve(api, status="running")

        code = main(["export", RUN_ID, "-o", str(target)])

    assert code == 2
    assert not target.exists()
    assert "still running" in capsys.readouterr().err


def test_export_of_an_unknown_run_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "run.json"
    with fake_api() as api:
        monkeypatch.setenv("AGENTTRACE_API_URL", api.url)

        code = main(["export", RUN_ID, "-o", str(target)])

    assert code == 2
    assert not target.exists()
    assert f"run {RUN_ID} not found" in capsys.readouterr().err


def test_export_with_the_api_down_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("AGENTTRACE_API_URL", f"http://127.0.0.1:{closed_port()}")

    code = main(["export", RUN_ID, "-o", str(tmp_path / "run.json")])

    assert code == 2
    assert "could not fetch run" in capsys.readouterr().err
