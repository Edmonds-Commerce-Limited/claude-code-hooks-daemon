"""Rule dataclass and RuleFormatter — single source of truth for handler rules.

Plan 00116, Phase 2 (Tasks 2.1).

A ``Rule`` encodes everything needed to generate:

1. A **CLAUDE.md table row** (terse, always-on — via ``RuleFormatter.table_row``).
2. A **terse reminder** for repeat fires (via ``RuleFormatter.terse``).
3. A **verbose block** for the first fire per session (via ``RuleFormatter.verbose``).

All three are rendered from ONE ``Rule`` object so they cannot drift apart.

Design decisions (Plan 00116):
  - Decision A: handler-owned rules via ``Handler.get_rules()``.
  - Decision B: per-rule granularity (e.g. ``destructive_git`` → 9 rules).
  - Decision C: blocking-only rules get the full table + disclosure ladder.
  - Decision D: rule IDs are a public contract; use ``RuleID`` constants.
"""

from __future__ import annotations

from dataclasses import dataclass

# Pointer suffix injected into terse reminders so agents can fetch full detail.
_EXPLAIN_SUFFIX = "Full detail: /hooks-daemon rule-explain {rule_id}"


@dataclass(frozen=True, slots=True)
class Rule:
    """Immutable descriptor for a single blocking rule.

    Attributes:
        rule_id:  Stable public identifier (from ``RuleID`` constants, e.g.
                  ``"R-GIT-RESET-HARD"``).  Appears in CLAUDE.md and block
                  messages.  Renames are a breaking change.
        blocked:  Terse description of what is blocked, including the literal
                  command/pattern (e.g. ``"`git reset --hard`"``).  Must
                  contain the load-bearing literal verbatim so term-set tests
                  can assert no content was lost.
        why:      One-line consequence (e.g. ``"Permanently destroys all
                  uncommitted changes"``).
        fix:      One-line prescribed remedy (e.g. ``"Use `git stash` or ask
                  the user to run manually"``).
        verbose:  Full teaching content for the first-fire block message.
                  Delivered exactly once per rule per session; subsequent fires
                  use the terse reminder.  Must not be empty.
    """

    rule_id: str
    blocked: str
    why: str
    fix: str
    verbose: str


class RuleFormatter:
    """Renders a ``Rule`` into the three canonical text formats.

    All three formats are generated from the same ``Rule`` instance, so they
    cannot drift from one another (Decision D single-source guarantee).

    Formats:
      - ``table_row(rule)``  — a single pipe-delimited markdown table row for
        the always-on CLAUDE.md rule table.
      - ``terse(rule)``      — a short reminder used for repeat block fires
        after the verbose block has already been disclosed this session.
      - ``verbose(rule)``    — the full first-fire block message containing the
        rule_id, blocked literal, and the ``Rule.verbose`` teaching content.
    """

    def table_row(self, rule: Rule) -> str:
        """Render a single markdown table row for the rule.

        Format::

            | R-GIT-RESET-HARD | `git reset --hard` | Permanently destroys... | Use git stash... |

        The row is a single line (no embedded newlines).

        Args:
            rule: The rule to render.

        Returns:
            A pipe-delimited markdown table row string (no trailing newline).
        """
        return (
            f"| {rule.rule_id} | {rule.blocked} | {rule.why} | {rule.fix} |"
        )

    def terse(self, rule: Rule) -> str:
        """Render a terse reminder for repeat block fires.

        Contains the rule_id, the blocked literal, the one-line fix, and a
        pointer to the on-demand detail command.

        Args:
            rule: The rule to render.

        Returns:
            A compact block message string for repeat fires.
        """
        explain_pointer = _EXPLAIN_SUFFIX.format(rule_id=rule.rule_id)
        return (
            f"BLOCKED [{rule.rule_id}]: {rule.blocked} — {rule.why}. "
            f"Fix: {rule.fix}. {explain_pointer}"
        )

    def verbose(self, rule: Rule) -> str:
        """Render the full verbose block for the first fire of this rule.

        Contains the rule_id, blocked literal, and the full ``Rule.verbose``
        teaching content.  Always longer than ``terse()``.

        Args:
            rule: The rule to render.

        Returns:
            The complete first-fire block message string.
        """
        return (
            f"BLOCKED [{rule.rule_id}]: {rule.blocked}\n\n"
            f"{rule.verbose}"
        )
