"""Tests for the skill / CLI subcommand name constants.

Plan 00116: subcommand names are a public contract reused across the
rule-explain pointer (core/rule.py) and the CLI + skill. They must be named
constants (NO MAGIC / single source of truth), not scattered literals.

Plan 00330: the pointer names the CLI verb (`explain-rule`), because
`rule-explain` is a documented capability rather than a routed subcommand.
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants.skill_commands import CliCommand, SkillCommand
from claude_code_hooks_daemon.core.rule import _EXPLAIN_SUFFIX


class TestCliCommand:
    def test_explain_rule_value(self) -> None:
        assert CliCommand.EXPLAIN_RULE == "explain-rule"

    def test_housekeeping_is_the_same_verb_the_skill_routes(self) -> None:
        assert CliCommand.HOUSEKEEPING == SkillCommand.HOUSEKEEPING == "housekeeping"

    def test_explain_suffix_uses_the_cli_verb(self) -> None:
        """core/rule.py's pointer is built from the constant, not a literal, and
        names the CLI form a human can paste."""
        assert CliCommand.EXPLAIN_RULE in _EXPLAIN_SUFFIX
        assert "rule-explain" not in _EXPLAIN_SUFFIX
        # Slash-command syntax reads as a bash command to Claude (skill_refs QA).
        assert " /hooks-daemon" not in _EXPLAIN_SUFFIX
        assert "bin/hooks-daemon" in _EXPLAIN_SUFFIX


class TestSkillCommand:
    def test_optimise_value(self) -> None:
        assert SkillCommand.OPTIMISE == "optimise"

    def test_no_constant_names_a_documented_only_capability(self) -> None:
        """Only routed subcommands belong on SkillCommand."""
        assert not hasattr(SkillCommand, "RULE_EXPLAIN")
