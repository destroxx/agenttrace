"""Tests for comparison: a recording and its replay turned into a verdict."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import Any

import pytest

from agenttrace import (
    AgentTracer,
    ComparisonPolicy,
    ComparisonReport,
    Recording,
    ReplayResult,
    ToolCallMatch,
    TracerConfig,
    UnusedRecordedCall,
    compare,
)
from agenttrace.comparison import (
    CHANGE_ADDED,
    CHANGE_LENGTH,
    CHANGE_REMOVED,
    CHANGE_TEXT,
    CHANGE_TYPE,
    CHANGE_VALUE,
    Difference,
    diff_json,
)
from agenttrace.replay import ReplaySummary

# --- helpers ------------------------------------------------------------------


def _codes(report: ComparisonReport) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in report.findings]


def _booking_tools(tracer: AgentTracer) -> dict[str, Any]:
    @tracer.tool
    async def check_availability(flight: str) -> bool:
        return True

    @tracer.tool
    async def confirm_price(flight: str, seats: int) -> int:
        return 420

    @tracer.tool
    async def book(flight: str, seats: int) -> str:
        return "BK-1"

    return {"check": check_availability, "price": confirm_price, "book": book}


def _booking_agent(tracer: AgentTracer, tools: dict[str, Any], **variant: Any):
    """Checks, prices, then books. `variant` bends one thing at a time."""

    async def agent(agent_input: dict) -> str:
        async with tracer.trace("booking", input=agent_input) as trace:
            flight = variant.get("flight", agent_input["flight"])
            seats = variant.get("seats", 2)
            if variant.get("book_first"):
                ref = await tools["book"](flight, seats)
                await tools["check"](flight)
                await tools["price"](flight, seats)
            else:
                await tools["check"](flight)
                if not variant.get("skip_price"):
                    await tools["price"](flight, seats)
                ref = await tools["book"](flight, seats)
            if variant.get("fail"):
                raise RuntimeError("card declined")
            trace.set_output(variant.get("output", {"reference": ref, "seats": 2}))
        return ref

    return agent


def _replay(**variant: Any) -> tuple[Recording, ReplayResult]:
    """Record the booking agent unchanged, then replay the variant against it."""
    tracer = AgentTracer(TracerConfig())
    tools = _booking_tools(tracer)
    asyncio.run(_booking_agent(tracer, tools)({"flight": "LH-100"}))
    recording = Recording.from_trace(tracer.completed_traces[-1])
    result = asyncio.run(tracer.replay(recording, _booking_agent(tracer, tools, **variant)))
    return recording, result


def _outputs(recorded: dict | None, new: dict | None) -> tuple[Recording, ReplayResult]:
    """A recording and replay that agree on everything except their output."""
    recording = Recording(
        run_id="rec-1",
        agent_name="a",
        agent_version=None,
        input={},
        output=recorded,
        status="completed",
        tool_calls=(),
    )
    result = ReplayResult(
        recording_run_id="rec-1",
        trace=None,
        status="completed",
        output=new,
        return_value=None,
        error=None,
        matches=[],
        unused=[],
        summary=ReplaySummary(0, 0, 0, 0, 0, 0),
    )
    return recording, result


# --- tool calls -----------------------------------------------------------------


def test_identical_replay_passes_with_no_findings() -> None:
    recording, result = _replay()

    report = compare(recording, result)

    assert report.verdict == "pass" and report.passed
    assert report.findings == ()
    assert report.recording_run_id == recording.run_id
    assert result.trace is not None and report.replay_run_id == result.trace.id
    assert dict(report.counts["by_severity"]) == {"error": 0, "warning": 0, "info": 0}
    assert dict(report.counts["by_code"]) == {}


def test_skipped_step_is_a_missing_tool_call() -> None:
    recording, result = _replay(skip_price=True)

    report = compare(recording, result)

    assert report.verdict == "fail" and not report.passed
    assert _codes(report) == [("MISSING_TOOL_CALL", "error")]
    details = report.findings[0].details
    skipped = recording.tool_calls[1]
    assert details["tool_name"] == "confirm_price"
    assert details["recorded_call_id"] == skipped.call_id
    assert details["recorded_sequence"] == skipped.sequence
    assert details["recorded_arguments"] == {"flight": "LH-100", "seats": 2}


def test_changed_call_is_unexpected_and_leaves_its_recording_missing() -> None:
    recording, result = _replay(seats=3)

    report = compare(recording, result)

    assert report.verdict == "fail"
    codes = [code for code, _ in _codes(report)]
    assert codes.count("UNEXPECTED_TOOL_CALL") >= 1
    unexpected = next(f for f in report.findings if f.code == "UNEXPECTED_TOOL_CALL")
    assert unexpected.severity == "error"
    assert unexpected.details["tool_name"] == "confirm_price"
    assert unexpected.details["new_arguments"] == {"flight": "LH-100", "seats": 3}
    assert "MISSING_TOOL_CALL" in codes


def test_normalized_match_is_a_warning_and_still_passes() -> None:
    recording, result = _replay(flight="  LH-100 ")

    report = compare(recording, result)

    assert report.passed
    assert {code for code, _ in _codes(report)} == {"ARGUMENTS_NORMALIZED"}
    assert all(severity == "warning" for _, severity in _codes(report))
    first = report.findings[0]
    assert first.details["tool_name"] == "check_availability"
    assert first.details["recorded_arguments"] == {"flight": "LH-100"}
    assert first.details["new_arguments"] == {"flight": "  LH-100 "}
    assert first.details["paths"] == ["flight"]


def test_reordered_calls_report_the_inversion_not_every_call() -> None:
    recording, result = _replay(book_first=True)

    report = compare(recording, result)

    assert report.passed
    assert _codes(report) == [("TOOL_ORDER_CHANGED", "warning")]
    details = report.findings[0].details
    assert details["tool_name"] == "check_availability"
    assert details["after_tool_name"] == "book"
    assert details["recorded_sequence"] < details["after_recorded_sequence"]


def test_same_order_reports_no_order_finding() -> None:
    recording, result = _replay()
    assert [m.recorded_sequence for m in result.matches] == sorted(
        m.recorded_sequence for m in result.matches
    )
    assert not any(f.code == "TOOL_ORDER_CHANGED" for f in compare(recording, result).findings)


def test_order_can_be_raised_to_an_error() -> None:
    recording, result = _replay(book_first=True)

    report = compare(
        recording, result, ComparisonPolicy(severity_overrides={"TOOL_ORDER_CHANGED": "error"})
    )

    assert report.verdict == "fail"
    assert _codes(report) == [("TOOL_ORDER_CHANGED", "error")]


# --- run status -----------------------------------------------------------------


def test_agent_error_and_status_change_both_fail() -> None:
    recording, result = _replay(fail=True)

    report = compare(recording, result)

    assert report.verdict == "fail"
    assert _codes(report) == [
        ("AGENT_ERROR", "error"),
        ("STATUS_CHANGED", "error"),
        ("OUTPUT_MISSING", "error"),
    ]
    assert report.findings[0].details == {"type": "RuntimeError", "message": "card declined"}
    assert report.findings[1].details == {"recorded": "completed", "new": "failed"}


def test_status_change_alone_fails() -> None:
    recording, result = _outputs({"a": 1}, {"a": 1})
    result.status = "failed"

    report = compare(recording, result)

    assert _codes(report) == [("STATUS_CHANGED", "error")]


# --- output -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("recorded", "new", "path", "change"),
    [
        ({"a": 1}, {"a": 1, "b": 2}, "b", CHANGE_ADDED),
        ({"a": 1, "b": 2}, {"a": 1}, "b", CHANGE_REMOVED),
        ({"a": 1}, {"a": "1"}, "a", CHANGE_TYPE),
        ({"a": 1}, {"a": 2}, "a", CHANGE_VALUE),
        ({"a": True}, {"a": False}, "a", CHANGE_VALUE),
        ({"a": [1, 2]}, {"a": [1, 2, 3]}, "a", CHANGE_LENGTH),
    ],
)
def test_structural_output_changes_fail(recorded: dict, new: dict, path: str, change: str) -> None:
    report = compare(*_outputs(recorded, new))

    assert report.verdict == "fail"
    assert _codes(report) == [("OUTPUT_STRUCTURE_CHANGED", "error")]
    assert report.findings[0].details["path"] == path
    assert report.findings[0].details["change"] == change


def test_reworded_text_is_a_warning_by_default() -> None:
    report = compare(*_outputs({"reply": "It arrives tomorrow."}, {"reply": "Due tomorrow."}))

    assert report.passed
    assert _codes(report) == [("OUTPUT_TEXT_CHANGED", "warning")]
    assert report.findings[0].details == {
        "path": "reply",
        "change": CHANGE_TEXT,
        "recorded": "It arrives tomorrow.",
        "new": "Due tomorrow.",
    }


def test_reworded_text_fails_when_the_policy_raises_it() -> None:
    policy = ComparisonPolicy(severity_overrides={"OUTPUT_TEXT_CHANGED": "error"})

    report = compare(*_outputs({"reply": "a"}, {"reply": "b"}), policy)

    assert report.verdict == "fail"
    assert _codes(report) == [("OUTPUT_TEXT_CHANGED", "error")]


@pytest.mark.parametrize(
    ("recorded", "new"),
    [
        ({"reply": "hello"}, {"reply": "  hello\n"}),
        ({"total": 2}, {"total": 2.0}),
        ({"items": [{"qty": 1.0}]}, {"items": [{"qty": 1}]}),
        ({"a": 1}, {"a": 1, "note": None}),
    ],
)
def test_normalization_only_differences_are_not_reported(recorded: dict, new: dict) -> None:
    report = compare(*_outputs(recorded, new))

    assert report.passed and report.findings == ()


def test_ignored_paths_become_info_and_pass() -> None:
    recorded = {
        "timestamp": "2026-01-01T00:00:00Z",
        "reply": {"text": "ok", "generated_at": 1},
        "items": [{"id": "x1", "qty": 1}, {"id": "x2", "qty": 2}],
    }
    new = {
        "timestamp": "2026-09-23T10:00:00Z",
        "reply": {"text": "ok", "generated_at": 2},
        "items": [{"id": "y1", "qty": 1}, {"id": "y2", "qty": 2}],
    }
    policy = ComparisonPolicy(ignore_paths=("timestamp", "reply.generated_at", "items.*.id"))

    report = compare(*_outputs(recorded, new), policy)

    assert report.passed
    assert [(f.details["path"], f.severity) for f in report.findings] == [
        ("items.0.id", "info"),
        ("items.1.id", "info"),
        ("reply.generated_at", "info"),
        ("timestamp", "info"),
    ]
    assert all(f.details["ignored"] is True for f in report.findings)
    assert dict(report.counts["by_severity"]) == {"error": 0, "warning": 0, "info": 4}


def test_ignore_paths_cover_descendants_but_not_siblings() -> None:
    policy = ComparisonPolicy(ignore_paths=["meta", "items.*.id"])

    report = compare(
        *_outputs(
            {"meta": {"a": 1}, "items": [{"id": 1, "qty": 1}]},
            {"meta": {"a": 2, "b": 3}, "items": [{"id": 2, "qty": 5}]},
        ),
        policy,
    )

    assert [(f.details["path"], f.severity) for f in report.findings] == [
        ("items.0.qty", "error"),
        ("items.0.id", "info"),
        ("meta.a", "info"),
        ("meta.b", "info"),
    ]
    assert report.verdict == "fail"


def test_star_matches_list_indexes_only() -> None:
    policy = ComparisonPolicy(ignore_paths=("*.id",))

    report = compare(*_outputs({"user": {"id": 1}}, {"user": {"id": 2}}), policy)

    assert _codes(report) == [("OUTPUT_STRUCTURE_CHANGED", "error")]


@pytest.mark.parametrize(
    ("recorded", "new", "which"),
    [({"a": 1}, None, "the replay"), (None, {"a": 1}, "the recording")],
)
def test_output_on_one_side_only_is_missing(recorded: Any, new: Any, which: str) -> None:
    report = compare(*_outputs(recorded, new))

    assert _codes(report) == [("OUTPUT_MISSING", "error")]
    assert report.findings[0].message == f"{which} has no output"


def test_no_output_on_either_side_is_fine() -> None:
    assert compare(*_outputs(None, None)).findings == ()


# --- policy -------------------------------------------------------------------


def test_policy_rejects_unknown_codes_and_severities() -> None:
    with pytest.raises(ValueError, match="unknown finding code"):
        ComparisonPolicy(severity_overrides={"OUTPUT_CHANGED": "error"})
    with pytest.raises(ValueError, match="unknown severity"):
        ComparisonPolicy(severity_overrides={"OUTPUT_TEXT_CHANGED": "fatal"})
    with pytest.raises(TypeError, match="not one string"):
        ComparisonPolicy(ignore_paths="timestamp")  # type: ignore[arg-type]


def test_policy_is_detached_from_the_callers_containers() -> None:
    overrides = {"OUTPUT_TEXT_CHANGED": "error"}
    paths = ["timestamp"]
    policy = ComparisonPolicy(severity_overrides=overrides, ignore_paths=paths)  # type: ignore[arg-type]
    overrides["OUTPUT_TEXT_CHANGED"] = "info"
    paths.append("reply")

    assert policy.severity_of("OUTPUT_TEXT_CHANGED") == "error"
    assert policy.ignore_paths == ("timestamp",)


def test_a_code_lowered_to_info_no_longer_fails() -> None:
    recording, result = _replay(skip_price=True)

    report = compare(
        recording, result, ComparisonPolicy(severity_overrides={"MISSING_TOOL_CALL": "info"})
    )

    assert report.passed
    assert _codes(report) == [("MISSING_TOOL_CALL", "info")]


# --- the report ---------------------------------------------------------------


def test_same_pair_compared_twice_gives_the_same_report() -> None:
    recording, result = _replay(fail=True, seats=3)

    first, second = compare(recording, result), compare(recording, result)

    assert first.to_dict() == second.to_dict()
    assert json.dumps(first.to_dict()) == json.dumps(second.to_dict())
    assert first.format() == second.format()


def test_to_dict_is_json_serialisable_with_a_stable_shape() -> None:
    recording, result = _replay(fail=True, seats=3, flight=" LH-100")

    data = compare(recording, result).to_dict()

    assert json.loads(json.dumps(data)) == data
    assert list(data) == ["verdict", "recording_run_id", "replay_run_id", "counts", "findings"]
    assert list(data["counts"]) == ["by_severity", "by_code"]
    assert list(data["counts"]["by_severity"]) == ["error", "warning", "info"]
    assert all(list(f) == ["code", "severity", "message", "details"] for f in data["findings"])


def test_to_dict_does_not_share_state_with_the_report() -> None:
    report = compare(*_outputs({"a": [1]}, {"a": [1, 2]}))

    data = report.to_dict()
    data["findings"][0]["details"]["recorded"] = "tampered"

    assert report.findings[0].details["recorded"] == 1


def test_findings_are_ordered_errors_first_then_by_sequence_then_path() -> None:
    recording, result = _replay(skip_price=True, flight=" LH-100", output={"b": 1, "a": "x"})
    recording = dataclasses.replace(recording, output={"a": "y", "b": 2})

    report = compare(recording, result)

    assert _codes(report) == [
        ("MISSING_TOOL_CALL", "error"),
        ("OUTPUT_STRUCTURE_CHANGED", "error"),
        ("ARGUMENTS_NORMALIZED", "warning"),
        ("ARGUMENTS_NORMALIZED", "warning"),
        ("OUTPUT_TEXT_CHANGED", "warning"),
    ]
    normalized = [f.details["recorded_sequence"] for f in report.findings[2:4]]
    assert normalized == sorted(normalized)


def test_finding_order_does_not_depend_on_the_order_calls_happened() -> None:
    """The same facts, listed in a different order, give an identical report."""
    recording = Recording.from_payload(
        {
            "id": "rec-1",
            "status": "completed",
            "events": [
                {"sequence": i, "event_type": "tool_call", "call_id": f"c{i}",
                 "tool_name": "t", "arguments": {"n": i}}
                for i in range(4)
            ],
        }
    )

    def result(order: list[int]) -> ReplayResult:
        matches = [
            ToolCallMatch("t", "normalized", f"n{i}", {"n": float(i)}, f"c{i}", {"n": i}, i)
            for i in order
        ] + [ToolCallMatch("x", "unmatched", f"u{i}", {"k": i}) for i in order]
        unused = [UnusedRecordedCall("t", f"c{i}", {"n": i}, i) for i in order]
        return ReplayResult("rec-1", None, "completed", None, None, None, matches, unused,
                            ReplaySummary(0, 0, 0, 0, 0, 0))

    forward = compare(recording, result([0, 1, 2, 3]))
    backward = compare(recording, result([3, 2, 1, 0]))

    strip = [(f.code, f.message) for f in forward.findings if f.code != "TOOL_ORDER_CHANGED"]
    assert strip == [
        (f.code, f.message) for f in backward.findings if f.code != "TOOL_ORDER_CHANGED"
    ]
    assert [f.code for f in backward.findings].count("TOOL_ORDER_CHANGED") == 3


def test_format_is_a_verdict_line_then_one_line_per_finding() -> None:
    recording, result = _replay(skip_price=True)

    text = compare(recording, result).format()

    lines = text.splitlines()
    assert lines[0].startswith("FAIL  1 error, 0 warnings, 0 info")
    assert len(lines) == 2
    assert "MISSING_TOOL_CALL" in lines[1] and "confirm_price" in lines[1]
    assert "\x1b" not in text


def test_long_text_changes_show_where_the_wording_differs() -> None:
    shared = "Your order has shipped and will arrive " * 3
    report = compare(*_outputs({"m": shared + "tomorrow."}, {"m": shared + "on Friday."}))

    message = report.findings[0].message
    assert "tomorrow." in message and "on Friday." in message


# --- entry point --------------------------------------------------------------


def test_replay_and_compare_is_replay_then_compare() -> None:
    tracer = AgentTracer(TracerConfig())
    tools = _booking_tools(tracer)
    asyncio.run(_booking_agent(tracer, tools)({"flight": "LH-100"}))
    recording = Recording.from_trace(tracer.completed_traces[-1])
    policy = ComparisonPolicy(severity_overrides={"MISSING_TOOL_CALL": "warning"})

    result, report = asyncio.run(
        tracer.replay_and_compare(
            recording,
            _booking_agent(tracer, tools, skip_price=True),
            agent_version="v2",
            policy=policy,
        )
    )

    assert result.trace is not None and result.trace.agent_version == "v2"
    assert report.passed
    assert _codes(report) == [("MISSING_TOOL_CALL", "warning")]
    assert report.to_dict() == compare(recording, result, policy).to_dict()


# --- JSON diff ----------------------------------------------------------------


def test_diff_of_equal_values_is_empty() -> None:
    value = {"a": [1, {"b": "c"}], "d": None, "e": True}
    assert diff_json(value, json.loads(json.dumps(value))) == []


def test_diff_reports_dot_paths_in_sorted_key_order() -> None:
    assert diff_json({"z": 1, "a": {"b": [1, 2]}}, {"z": 2, "a": {"b": [1, 3]}}) == [
        Difference(("a", "b", 1), CHANGE_VALUE, 2, 3),
        Difference(("z",), CHANGE_VALUE, 1, 2),
    ]


def test_diff_of_lists_reports_length_once_and_compares_shared_indexes() -> None:
    assert diff_json([1, 2, 3], ["1", 2]) == [
        Difference((), CHANGE_LENGTH, 3, 2),
        Difference((0,), CHANGE_TYPE, 1, "1"),
    ]


def test_diff_types() -> None:
    assert diff_json({"a": 1}, {"a": True}) == [Difference(("a",), CHANGE_TYPE, 1, True)]
    assert diff_json({"a": None}, {"a": 0}) == [Difference(("a",), CHANGE_TYPE, None, 0)]
    assert diff_json({"a": {}}, {"a": []}) == [Difference(("a",), CHANGE_TYPE, {}, [])]
    assert diff_json({"a": 1}, {"a": 1.5}) == [Difference(("a",), CHANGE_VALUE, 1, 1.5)]
    assert diff_json("x", "y") == [Difference((), CHANGE_TEXT, "x", "y")]


def test_diff_added_and_removed_keys() -> None:
    assert diff_json({"a": 1}, {"b": 1}) == [
        Difference(("a",), CHANGE_REMOVED, recorded=1),
        Difference(("b",), CHANGE_ADDED, new=1),
    ]
