"""Tests for semantic comparison: judging whether reworded output means the same.

`judge_report` is exercised with plain functions as judges. `ClaudeJudge` is
exercised against a fake Messages API on a loopback port -- a real HTTP
server, like `fake_api`, so the request the judge sends is the one the wire
sees. Nothing here calls Anthropic.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agenttrace import (
    AgentTracer,
    ClaudeJudge,
    ComparisonPolicy,
    ComparisonReport,
    JudgeError,
    Judgement,
    Recording,
    TracerConfig,
    compare,
    judge_report,
)
from agenttrace.cli import main
from agenttrace.errors import SuiteError
from agenttrace.semantic import SYSTEM_PROMPT
from agenttrace.suite import format_recording, load_suite
from agenttrace.transport import build_payload

# --- helpers ------------------------------------------------------------------


def _codes(report: ComparisonReport) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in report.findings]


def _report(recorded: dict, new: dict, *, skip_second_call: bool = False,
            policy: ComparisonPolicy | None = None) -> ComparisonReport:
    """A real `compare` report for an agent whose output went from `recorded` to `new`."""
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def lookup(key: str) -> str:
        return f"value-{key}"

    def agent(output: dict, calls: list[str]):
        def run(agent_input: dict) -> None:
            with tracer.trace("agent", input=agent_input) as trace:
                for call in calls:
                    lookup(call)
                trace.set_output(output)
        return run

    agent(recorded, ["a", "b"])({"q": 1})
    recording = Recording.from_trace(tracer.completed_traces[-1])
    replay_calls = ["a"] if skip_second_call else ["a", "b"]

    result = asyncio.run(tracer.replay(recording, agent(new, replay_calls)))
    return compare(recording, result, policy)


class Calls:
    """A judge that answers from a table and remembers what it was asked."""

    def __init__(self, equivalent: bool, reason: str = "because") -> None:
        self.equivalent = equivalent
        self.reason = reason
        self.asked: list[tuple[str, str, str]] = []

    def __call__(self, path: str, recorded: str, new: str) -> Judgement:
        self.asked.append((path, recorded, new))
        return Judgement(self.equivalent, self.reason)


# --- judge_report -------------------------------------------------------------


def test_equivalent_rewording_becomes_info_and_passes() -> None:
    report = _report({"reply": "Arriving tomorrow."}, {"reply": "Due tomorrow."})
    judge = Calls(equivalent=True, reason="Same delivery date, different verb.")

    judged = judge_report(report, judge)

    assert _codes(judged) == [("OUTPUT_TEXT_EQUIVALENT", "info")]
    assert judged.passed
    finding = judged.findings[0]
    assert finding.message == (
        "output.reply reworded, same meaning: Same delivery date, different verb."
    )
    assert finding.details["judge"] == {
        "name": "Calls",
        "equivalent": True,
        "reason": "Same delivery date, different verb.",
    }
    # what deterministically changed is kept next to the verdict
    assert finding.details["text_change"].startswith("output.reply text changed:")
    assert judge.asked == [("reply", "Arriving tomorrow.", "Due tomorrow.")]


def test_changed_meaning_becomes_an_error_and_fails() -> None:
    report = _report({"reply": "Arriving tomorrow."}, {"reply": "Arriving Friday."})

    judged = judge_report(report, Calls(equivalent=False, reason="The date moved."))

    assert _codes(judged) == [("OUTPUT_MEANING_CHANGED", "error")]
    assert not judged.passed
    assert judged.counts["by_code"] == {"OUTPUT_MEANING_CHANGED": 1}
    assert judged.counts["by_severity"]["error"] == 1
    assert judged.findings[0].message == "output.reply meaning changed: The date moved."


def test_report_without_wording_changes_is_not_sent_to_the_judge() -> None:
    report = _report({"reply": "same"}, {"reply": "same"}, skip_second_call=True)
    judge = Calls(equivalent=False)

    judged = judge_report(report, judge)

    assert judge.asked == []
    assert judged.to_dict() == report.to_dict()


def test_only_wording_changes_are_judged_and_errors_stay_first() -> None:
    report = _report(
        {"reply": "Arriving tomorrow.", "count": 1},
        {"reply": "Arriving Friday.", "count": 2},
        skip_second_call=True,
    )
    judge = Calls(equivalent=False)

    judged = judge_report(report, judge)

    assert len(judge.asked) == 1
    assert _codes(judged) == [
        ("MISSING_TOOL_CALL", "error"),
        ("OUTPUT_STRUCTURE_CHANGED", "error"),
        ("OUTPUT_MEANING_CHANGED", "error"),
    ]


def test_ignored_paths_are_not_judged() -> None:
    policy = ComparisonPolicy(ignore_paths=("reply",))
    report = _report({"reply": "a"}, {"reply": "b"}, policy=policy)
    judge = Calls(equivalent=False)

    judged = judge_report(report, judge, policy)

    assert judge.asked == []
    assert _codes(judged) == [("OUTPUT_TEXT_CHANGED", "info")]


def test_policy_overrides_apply_to_the_semantic_codes() -> None:
    policy = ComparisonPolicy(severity_overrides={"OUTPUT_MEANING_CHANGED": "warning"})
    report = _report({"reply": "a"}, {"reply": "b"}, policy=policy)

    judged = judge_report(report, Calls(equivalent=False), policy)

    assert _codes(judged) == [("OUTPUT_MEANING_CHANGED", "warning")]
    assert judged.passed


def test_the_same_change_in_two_places_is_judged_once() -> None:
    report = _report(
        {"items": [{"note": "Arriving tomorrow."}, {"note": "Arriving tomorrow."}]},
        {"items": [{"note": "Due tomorrow."}, {"note": "Due tomorrow."}]},
    )
    judge = Calls(equivalent=True)

    judged = judge_report(report, judge)

    assert len(judge.asked) == 1
    assert [f.details["path"] for f in judged.findings] == ["items.0.note", "items.1.note"]


def test_a_judge_that_returns_something_else_raises() -> None:
    report = _report({"reply": "a"}, {"reply": "b"})

    with pytest.raises(JudgeError, match="not a Judgement"):
        judge_report(report, lambda path, recorded, new: True)


def test_judged_report_is_json_serialisable() -> None:
    report = _report({"reply": "a"}, {"reply": "b"})

    judged = judge_report(report, Calls(equivalent=True))

    assert json.loads(json.dumps(judged.to_dict()))["findings"][0]["code"] == (
        "OUTPUT_TEXT_EQUIVALENT"
    )


def test_replay_and_compare_takes_a_judge() -> None:
    tracer = AgentTracer(TracerConfig())

    def agent(reply: str):
        def run(agent_input: dict) -> None:
            with tracer.trace("agent", input=agent_input) as trace:
                trace.set_output({"reply": reply})
        return run

    agent("Arriving tomorrow.")({})
    recording = Recording.from_trace(tracer.completed_traces[-1])

    _, report = asyncio.run(
        tracer.replay_and_compare(
            recording, agent("Due tomorrow."), judge=Calls(equivalent=True)
        )
    )

    assert _codes(report) == [("OUTPUT_TEXT_EQUIVALENT", "info")]


# --- ClaudeJudge, against a fake Messages API -------------------------------------


@dataclass
class FakeClaude:
    """Responses to hand out in order, and the requests that took them."""

    responses: list[tuple[int, Any, dict[str, str]]] = field(default_factory=list)
    requests: list[tuple[str, dict[str, str], Any]] = field(default_factory=list)
    url: str = ""


def _answer(equivalent: bool, reason: str = "fine", stop_reason: str = "end_turn") -> Any:
    text = json.dumps({"equivalent": equivalent, "reason": reason})
    return {
        "type": "message",
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
        "stop_reason": stop_reason,
    }


@contextmanager
def fake_claude(*responses: tuple[int, Any, dict[str, str]]) -> Iterator[FakeClaude]:
    state = FakeClaude(responses=list(responses))
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            with lock:
                state.requests.append(
                    (self.path, {k.lower(): v for k, v in self.headers.items()}, body)
                )
                status, payload, headers = state.responses.pop(0)
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    # A short poll keeps shutdown() from waiting out the default half second.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def _judge(url: str, **overrides: Any) -> ClaudeJudge:
    return ClaudeJudge(api_key="sk-test", api_url=url, timeout_seconds=5, **overrides)


def test_claude_judge_sends_a_structured_request_and_reads_the_verdict() -> None:
    with fake_claude((200, _answer(True, "Same date."), {})) as api:
        judgement = _judge(api.url)("reply", "Arriving tomorrow.", "Due tomorrow.")

    assert judgement == Judgement(equivalent=True, reason="Same date.")
    [(path, headers, body)] = api.requests
    assert path == "/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["system"] == SYSTEM_PROMPT
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["required"] == ["equivalent", "reason"]
    assert "temperature" not in body and "thinking" not in body
    content = body["messages"][0]["content"]
    assert "Field: output.reply" in content
    assert "<recorded>\nArriving tomorrow.\n</recorded>" in content
    assert "<new>\nDue tomorrow.\n</new>" in content


def test_a_model_without_server_fallbacks_is_sent_without_them() -> None:
    with fake_claude((200, _answer(False), {})) as api:
        _judge(api.url, model="claude-haiku-4-5", effort=None)("", "a", "b")

    [(_, headers, body)] = api.requests
    assert "fallbacks" not in body and "anthropic-beta" not in headers
    assert "effort" not in body["output_config"]
    assert "Field: the whole output" in body["messages"][0]["content"]


def test_rate_limits_are_retried_honouring_retry_after() -> None:
    with fake_claude(
        (429, {"error": {"message": "slow down"}}, {"retry-after": "0"}),
        (529, {"error": {"message": "overloaded"}}, {"retry-after": "0"}),
        (200, _answer(True), {}),
    ) as api:
        judgement = _judge(api.url)("reply", "a", "b")

    assert judgement.equivalent
    assert len(api.requests) == 3


def test_retries_give_up_with_the_last_status() -> None:
    busy = (529, {"error": {"message": "overloaded"}}, {"retry-after": "0"})
    with fake_claude(busy, busy) as api, pytest.raises(JudgeError) as caught:
        _judge(api.url, max_retries=1)("reply", "a", "b")

    assert caught.value.status == 529
    assert "overloaded" in str(caught.value)


def test_a_bad_request_is_not_retried() -> None:
    bad = (400, {"error": {"message": "bad model"}}, {})
    with fake_claude(bad) as api, pytest.raises(JudgeError, match="400: bad model") as caught:
        _judge(api.url)("reply", "a", "b")

    assert caught.value.status == 400
    assert len(api.requests) == 1


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_answer(True, stop_reason="refusal"), "declined"),
        (_answer(True, stop_reason="max_tokens"), "ran out of tokens"),
        ({"content": [], "stop_reason": "end_turn"}, "had no text"),
        ({"content": [{"type": "text", "text": "yes"}], "stop_reason": "end_turn"}, "not JSON"),
        (
            {"content": [{"type": "text", "text": '{"equivalent": "yes"}'}],
             "stop_reason": "end_turn"},
            "did not match the schema",
        ),
        (b"<html>", "not JSON"),
    ],
)
def test_unusable_answers_raise(response: Any, message: str) -> None:
    with fake_claude((200, response, {})) as api, pytest.raises(JudgeError, match=message):
        _judge(api.url)("reply", "a", "b")


def test_an_unreachable_api_raises_after_retrying() -> None:
    with fake_claude() as api:
        url = api.url
    # the server is gone; the port refuses connections
    with pytest.raises(JudgeError, match="could not reach"):
        _judge(url, max_retries=0)("reply", "a", "b")


def test_from_env_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(JudgeError, match="ANTHROPIC_API_KEY"):
        ClaudeJudge.from_env()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    with pytest.raises(JudgeError):
        ClaudeJudge.from_env()


def test_from_env_reads_the_key_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy.local/")

    judge = ClaudeJudge.from_env(model="claude-sonnet-5-5")

    assert (judge.api_key, judge.api_url, judge.model) == (
        "sk-env", "http://proxy.local", "claude-sonnet-5-5"
    )
    assert "sk-env" not in repr(judge)


# --- suites and run-suite -----------------------------------------------------

AGENT_MODULE = '''
from agenttrace import AgentTracer, TracerConfig

tracer = AgentTracer(TracerConfig())


def run(request: dict) -> str:
    with tracer.trace("agent", input=request) as trace:
        trace.set_output({"reply": "Due tomorrow."})
    return "ok"
'''


@pytest.fixture
def suite_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in ("AGENTTRACE_PROJECT_ID", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _semantic_suite(folder: Path, semantic: str = "[semantic]") -> str:
    """A suite whose one case was recorded as "Arriving tomorrow." and now says "Due tomorrow."."""
    module = f"agent_{uuid.uuid4().hex}"
    (folder / f"{module}.py").write_text(AGENT_MODULE, encoding="utf-8")
    tracer = AgentTracer(TracerConfig())
    with tracer.trace("agent", input={}) as trace:
        trace.set_output({"reply": "Arriving tomorrow."})
    (folder / "case.json").write_text(format_recording(build_payload(trace)))
    path = folder / "suite.toml"
    path.write_text(
        f'name = "demo"\nagent = "{module}:run"\n{semantic}\n'
        '[[cases]]\nname = "reply"\nrecording = "case.json"\n'
    )
    return str(path)


def test_suite_reads_its_semantic_table(suite_dir: Path) -> None:
    path = _semantic_suite(suite_dir, '[semantic]\nmodel = "claude-sonnet-5-5"\n')

    suite = load_suite(path)

    assert suite.semantic is not None
    assert (suite.semantic.model, suite.semantic.effort) == ("claude-sonnet-5-5", None)
    assert load_suite(_semantic_suite(suite_dir, "")).semantic is None


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('[semantic]\njudge = "x"\n', "unknown semantic key"),
        ("[semantic]\nmodel = 3\n", "semantic.model must be a non-empty string"),
        ('semantic = "on"\n', "semantic must be a table"),
    ],
)
def test_suite_rejects_a_bad_semantic_table(suite_dir: Path, table: str, message: str) -> None:
    with pytest.raises(SuiteError, match=message):
        load_suite(_semantic_suite(suite_dir, table))


def test_run_suite_without_a_key_exits_2_before_any_case(suite_dir: Path, capsys) -> None:
    code = main(["run-suite", _semantic_suite(suite_dir)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "ANTHROPIC_API_KEY" in captured.err and "--no-semantic" in captured.err


def test_no_semantic_runs_offline_with_the_wording_as_a_warning(suite_dir: Path, capsys) -> None:
    code = main(["run-suite", _semantic_suite(suite_dir), "--no-semantic"])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS  reply  1 warning",
        "suite demo: 1 passed, 0 failed",
    ]


def test_run_suite_judges_wording_and_fails_on_changed_meaning(
    suite_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    suite = _semantic_suite(suite_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with fake_claude((200, _answer(False, "The day changed."), {})) as api:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", api.url)
        code = main(["run-suite", suite])

    lines = capsys.readouterr().out.splitlines()
    assert code == 1
    assert lines[0] == "semantic comparison: judged by claude-opus-5-5"
    assert lines[1] == "FAIL  reply  1 error"
    assert "OUTPUT_MEANING_CHANGED" in lines[2] and "The day changed." in lines[2]


def test_run_suite_passes_an_equivalent_rewording(
    suite_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    suite = _semantic_suite(suite_dir, '[semantic]\neffort = "none"\nmodel = "claude-haiku-4-5"')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with fake_claude((200, _answer(True), {})) as api:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", api.url)
        code = main(["run-suite", suite])

    assert code == 0
    assert capsys.readouterr().out.splitlines()[1] == "PASS  reply"
    [(_, _, body)] = api.requests
    assert body["model"] == "claude-haiku-4-5" and "effort" not in body["output_config"]


def test_a_judge_failure_is_an_error_case_not_a_verdict(
    suite_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    suite = _semantic_suite(suite_dir)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with fake_claude((401, {"error": {"message": "invalid x-api-key"}}, {})) as api:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", api.url)
        code = main(["run-suite", suite])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.splitlines()[1] == "ERROR reply  could not judge"
    assert "invalid x-api-key" in captured.err
