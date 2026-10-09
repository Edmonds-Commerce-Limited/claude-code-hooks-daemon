"""Lookup of plan-QA and docs-QA check IDs (Plan 00484 G15).

A deny from ``plan_qa_edit``, ``plan_qa_commit_gate``, ``docs_qa_edit`` or
``docs_qa_commit_gate`` names the failing CHECK (for example ``plan-doc-size``),
because many checks share one umbrella rule. Without this module the printed ID
resolves nowhere: ``explain-rule plan-doc-size`` answered "unknown rule ID".

Nothing is registered twice. The checks come from the same ``all_checks()``
registries the runners execute, the umbrella rule is the one the stage maps to,
and the statement is the ``STATEMENT`` constant each check module declares beside its
``CHECK_ID``.
"""

from __future__ import annotations

import difflib
import importlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.docs_qa.checks import all_checks as all_docs_checks
from claude_code_hooks_daemon.docs_qa.types import CheckStage as DocsStage
from claude_code_hooks_daemon.plan_qa.checks import all_checks as all_plan_checks
from claude_code_hooks_daemon.plan_qa.types import Stage as PlanStage

__all__ = ["CheckEntry", "collect_check_entries", "find_check", "near_check_matches"]

# The umbrella rule a check's deny is reported under, by the stage it runs at.
# The sweep stage never denies (it is the advisory session-start report), so it
# maps to nothing.
_PLAN_UMBRELLA: Final[dict[str, str]] = {
    PlanStage.EDIT.value: RuleID.PLAN_QA_EDIT,
    PlanStage.COMMIT.value: RuleID.PLAN_QA_COMMIT,
}
_DOCS_UMBRELLA: Final[dict[str, str]] = {
    DocsStage.EDIT.value: RuleID.DOCS_QA_EDIT,
    DocsStage.STAGED.value: RuleID.DOCS_QA_COMMIT,
}

_NEAR_MATCH_CUTOFF: Final[float] = 0.6
_NEAR_MATCH_LIMIT: Final[int] = 5
_STATEMENT_ATTR: Final[str] = "STATEMENT"


@dataclass(frozen=True, slots=True)
class CheckEntry:
    """One QA check: its ID, the umbrella rules its denies are filed under, its purpose.

    Attributes:
        check_id: The ID printed in a deny reason, such as ``plan-doc-size``.
        umbrella_rule_ids: The ``R-`` rules whose denies can name this check
            (empty for a check that only runs in the advisory sweep).
        stages: The stages the check is registered at, in registry order.
        statement: What the check refuses and what to do, from its module's ``STATEMENT``.
    """

    check_id: str
    umbrella_rule_ids: tuple[str, ...]
    stages: tuple[str, ...]
    statement: str


def _statement(run_module: str) -> str:
    """The check module's own ``STATEMENT`` constant (what is refused, and what to do).

    Raises:
        ValueError: If the module declares none; ``test_rule_parity.py`` requires one.
    """
    statement = getattr(importlib.import_module(run_module), _STATEMENT_ATTR, None)
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError(f"{run_module} declares no {_STATEMENT_ATTR} constant")
    return statement


def _entries(
    specs: Iterable[tuple[str, str, str]], umbrella: dict[str, str]
) -> dict[str, CheckEntry]:
    """Fold ``(check_id, stage, run_module)`` registrations into one entry per check."""
    folded: dict[str, CheckEntry] = {}
    for check_id, stage, run_module in specs:
        known = folded.get(check_id)
        stages = (*known.stages, stage) if known else (stage,)
        rules = tuple(umbrella[s] for s in stages if s in umbrella)
        statement = known.statement if known else _statement(run_module)
        folded[check_id] = CheckEntry(check_id, rules, stages, statement)
    return folded


def collect_check_entries() -> list[CheckEntry]:
    """Every registered plan-QA and docs-QA check, one entry per check ID.

    Returns:
        Entries sorted by check ID.

    Raises:
        ValueError: If one check ID is registered by both packages (the lookup
            could not tell which umbrella rule the reader means).
    """
    plan = _entries(
        ((c.check_id, c.stage.value, c.run.__module__) for c in all_plan_checks()), _PLAN_UMBRELLA
    )
    docs = _entries(
        ((c.check_id, c.stage.value, c.run.__module__) for c in all_docs_checks()), _DOCS_UMBRELLA
    )
    clash = sorted(set(plan) & set(docs))
    if clash:
        raise ValueError(f"check IDs registered by both plan_qa and docs_qa: {clash}")
    return sorted([*plan.values(), *docs.values()], key=lambda entry: entry.check_id)


def find_check(entries: list[CheckEntry], check_id: str) -> CheckEntry | None:
    """Find a check by ID, case-insensitively.

    Args:
        entries: Entries from :func:`collect_check_entries`.
        check_id: The ID the caller typed.

    Returns:
        The matching entry, or ``None``.
    """
    target = check_id.strip().lower()
    return next((entry for entry in entries if entry.check_id == target), None)


def near_check_matches(
    entries: list[CheckEntry], check_id: str, limit: int = _NEAR_MATCH_LIMIT
) -> list[str]:
    """Suggest close-spelling check IDs for an unknown lookup.

    Args:
        entries: Entries from :func:`collect_check_entries`.
        check_id: The unmatched ID the caller typed.
        limit: Maximum number of suggestions.

    Returns:
        Close-spelling check IDs, best match first.
    """
    return difflib.get_close_matches(
        check_id.strip().lower(),
        [entry.check_id for entry in entries],
        n=limit,
        cutoff=_NEAR_MATCH_CUTOFF,
    )
