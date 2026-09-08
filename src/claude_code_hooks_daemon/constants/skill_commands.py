"""Skill / CLI subcommand name constants.

Plan 00116: subcommand names are a public contract reused across the
rule-explain pointer (``core/rule.py``) and the CLI + skill. Centralised here
so each literal lives in exactly one place (NO MAGIC / single source of truth).

Plan 00330 split the two surfaces: ``SkillCommand`` names what a human types
after ``/hooks-daemon``; ``CliCommand`` names a daemon CLI verb that is a
documented capability rather than a routed subcommand. ``explain-rule`` moved
from the first to the second, so the pointer every terse block message
carries now prints the CLI form.
"""

from __future__ import annotations

from typing import ClassVar


class SkillCommand:
    """Canonical names for routed hooks-daemon skill subcommands."""

    HOUSEKEEPING: ClassVar[str] = "housekeeping"
    OPTIMISE: ClassVar[str] = "optimise"


class CliCommand:
    """Canonical names for daemon CLI verbs that agent-facing text points at."""

    EXPLAIN_RULE: ClassVar[str] = "explain-rule"
    HOUSEKEEPING: ClassVar[str] = "housekeeping"
