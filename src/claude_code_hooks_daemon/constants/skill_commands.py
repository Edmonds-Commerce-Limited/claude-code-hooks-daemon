"""Skill / CLI subcommand name constants.

Plan 00116: subcommand names are a public contract reused across the rule-explain
pointer (``core/rule.py``) and the Phase 6 CLI + skill. Centralised here so each
literal lives in exactly one place (NO MAGIC / single source of truth). Sibling
commands (``explain-rule`` CLI, ``explain-handler``) join here when Phase 6 builds
them.
"""

from __future__ import annotations

from typing import ClassVar


class SkillCommand:
    """Canonical names for hooks-daemon skill / CLI subcommands."""

    RULE_EXPLAIN: ClassVar[str] = "rule-explain"
