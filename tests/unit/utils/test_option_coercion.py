"""Tests for the shared typed-coercion helpers for blind-``setattr`` YAML
handler options (Plan 00311 Task 1.5, R6).

Extracted from three independent hand-rolled coercions that had drifted from
each other despite guarding the identical shape of input --
``dispatch_declaration._is_strict()`` (bool), ``bash_safe_mode._threshold()``
and ``subagent_report_size_blocker._threshold()`` (both int, but only the
latter parsed a numeric STRING before this extraction). Both directions were
already fail-safe (a malformed value degrades to the caller's default,
never raises), so this is a maintenance-cost fix, not a correctness one --
these tests pin the UNIFIED behaviour going forward.
"""

from __future__ import annotations

from claude_code_hooks_daemon.utils.option_coercion import (
    coerce_bool_option,
    coerce_int_option,
)


class TestCoerceBoolOption:
    def test_real_true_is_used_as_is(self) -> None:
        assert coerce_bool_option(True, default=False) is True

    def test_real_false_is_used_as_is(self) -> None:
        assert coerce_bool_option(False, default=True) is False

    def test_string_true_case_insensitive(self) -> None:
        assert coerce_bool_option("true", default=False) is True
        assert coerce_bool_option("True", default=False) is True
        assert coerce_bool_option("  TRUE  ", default=False) is True

    def test_string_false_case_insensitive(self) -> None:
        assert coerce_bool_option("false", default=True) is False
        assert coerce_bool_option("False", default=True) is False
        assert coerce_bool_option("  FALSE  ", default=True) is False

    def test_unrecognised_string_degrades_to_default(self) -> None:
        """`strict: yes` / `strict: 1` are plausible YAML spellings of "on"
        that the original ``_is_strict()`` silently read as False regardless
        of the caller's own default -- the shared helper degrades to the
        CALLER'S default instead, which is the same outcome for a False
        default and the more honest one for a True default."""
        assert coerce_bool_option("yes", default=False) is False
        assert coerce_bool_option("yes", default=True) is True
        assert coerce_bool_option("1", default=False) is False

    def test_non_bool_non_string_degrades_to_default(self) -> None:
        assert coerce_bool_option(1, default=False) is False
        assert coerce_bool_option(None, default=True) is True
        assert coerce_bool_option(["x"], default=False) is False


class TestCoerceIntOption:
    def test_real_positive_int_is_used_as_is(self) -> None:
        assert coerce_int_option(5, default=1) == 5

    def test_bool_is_never_treated_as_an_int(self) -> None:
        """``bool`` is an ``int`` subclass in Python -- ``True == 1`` must
        not silently pass through as a configured value."""
        assert coerce_int_option(True, default=7) == 7
        assert coerce_int_option(False, default=7) == 7

    def test_zero_and_negative_int_fall_back_to_default(self) -> None:
        assert coerce_int_option(0, default=3) == 3
        assert coerce_int_option(-5, default=3) == 3

    def test_numeric_string_is_parsed(self) -> None:
        assert coerce_int_option("10", default=1) == 10
        assert coerce_int_option("  10  ", default=1) == 10

    def test_non_numeric_string_falls_back_to_default(self) -> None:
        assert coerce_int_option("soon", default=1) == 1
        assert coerce_int_option("not-a-number", default=4000) == 4000

    def test_zero_or_negative_numeric_string_falls_back_to_default(self) -> None:
        assert coerce_int_option("0", default=3) == 3
        assert coerce_int_option("-1", default=3) == 3

    def test_non_int_non_string_falls_back_to_default(self) -> None:
        assert coerce_int_option(None, default=1) == 1
        assert coerce_int_option([1], default=1) == 1
        assert coerce_int_option(3.5, default=1) == 1

    def test_custom_minimum_is_honoured(self) -> None:
        assert coerce_int_option(0, default=5, minimum=0) == 0
        assert coerce_int_option("-1", default=5, minimum=-5) == -1
