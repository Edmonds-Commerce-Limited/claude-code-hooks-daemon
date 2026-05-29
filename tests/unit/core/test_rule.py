"""Tests for core/rule.py — Rule dataclass and RuleFormatter.

Phase 2 of Plan 00116: Rule model with formatter.

RED phase: these tests fail until Rule and RuleFormatter are implemented.

Design contract (Decision A/B/C/D from PLAN.md):
  - Rule is a frozen dataclass with slots
  - RuleFormatter renders table_row / terse / verbose from one Rule
  - All three outputs contain the rule_id and the blocked literal
"""

from __future__ import annotations

import dataclasses

import pytest

from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_rule() -> Rule:
    """A representative Rule for testing."""
    return Rule(
        rule_id="R-GIT-RESET-HARD",
        blocked="`git reset --hard`",
        why="Permanently destroys all uncommitted changes",
        fix="Ask the user to run manually, or use `git stash` first",
        verbose=(
            "git reset --hard PERMANENTLY DESTROYS all uncommitted changes with no recovery.\n\n"
            "Safe alternatives:\n"
            "  - git stash        (save changes, can recover later)\n"
            "  - git diff         (review changes first)\n"
            "  - git status       (see what would be affected)\n"
            "  - git commit       (save changes permanently first)\n\n"
            "Ask the user to run this manually if needed."
        ),
    )


@pytest.fixture()
def formatter() -> RuleFormatter:
    """A RuleFormatter instance."""
    return RuleFormatter()


# ---------------------------------------------------------------------------
# Rule dataclass tests
# ---------------------------------------------------------------------------


class TestRuleDataclass:
    """Rule is a frozen, slotted dataclass with correct field types."""

    def test_rule_instantiation(self, sample_rule: Rule) -> None:
        """Rule can be instantiated with all required fields."""
        assert sample_rule.rule_id == "R-GIT-RESET-HARD"

    def test_rule_is_frozen(self, sample_rule: Rule) -> None:
        """Rule is immutable (frozen dataclass)."""
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            setattr(sample_rule, "rule_id", "CHANGED")

    def test_rule_is_dataclass(self, sample_rule: Rule) -> None:
        """Rule is a dataclass."""
        assert dataclasses.is_dataclass(sample_rule)

    def test_rule_has_rule_id(self, sample_rule: Rule) -> None:
        """Rule has rule_id field."""
        assert hasattr(sample_rule, "rule_id")
        assert isinstance(sample_rule.rule_id, str)

    def test_rule_has_blocked(self, sample_rule: Rule) -> None:
        """Rule has blocked field (terse what-is-blocked)."""
        assert hasattr(sample_rule, "blocked")
        assert isinstance(sample_rule.blocked, str)

    def test_rule_has_why(self, sample_rule: Rule) -> None:
        """Rule has why field (one-line consequence)."""
        assert hasattr(sample_rule, "why")
        assert isinstance(sample_rule.why, str)

    def test_rule_has_fix(self, sample_rule: Rule) -> None:
        """Rule has fix field (one-line fix)."""
        assert hasattr(sample_rule, "fix")
        assert isinstance(sample_rule.fix, str)

    def test_rule_has_verbose(self, sample_rule: Rule) -> None:
        """Rule has verbose field (full rationale for first-fire block)."""
        assert hasattr(sample_rule, "verbose")
        assert isinstance(sample_rule.verbose, str)

    def test_rule_equality(self) -> None:
        """Two Rules with identical fields are equal."""
        r1 = Rule(
            rule_id="R-TEST",
            blocked="`test`",
            why="reason",
            fix="the fix",
            verbose="verbose detail",
        )
        r2 = Rule(
            rule_id="R-TEST",
            blocked="`test`",
            why="reason",
            fix="the fix",
            verbose="verbose detail",
        )
        assert r1 == r2

    def test_rule_inequality(self, sample_rule: Rule) -> None:
        """Two Rules with different rule_ids are not equal."""
        other = Rule(
            rule_id="R-DIFFERENT",
            blocked="`git reset --hard`",
            why="Permanently destroys all uncommitted changes",
            fix="Ask the user to run manually",
            verbose="detail",
        )
        assert sample_rule != other

    def test_rule_repr_contains_rule_id(self, sample_rule: Rule) -> None:
        """repr(rule) contains the rule_id for debugging."""
        assert "R-GIT-RESET-HARD" in repr(sample_rule)

    def test_rule_has_slots(self) -> None:
        """Rule uses __slots__ for memory efficiency."""
        assert hasattr(Rule, "__slots__")

    def test_rule_blocked_field_is_not_empty(self, sample_rule: Rule) -> None:
        """Rule.blocked is non-empty (it carries the load-bearing literal)."""
        assert len(sample_rule.blocked.strip()) > 0

    def test_rule_verbose_field_is_not_empty(self, sample_rule: Rule) -> None:
        """Rule.verbose is non-empty (carries teaching content for first fire)."""
        assert len(sample_rule.verbose.strip()) > 0


# ---------------------------------------------------------------------------
# RuleFormatter tests
# ---------------------------------------------------------------------------


