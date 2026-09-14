"""The last backstop over a report's free text (Plan 00403).

Everything else in this package protects by NOT COLLECTING: no hostname, no git
remote, no config dump, no logs. That design cannot reach the fields the
reporter types themselves, and free text is exactly where somebody pastes the
internal hostname because it seemed load-bearing to the explanation. A project's
gitignored block-word list is the only declaration of what those strings are, so
it is the only thing that can catch them.

Two behaviours differ from what the rest of the daemon does with those terms,
and both are deliberate.

``refused, not redacted``
    ``scrub_report`` REPLACES a term with a placeholder, which is right for a
    local diagnostic nobody has read yet. A report is different: the reporter is
    still at the keyboard, the sentence containing the term is theirs to
    rewrite, and a silently redacted report teaches them nothing while leaving
    prose that now reads as nonsense. Refusing hands the decision back to the
    person who can actually make it.

``the refusal names an index, never the term``
    Identical to ``sensitive_content``'s disclosure rule, for the identical
    reason: this message goes into logs, into a transcript, and into the
    agent's own context. "entry 2 of 5" is meaningless without the gitignored
    file, and that is the whole point of naming it that way.

The terms are passed IN rather than resolved here, so assembly stays a pure
function a test can drive without a filesystem — and so the one place that
resolves the active list is the CLI, which already knows which project it runs
for.

The module is named for the list's own filename rather than for what the list
holds. The obvious name collides with ``secret_file_guard``'s protected-path
globs, which match a dotted module path as readily as a filename, so referring
to this module in any docstring would itself be denied (Plan 00405 N3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_code_hooks_daemon.utils.secret_redaction import find_first_match_index

if TYPE_CHECKING:  # pragma: no cover - types only; a runtime import would cycle
    from claude_code_hooks_daemon.issue_report.assemble import ReportFields


def describe_blocked_term(index: int, total: int) -> str:
    """The refusal, naming the entry and nothing else.

    Args:
        index: 1-based position in the project's block-word list.
        total: How many entries that list holds.

    Returns:
        A sentence safe to print, log and archive.
    """
    return (
        f"the report text matches entry {index} of {total} in this project's block-word "
        "list, so it cannot be filed. The term is deliberately not named here — this "
        "message is logged and kept in context, and naming it would put it exactly where "
        "the list exists to keep it out of. Find it by re-reading what you wrote against "
        "the list, then rewrite that sentence without it. If the term is genuinely needed "
        "to explain the defect, describe its SHAPE instead (an internal hostname, a client "
        "name) rather than the value."
    )


def _texts(fields: ReportFields) -> tuple[str, ...]:
    """Every string in a report that a human typed.

    The generated fields — version, platform, install mode, the date — are
    produced by the daemon and cannot carry a project's declared term. The
    ``config_considered`` entries are included because they are prose too, and
    the "why it was insufficient" half is the one people forget is free text.
    """
    parts: list[str] = [
        fields.summary,
        fields.expected,
        fields.observed,
        fields.reproduction,
        fields.handler or "",
        fields.source_citation or "",
    ]
    for item in fields.config_considered:
        parts.append(item.option)
        parts.append(item.why_insufficient)
    return tuple(part for part in parts if part)


def first_blocked_term_problem(fields: ReportFields, terms: tuple[str, ...]) -> str | None:
    """The refusal for the first declared term found, or ``None``.

    Args:
        fields: The controlled field set.
        terms: The project's block-word list. Empty means the feature is inert
            — a project that declared nothing gets silence, not an error.

    Returns:
        A term-free refusal, or ``None`` when nothing matched. It stops at the
        first match on purpose: a second refusal naming a second index would
        narrow the search for anyone reading the log, and one is enough to stop
        the filing.
    """
    if not terms:
        return None
    for text in _texts(fields):
        index = find_first_match_index(text, terms)
        if index is not None:
            return describe_blocked_term(index, len(terms))
    return None
