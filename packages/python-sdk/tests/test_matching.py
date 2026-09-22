"""Tests for the pure matching functions. No tracer, no session, no I/O."""

from __future__ import annotations

from agenttrace.matching import (
    TIER_EXACT,
    TIER_NORMALIZED,
    canonical,
    find_match,
    fingerprint,
    normalize,
)


def _recorded(*calls: tuple[str, dict]) -> list:
    return [fingerprint(name, arguments) for name, arguments in calls]


def test_identical_arguments_match_exactly() -> None:
    recorded = _recorded(("get_order", {"order_id": "A-1"}))

    assert find_match(fingerprint("get_order", {"order_id": "A-1"}), recorded, set()) == (
        0,
        TIER_EXACT,
    )


def test_key_order_does_not_matter_for_an_exact_match() -> None:
    recorded = _recorded(("search", {"q": "shoes", "limit": 5}))

    assert find_match(fingerprint("search", {"limit": 5, "q": "shoes"}), recorded, set()) == (
        0,
        TIER_EXACT,
    )


def test_exact_beats_normalized_even_when_the_normalized_candidate_is_earlier() -> None:
    recorded = _recorded(
        ("get_order", {"order_id": " A-1 "}),  # only a normalized match
        ("get_order", {"order_id": "A-1"}),  # the exact match
    )

    assert find_match(fingerprint("get_order", {"order_id": "A-1"}), recorded, set()) == (
        1,
        TIER_EXACT,
    )


def test_falls_back_to_normalized_when_nothing_is_exact() -> None:
    recorded = _recorded(("get_order", {"order_id": "A-1"}))

    assert find_match(fingerprint("get_order", {"order_id": "A-1 "}), recorded, set()) == (
        0,
        TIER_NORMALIZED,
    )


def test_normalize_strips_surrounding_whitespace_only() -> None:
    assert normalize("  A-1\n") == "A-1"
    assert normalize("New  York") == "New  York"


def test_normalize_turns_integral_floats_into_ints() -> None:
    assert normalize(2.0) == 2 and isinstance(normalize(2.0), int)
    assert normalize(2.5) == 2.5
    # bool is an int subclass, not a float; it must survive untouched
    assert normalize(True) is True
    assert canonical(normalize({"n": 3.0})) == canonical({"n": 3})


def test_normalize_drops_keys_whose_value_is_none() -> None:
    assert normalize({"q": "x", "limit": None}) == {"q": "x"}
    assert normalize({"outer": {"inner": None, "keep": 1}}) == {"outer": {"keep": 1}}


def test_normalize_keeps_none_inside_lists_and_list_order() -> None:
    assert normalize([None, " b ", "a"]) == [None, "b", "a"]


def test_normalize_recurses_through_nested_structures() -> None:
    assert normalize({"items": [{"id": " x ", "qty": 1.0, "note": None}]}) == {
        "items": [{"id": "x", "qty": 1}]
    }


def test_each_normalize_rule_produces_a_normalized_match() -> None:
    recorded = _recorded(("search", {"q": "shoes", "limit": 5}))

    for live in (
        {"q": " shoes", "limit": 5},
        {"q": "shoes", "limit": 5.0},
        {"q": "shoes", "limit": 5, "page": None},
    ):
        assert find_match(fingerprint("search", live), recorded, set()) == (0, TIER_NORMALIZED)


def test_case_is_not_normalized() -> None:
    recorded = _recorded(("get_order", {"order_id": "A-1"}))

    assert normalize("A-1") != normalize("a-1")
    assert find_match(fingerprint("get_order", {"order_id": "a-1"}), recorded, set()) is None


def test_list_order_is_significant() -> None:
    recorded = _recorded(("rank", {"ids": ["a", "b"]}))

    assert find_match(fingerprint("rank", {"ids": ["b", "a"]}), recorded, set()) is None


def test_consumed_calls_are_skipped() -> None:
    recorded = _recorded(("poll", {"job": 1}), ("poll", {"job": 1}))

    assert find_match(fingerprint("poll", {"job": 1}), recorded, {0}) == (1, TIER_EXACT)
    assert find_match(fingerprint("poll", {"job": 1}), recorded, {0, 1}) is None


def test_lowest_sequence_wins_among_equal_candidates() -> None:
    recorded = _recorded(("poll", {"job": 1}), ("poll", {"job": 1}), ("poll", {"job": 1}))

    assert find_match(fingerprint("poll", {"job": 1}), recorded, set()) == (0, TIER_EXACT)
    assert find_match(fingerprint("poll", {"job": 1}), recorded, {0}) == (1, TIER_EXACT)


def test_tool_name_must_match() -> None:
    recorded = _recorded(("get_customer", {"id": "A-1"}))

    assert find_match(fingerprint("get_order", {"id": "A-1"}), recorded, set()) is None


def test_live_arguments_are_snapshotted_like_recorded_ones() -> None:
    """A tuple is recorded as a JSON list; the live call must compare the same way."""
    recorded = _recorded(("lines", {"ids": ["a", "b"]}))

    assert find_match(fingerprint("lines", {"ids": ("a", "b")}), recorded, set()) == (
        0,
        TIER_EXACT,
    )