class TestRuleFormatterTableRow:
    """RuleFormatter.table_row() produces a valid markdown table row."""

    def test_table_row_returns_string(self, formatter: RuleFormatter, sample_rule: Rule) -> None:
        """table_row() returns a str."""
        row = formatter.table_row(sample_rule)
        assert isinstance(row, str)

    def test_table_row_contains_rule_id(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """table_row() contains the rule_id."""
        row = formatter.table_row(sample_rule)
        assert sample_rule.rule_id in row

    def test_table_row_contains_blocked_literal(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """table_row() contains the blocked literal."""
        row = formatter.table_row(sample_rule)
        # Normalise backticks away for the check — the literal 'git reset --hard' must appear
        assert "git reset --hard" in row

    def test_table_row_contains_why(self, formatter: RuleFormatter, sample_rule: Rule) -> None:
        """table_row() contains the why text."""
        row = formatter.table_row(sample_rule)
        # Key word from why field
        assert "destroys" in row.lower()

    def test_table_row_contains_fix(self, formatter: RuleFormatter, sample_rule: Rule) -> None:
        """table_row() contains the fix text."""
        row = formatter.table_row(sample_rule)
        assert "stash" in row.lower()

    def test_table_row_is_pipe_delimited(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """table_row() uses pipe characters as column delimiters."""
        row = formatter.table_row(sample_rule)
        assert "|" in row

    def test_table_row_no_newlines_in_middle(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """table_row() is a single line (no internal newlines beyond trailing)."""
        row = formatter.table_row(sample_rule)
        # Strip trailing newline, then no more newlines inside
        assert "\n" not in row.rstrip("\n")


class TestRuleFormatterTerse:
    """RuleFormatter.terse() produces a terse reminder message."""

    def test_terse_returns_string(self, formatter: RuleFormatter, sample_rule: Rule) -> None:
        """terse() returns a str."""
        msg = formatter.terse(sample_rule)
        assert isinstance(msg, str)

    def test_terse_contains_rule_id(self, formatter: RuleFormatter, sample_rule: Rule) -> None:
        """terse() contains the rule_id (the ID is the key for repeat fires)."""
        msg = formatter.terse(sample_rule)
        assert sample_rule.rule_id in msg

    def test_terse_contains_blocked_literal(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """terse() contains the blocked literal."""
        msg = formatter.terse(sample_rule)
        assert "git reset --hard" in msg

    def test_terse_contains_fix_pointer(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """terse() contains the fix or a pointer to the rule-explain command."""
        msg = formatter.terse(sample_rule)
        # Either fix text or rule-explain pointer must be present
        has_fix = "stash" in msg.lower()
        has_explain = "rule-explain" in msg.lower() or "explain" in msg.lower()
        assert has_fix or has_explain, f"terse() missing fix/explain pointer: {msg!r}"

    def test_terse_contains_blocked_word(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """terse() signals the action is blocked."""
        msg = formatter.terse(sample_rule)
        assert "BLOCKED" in msg or "blocked" in msg.lower()

    def test_terse_is_shorter_than_verbose(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """terse() is meaningfully shorter than verbose() (it IS the terse form)."""
        terse_msg = formatter.terse(sample_rule)
        verbose_msg = formatter.verbose(sample_rule)
        assert len(terse_msg) < len(verbose_msg)


class TestRuleFormatterVerbose:
    """RuleFormatter.verbose() produces the full first-fire block message."""

    def test_verbose_returns_string(self, formatter: RuleFormatter, sample_rule: Rule) -> None:
        """verbose() returns a str."""
        msg = formatter.verbose(sample_rule)
        assert isinstance(msg, str)

    def test_verbose_contains_rule_id(self, formatter: RuleFormatter, sample_rule: Rule) -> None:
        """verbose() contains the rule_id."""
        msg = formatter.verbose(sample_rule)
        assert sample_rule.rule_id in msg

    def test_verbose_contains_blocked_literal(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """verbose() contains the blocked literal."""
        msg = formatter.verbose(sample_rule)
        assert "git reset --hard" in msg

    def test_verbose_contains_rule_verbose_field(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """verbose() incorporates Rule.verbose (the teaching content)."""
        msg = formatter.verbose(sample_rule)
        # Key phrase from the verbose field
        assert "permanently destroys" in msg.lower()

    def test_verbose_contains_blocked_word(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """verbose() signals the action is blocked."""
        msg = formatter.verbose(sample_rule)
        assert "BLOCKED" in msg or "blocked" in msg.lower()

    def test_verbose_is_longer_than_terse(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """verbose() is longer than terse() (contains teaching content)."""
        assert len(formatter.verbose(sample_rule)) > len(formatter.terse(sample_rule))


class TestRuleFormatterConsistency:
    """All three formats are generated from the same Rule source — no drift."""

    def test_rule_id_consistent_across_formats(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """rule_id appears in table_row, terse, and verbose."""
        rid = sample_rule.rule_id
        assert rid in formatter.table_row(sample_rule)
        assert rid in formatter.terse(sample_rule)
        assert rid in formatter.verbose(sample_rule)

    def test_blocked_literal_consistent_across_formats(
        self, formatter: RuleFormatter, sample_rule: Rule
    ) -> None:
        """The blocked literal appears in table_row, terse, and verbose."""
        literal = "git reset --hard"  # Core of the blocked field
        assert literal in formatter.table_row(sample_rule)
        assert literal in formatter.terse(sample_rule)
        assert literal in formatter.verbose(sample_rule)

    def test_different_rules_produce_different_table_rows(self, formatter: RuleFormatter) -> None:
        """Two different Rule instances produce different table rows."""
        r1 = Rule(
            rule_id="R-ONE",
            blocked="`command-one`",
            why="reason one",
            fix="fix one",
            verbose="verbose one",
        )
        r2 = Rule(
            rule_id="R-TWO",
            blocked="`command-two`",
            why="reason two",
            fix="fix two",
            verbose="verbose two",
        )
        assert formatter.table_row(r1) != formatter.table_row(r2)
