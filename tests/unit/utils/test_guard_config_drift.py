"""The working-tree guard config vs the committed one (Plan 00412 class 2b).

Class 2, `guard-self-disablement-unwatched`: an action that changes what a
future session's guards will do, where no gate judges the action and no record
is made that it happened. F-GAP probed the disabling routes across three
mechanisms and four files and every result was `NOTHING DENIES`, with the
compounding property that every deny message prints the config key that would
disable the guard that just fired.

F-GAP's own judgement is that the PreToolUse deny is both owner-gated and
circular -- an agent that can edit the config can edit the rule guarding it --
and that the non-circular remedies are the commit gate and this drift report.
This is the drift half, and F-GAP rates it the lowest-noise part and the one to
build first.

The comparison is deliberately pure: YAML text in, findings out, no git and no
filesystem, so the rules below are the whole behaviour and the handler that
wires it to `git show HEAD:...` stays thin enough to read.

**Why a weakening is phrased against the COMMITTED text rather than a default.**
A handler's default-enabled state is a property of its class, not of the config,
so "enabled: false appeared" and "this guard is now off" are different claims.
Only the first is knowable from two YAML documents, and it is the one reported.
"""

from __future__ import annotations

from claude_code_hooks_daemon.utils.guard_config_drift import (
    DriftKind,
    compare_guard_config,
)

_COMMITTED = """
daemon:
  exclude_paths:
    - vendor/**
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: true
    sensitive_content:
      enabled: true
      options:
        exclude_paths:
          - docs/**
"""


class TestAnIdenticalConfigIsSilent:
    """The overwhelmingly common case: no drift, nothing said."""

    def test_identical_text_reports_nothing(self) -> None:
        report = compare_guard_config(_COMMITTED, _COMMITTED)

        assert report.has_drift is False
        assert report.guard_changes == ()

    def test_whitespace_only_change_is_not_a_guard_change(self) -> None:
        report = compare_guard_config(_COMMITTED, _COMMITTED + "\n\n")

        assert report.guard_changes == ()


class TestAGuardTurnedOff:
    """The finding this exists for."""

    def test_enabled_flipped_to_false_is_reported(self) -> None:
        working = _COMMITTED.replace(
            "    sed_blocker:\n      enabled: true",
            "    sed_blocker:\n      enabled: false",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert report.has_drift is True
        assert [c.kind for c in report.guard_changes] == [DriftKind.DISABLED]
        assert report.guard_changes[0].handler == "pre_tool_use.sed_blocker"

    def test_a_handler_block_removed_entirely_is_reported(self) -> None:
        working = _COMMITTED.replace(
            "    sed_blocker:\n      enabled: true\n",
            "",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert [c.kind for c in report.guard_changes] == [DriftKind.REMOVED]
        assert report.guard_changes[0].handler == "pre_tool_use.sed_blocker"

    def test_enabling_a_guard_is_not_reported_as_a_weakening(self) -> None:
        """Drift in the SAFE direction is still drift, but not a guard change."""
        committed = _COMMITTED.replace(
            "    sed_blocker:\n      enabled: true",
            "    sed_blocker:\n      enabled: false",
        )

        report = compare_guard_config(committed, _COMMITTED)

        assert report.guard_changes == ()
        assert report.has_drift is True


class TestExclusionsWidened:
    """An exclusion is a guard turned off for a path."""

    def test_an_added_handler_exclusion_is_reported(self) -> None:
        working = _COMMITTED.replace(
            "          - docs/**",
            "          - docs/**\n          - src/**",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert [c.kind for c in report.guard_changes] == [DriftKind.EXCLUSIONS_WIDENED]
        assert "src/**" in report.guard_changes[0].detail

    def test_an_added_daemon_wide_exclusion_is_reported(self) -> None:
        working = _COMMITTED.replace(
            "    - vendor/**",
            "    - vendor/**\n    - src/**",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert [c.kind for c in report.guard_changes] == [DriftKind.EXCLUSIONS_WIDENED]
        assert report.guard_changes[0].handler == "daemon"

    def test_a_removed_exclusion_is_not_a_weakening(self) -> None:
        working = _COMMITTED.replace("\n          - docs/**", "")

        report = compare_guard_config(_COMMITTED, working)

        assert report.guard_changes == ()


class TestUnenumeratedDriftIsCountedNotClaimedSafe:
    """Class 6 applies to this rule too: a weakening can be spelled another way.

    The enumerated kinds are not a claim that everything else is benign, so any
    remaining difference is COUNTED and surfaced rather than silently dropped.
    """

    def test_an_unrelated_change_is_counted_as_other_drift(self) -> None:
        working = _COMMITTED.replace(
            "      enabled: true\n    sensitive_content:",
            "      enabled: true\n      priority: 99\n    sensitive_content:",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert report.guard_changes == ()
        assert report.has_drift is True
        assert report.other_changes > 0


class TestTheOtherChangesCountIsNotInflated:
    """`other_changes` means "a difference I could NOT name".

    Its whole job is to stop the enumerated kinds being read as complete, so a
    count that includes changes already named as guard findings is a false
    alarm -- and an advisory that reports phantom differences every session is
    one that gets switched off. Both shapes below were found by running the
    comparator against the real project config.
    """

    def test_options_created_solely_for_a_reported_exclusion_is_not_other_drift(self) -> None:
        """The handler had no `options` block at all until the exclusion was added."""
        working = _COMMITTED.replace(
            "    sed_blocker:\n      enabled: true",
            "    sed_blocker:\n      enabled: true\n      options:\n"
            "        exclude_paths:\n          - src/**",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert [c.kind for c in report.guard_changes] == [DriftKind.EXCLUSIONS_WIDENED]
        assert report.other_changes == 0

    def test_a_daemon_exclusion_is_not_counted_as_a_finding_and_again_as_drift(self) -> None:
        working = _COMMITTED.replace(
            "    - vendor/**",
            "    - vendor/**\n    - src/**",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert [c.kind for c in report.guard_changes] == [DriftKind.EXCLUSIONS_WIDENED]
        assert report.other_changes == 0

    def test_a_genuinely_unnamed_daemon_change_is_still_counted(self) -> None:
        """Narrowing the double-count must not silence the `daemon` block entirely."""
        working = _COMMITTED.replace(
            "daemon:\n  exclude_paths:",
            "daemon:\n  log_level: DEBUG\n  exclude_paths:",
        )

        report = compare_guard_config(_COMMITTED, working)

        assert report.guard_changes == ()
        assert report.other_changes == 1


class TestMalformedInputFailsQuietlyRatherThanCryingWolf:
    """An advisory that fires wrongly every session gets switched off."""

    def test_unparseable_working_yaml_reports_no_guard_change(self) -> None:
        report = compare_guard_config(_COMMITTED, "handlers: [unclosed")

        assert report.guard_changes == ()
        assert report.parse_failed is True

    def test_an_absent_committed_config_is_not_drift(self) -> None:
        """A fresh install has nothing to compare against."""
        report = compare_guard_config("", _COMMITTED)

        assert report.has_drift is False
        assert report.guard_changes == ()
