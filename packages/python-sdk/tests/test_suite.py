"""Tests for loading a regression suite: validation happens before anything runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenttrace import ComparisonPolicy, SuiteError, load_suite
from agenttrace.suite import format_recording, merge_policy

RECORDING = {
    "id": "0b7c1a52-0000-4000-8000-000000000001",
    "agent_name": "agent",
    "input": {"key": "a"},
    "output": {"value": "value-a"},
    "status": "completed",
    "events": [],
}

VALID = """
name = "support"
agent = "my_agent:run"

[policy]
severity_overrides = { TOOL_ORDER_CHANGED = "info" }
ignore_paths = ["generated_at"]

[[cases]]
name = "first"
recording = "recordings/first.json"

[[cases]]
name = "second"
recording = "recordings/second.json"
[cases.policy]
ignore_paths = ["reply.id"]
severity_overrides = { TOOL_ORDER_CHANGED = "error", OUTPUT_TEXT_CHANGED = "error" }
"""


def _write(tmp_path: Path, suite: str, recordings: dict[str, str] | None = None) -> Path:
    """Write suite.toml, plus recordings (name -> file text; valid ones by default)."""
    folder = tmp_path / "recordings"
    folder.mkdir(exist_ok=True)
    if recordings is None:
        recordings = {name: format_recording(RECORDING) for name in ("first", "second")}
    for name, text in recordings.items():
        (folder / f"{name}.json").write_text(text, encoding="utf-8")
    path = tmp_path / "suite.toml"
    path.write_text(suite, encoding="utf-8")
    return path


def test_a_valid_suite_loads_with_its_recordings(tmp_path: Path) -> None:
    suite = load_suite(_write(tmp_path, VALID))

    assert suite.name == "support"
    assert suite.agent == "my_agent:run"
    assert [case.name for case in suite.cases] == ["first", "second"]
    first = suite.cases[0]
    assert first.recording_path == tmp_path / "recordings" / "first.json"
    assert first.recording.run_id == RECORDING["id"]
    assert first.recording.input == {"key": "a"}
    # a case without a policy of its own is judged by the suite's
    assert first.policy == suite.policy


def test_a_case_policy_extends_the_suites(tmp_path: Path) -> None:
    second = load_suite(_write(tmp_path, VALID)).cases[1]

    assert second.policy.ignore_paths == ("generated_at", "reply.id")
    assert dict(second.policy.severity_overrides) == {
        "TOOL_ORDER_CHANGED": "error",  # the case wins over the suite's "info"
        "OUTPUT_TEXT_CHANGED": "error",
    }


def test_merge_policy_is_a_union_of_paths_and_the_case_wins_per_code() -> None:
    suite = ComparisonPolicy(
        severity_overrides={"TOOL_ORDER_CHANGED": "info", "ARGUMENTS_NORMALIZED": "error"},
        ignore_paths=("a", "b"),
    )
    case = ComparisonPolicy(
        severity_overrides={"TOOL_ORDER_CHANGED": "error"}, ignore_paths=("b", "c")
    )

    merged = merge_policy(suite, case)

    assert merged.ignore_paths == ("a", "b", "c")
    assert dict(merged.severity_overrides) == {
        "TOOL_ORDER_CHANGED": "error",
        "ARGUMENTS_NORMALIZED": "error",
    }
    assert merge_policy(suite, None) is suite


def test_the_suite_file_path_resolves_recordings_relative_to_itself(tmp_path: Path) -> None:
    nested = tmp_path / "suites" / "support"
    nested.mkdir(parents=True)
    path = _write(nested, VALID)

    suite = load_suite(path)

    assert suite.cases[0].recording_path == nested / "recordings" / "first.json"


ONE_CASE = """
name = "s"
agent = "my_agent:run"
[[cases]]
name = "first"
recording = "recordings/first.json"
"""


@pytest.mark.parametrize(
    ("suite", "needle"),
    [
        pytest.param("name = [unclosed", "invalid TOML", id="parse-error"),
        pytest.param(ONE_CASE.replace('agent = "my_agent:run"\n', ""), "'agent' missing",
                     id="missing-agent"),
        pytest.param(ONE_CASE.replace('name = "s"\n', ""), "'name' missing", id="missing-name"),
        pytest.param('agnet = "x"\n' + ONE_CASE, "unknown suite key(s) agnet",
                     id="unknown-suite-key"),
        pytest.param(ONE_CASE.replace("my_agent:run", "my_agent.run"),
                     "agent must be 'module:function'", id="agent-without-colon"),
        pytest.param('name = "s"\nagent = "m:f"\n', "at least one [[cases]]", id="no-cases"),
        pytest.param(ONE_CASE + '[policy]\nignore = ["x"]\n', "unknown policy key(s) ignore",
                     id="unknown-policy-key"),
        pytest.param(ONE_CASE + '[policy]\nseverity_overrides = { NOT_A_CODE = "info" }\n',
                     "unknown finding code 'NOT_A_CODE'", id="invalid-suite-policy"),
        pytest.param(ONE_CASE + '[policy]\nignore_paths = "generated_at"\n',
                     "ignore_paths must be a list of strings", id="ignore-paths-string"),
    ],
)
def test_suite_level_errors_name_the_suite_file(tmp_path: Path, suite: str, needle: str) -> None:
    path = _write(tmp_path, suite)

    with pytest.raises(SuiteError) as caught:
        load_suite(path)

    assert str(path) in str(caught.value)
    assert needle in str(caught.value)
    assert caught.value.path == str(path)


def test_a_missing_suite_file_is_a_suite_error(tmp_path: Path) -> None:
    with pytest.raises(SuiteError) as caught:
        load_suite(tmp_path / "nope.toml")

    assert "nope.toml" in str(caught.value)
    assert "cannot read suite" in str(caught.value)


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        pytest.param('recordng = "x"\n', "unknown case key(s) recordng", id="unknown-case-key"),
        pytest.param('[cases.policy]\nseverity_overrides = { OUTPUT_TEXT_CHANGED = "fatal" }\n',
                     "unknown severity 'fatal'", id="invalid-case-policy"),
        pytest.param('[cases.policy]\nignored = ["x"]\n', "unknown policy key(s) ignored",
                     id="unknown-case-policy-key"),
    ],
)
def test_case_level_errors_name_the_file_and_the_case(
    tmp_path: Path, extra: str, needle: str
) -> None:
    path = _write(tmp_path, ONE_CASE + extra)

    with pytest.raises(SuiteError) as caught:
        load_suite(path)

    assert str(path) in str(caught.value)
    assert "case 'first'" in str(caught.value)
    assert caught.value.case == "first"
    assert needle in str(caught.value)


def test_duplicate_case_names_are_rejected(tmp_path: Path) -> None:
    again = '[[cases]]\nname = "first"\nrecording = "recordings/second.json"\n'
    path = _write(tmp_path, ONE_CASE + again)

    with pytest.raises(SuiteError) as caught:
        load_suite(path)

    assert "duplicate case name" in str(caught.value)
    assert caught.value.case == "first"


def test_a_case_without_a_recording_key_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, 'name = "s"\nagent = "m:f"\n[[cases]]\nname = "first"\n')

    with pytest.raises(SuiteError) as caught:
        load_suite(path)

    assert "'recording' missing" in str(caught.value)
    assert caught.value.case == "first"


@pytest.mark.parametrize(
    ("recordings", "needle"),
    [
        pytest.param({}, "cannot read recording", id="missing-file"),
        pytest.param({"first": "{not json"}, "not valid JSON", id="bad-json"),
        pytest.param({"first": "[1, 2]"}, "must be a JSON object", id="not-an-object"),
        pytest.param({"first": json.dumps({"events": []})}, "not a recording",
                     id="no-run-id"),
    ],
)
def test_recording_errors_name_the_recording_file_and_the_case(
    tmp_path: Path, recordings: dict[str, str], needle: str
) -> None:
    path = _write(tmp_path, ONE_CASE, recordings)

    with pytest.raises(SuiteError) as caught:
        load_suite(path)

    recording = tmp_path / "recordings" / "first.json"
    assert caught.value.path == str(recording)
    assert str(recording) in str(caught.value)
    assert caught.value.case == "first"
    assert needle in str(caught.value)


def test_nothing_is_returned_when_a_later_case_is_invalid(tmp_path: Path) -> None:
    """All or nothing: the first case being fine does not let the suite half-load."""
    path = _write(tmp_path, VALID, {"first": format_recording(RECORDING)})

    with pytest.raises(SuiteError) as caught:
        load_suite(path)

    assert caught.value.case == "second"


def test_format_recording_is_deterministic() -> None:
    payload = {"b": 1, "a": {"z": "Grüße", "y": [1, 2]}}

    text = format_recording(payload)

    assert text == format_recording(json.loads(text))
    assert text.endswith("}\n")
    assert text.index('"a"') < text.index('"b"')
    assert "Grüße" in text  # not \u-escaped
    assert '\n  "a": {\n    "y": [' in text
