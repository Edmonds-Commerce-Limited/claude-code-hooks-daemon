"""Tests for SkillCommand constants.

Plan 00116: skill/CLI subcommand names are a public contract reused across the
rule-explain pointer (core/rule.py) and the Phase 6 CLI + skill. They must be
named constants (NO MAGIC / single source of truth), not scattered literals.
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants.skill_commands import SkillCommand
from claude_code_hooks_daemon.core.rule import _EXPLAIN_SUFFIX


class TestSkillCommand:
    """SkillCommand exposes the canonical skill/CLI subcommand names."""

    def test_rule_explain_value(self) -> None:
        """RULE_EXPLAIN is the documented `rule-explain` subcommand (Decision F)."""
        assert SkillCommand.RULE_EXPLAIN == "rule-explain"

    def test_rule_explain_is_str(self) -> None:
        """The constant is a plain string usable directly in f-strings."""
        assert isinstance(SkillCommand.RULE_EXPLAIN, str)

    def test_explain_suffix_uses_the_constant(self) -> None:
        """core/rule.py's pointer suffix is built from the constant, not a literal."""
        assert SkillCommand.RULE_EXPLAIN in _EXPLAIN_SUFFIX
