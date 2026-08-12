"""Single source of truth for the plan-doc-size REMEDY wording (Plan 00211).

A field report found the plan-size guidance offered exactly TWO remedies
(RELOCATE narrative into ``JOURNAL/``, SPLIT an over-scoped plan) across
three independent surfaces:

- :mod:`plan_qa.checks.plan_doc_size` — the ``Finding.remediation`` text
- :mod:`handlers.pre_tool_use.plan_qa_edit` — the injected CLAUDE.md
  guidance for the ``plan-doc-size`` check
- :mod:`handlers.pre_tool_use.plan_workflow` — the injected CLAUDE.md
  PLAN.md/JOURNAL/ contract section

Each surface hand-copied the wording, and it had already drifted: none of
them named the most common actual cause of an oversized ``PLAN.md`` —
durable, detailed, CURRENT content (research output, decisions and their
reasoning, evidence tables, drafts) that is neither history (so it does not
belong in ``JOURNAL/``) nor task tree (so splitting the plan does not help).

This module is now the ONLY place the remedies are authored. Every surface
renders from :data:`REMEDIES` via :func:`remedy_sentence` or
:func:`remedy_markdown_list` rather than restating the wording — so a
future hand-rewrite of one surface immediately shows up as that surface's
text no longer containing the canonical rendering (see
``tests/unit/plan_qa/test_remedy.py`` for the cross-surface guard).

Ordering is load-bearing: EXTRACT is listed first because it is the correct
answer most often — ``PLAN.md`` is a task list, and almost anything making
it big is durable detail that wants a name, not history (RELOCATE) or an
over-scoped task tree (SPLIT).
"""

from typing import Final, NamedTuple


class Remedy(NamedTuple):
    """One remedy: an imperative VERB plus the detail clause that follows it."""

    verb: str
    detail: str


REMEDIES: Final[tuple[Remedy, ...]] = (
    Remedy(
        verb="EXTRACT",
        detail=(
            "durable detail — research output, findings, decisions and "
            "their reasoning, drafts, evidence tables — into a named "
            "supporting document in this plan folder (e.g. `RESEARCH-*.md`, "
            "`DECISIONS.md`) and link to it from the task"
        ),
    ),
    Remedy(
        verb="RELOCATE",
        detail=(
            "dated narrative — progress notes, incident write-ups, "
            "hand-off prose — into this plan's JOURNAL/ day-file, which is "
            "append-only and unbounded by design"
        ),
    ),
    Remedy(
        verb="SPLIT",
        detail=(
            "the plan if the task tree itself is the bulk, since an "
            "over-scoped plan is not fixed by better journalling"
        ),
    ),
)

_LAST_INDEX: Final[int] = len(REMEDIES) - 1


def remedy_sentence() -> str:
    """Canonical inline-prose rendering for a ``Finding.remediation`` string.

    ``Three remedies, and NONE is deletion: (1) EXTRACT ...; (2) RELOCATE
    ...; or (3) SPLIT .... Keep PLAN.md lean, current and correct — history
    belongs in git and in JOURNAL/.``

    Single line (no embedded newlines) so it drops cleanly into flowing
    prose contexts.
    """
    clauses = []
    for index, remedy in enumerate(REMEDIES):
        ordinal = f"({index + 1})"
        if index == 0:
            joiner = ""
        elif index == _LAST_INDEX:
            joiner = "; or "
        else:
            joiner = "; "
        clauses.append(f"{joiner}{ordinal} {remedy.verb} {remedy.detail}")
    return (
        f"Three remedies, and NONE is deletion: {''.join(clauses)}. Keep "
        "PLAN.md lean, current and correct — history belongs in git and in "
        "JOURNAL/."
    )


def remedy_markdown_list() -> str:
    """Canonical numbered-markdown-list rendering for CLAUDE.md prose contexts."""
    return "\n".join(
        f"{index + 1}. **{remedy.verb}** {remedy.detail}." for index, remedy in enumerate(REMEDIES)
    )
