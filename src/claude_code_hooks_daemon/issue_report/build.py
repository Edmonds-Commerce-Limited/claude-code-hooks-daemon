"""Run the verification gates, then assemble (Plan 00403 Tasks 2.1/3.1/3.3).

:func:`claude_code_hooks_daemon.issue_report.assemble.assemble_report` builds
the document. This layer decides whether it may be built at all: it runs the
version-currency and source-citation gates, turns loosely-typed input into the
controlled field set, and returns EVERY reason a report is refused rather than
the first — an author who fixes one refusal per round trip learns the rule one
refusal at a time.

One behaviour looks like a defect and is the rule working. An install BEHIND
the newest release cannot answer the currency question offline: the release
notes that shipped with it stop at its own version, so the notes for the
versions in between are precisely what it does not have. The check therefore
refuses, and the remedy is to upgrade — which is the owner's rule ("ensure that
they are running the latest version") reached mechanically instead of asserted.

Nothing here reaches the network. A report generator that needed a working
remote would fail exactly when the daemon is misbehaving, which is when it is
run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.issue_report.assemble import (
    AssembledReport,
    ConfigConsideration,
    ReportFields,
    ReportProblem,
    assemble_report,
)
from claude_code_hooks_daemon.issue_report.citation import check_source_citation
from claude_code_hooks_daemon.issue_report.currency import assess_currency

_REQUIRED_TEXT_FIELDS: tuple[str, ...] = ("summary", "expected", "observed", "reproduction")


@dataclass(frozen=True)
class _Parsed:
    """Field extraction that reports its own failures instead of raising."""

    values: dict[str, str]
    considerations: tuple[ConfigConsideration, ...]
    handler: str | None
    citation: str | None
    problems: tuple[ReportProblem, ...]


def _parse_considerations(raw: Any) -> tuple[tuple[ConfigConsideration, ...], list[ReportProblem]]:
    problems: list[ReportProblem] = []
    considerations: list[ConfigConsideration] = []
    if raw is None:
        return (), problems
    if not isinstance(raw, list):
        return (), [ReportProblem(reason="`config_considered` must be a list of entries.")]

    for index, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            problems.append(
                ReportProblem(
                    reason=(
                        f"`config_considered[{index}]` must be an object with `option` and "
                        "`why_insufficient`."
                    )
                )
            )
            continue
        option = str(entry.get("option", "")).strip()
        why = str(entry.get("why_insufficient", "")).strip()
        if not option or not why:
            problems.append(
                ReportProblem(
                    reason=(
                        f"`config_considered[{index}]` needs both `option` and "
                        "`why_insufficient` — naming an option without saying why it is "
                        "insufficient is the claim, not the evidence."
                    )
                )
            )
            continue
        considerations.append(ConfigConsideration(option=option, why_insufficient=why))

    return tuple(considerations), problems


def _parse(data: Mapping[str, Any]) -> _Parsed:
    problems: list[ReportProblem] = []
    values: dict[str, str] = {}

    for name in _REQUIRED_TEXT_FIELDS:
        raw = data.get(name)
        if raw is None:
            problems.append(
                ReportProblem(reason=f"`{name}` is missing from the report fields.")
            )
            values[name] = ""
        else:
            values[name] = str(raw)

    considerations, consideration_problems = _parse_considerations(data.get("config_considered"))
    problems.extend(consideration_problems)

    handler = data.get("handler")
    citation = data.get("source_citation")

    return _Parsed(
        values=values,
        considerations=considerations,
        handler=str(handler) if handler else None,
        citation=str(citation) if citation else None,
        problems=tuple(problems),
    )


def build_report(
    data: Mapping[str, Any],
    *,
    project_root: Path,
    daemon_root: Path,
    daemon_version: str,
    install_mode: str,
    platform_text: str,
    generated_at: str,
    release_notes: Mapping[str, str],
    latest_version: str | None = None,
    home: Path | None = None,
) -> AssembledReport:
    """Verify, then assemble — or refuse with every reason at once.

    Args:
        data: The reporter's declared fields, loosely typed (it arrives as
            JSON), so every extraction reports rather than raises.
        project_root: The client's checkout, scrubbed out of the free text.
        daemon_root: Where the installed daemon lives, for resolving the
            citation.
        daemon_version: The running version.
        install_mode: ``self-install`` or ``normal``.
        platform_text: OS, architecture and Python version. Deliberately NOT
            the hostname — see :class:`ReportFields`.
        generated_at: ISO date.
        release_notes: Version to note body, for the currency check.
        latest_version: The newest release, when known. Absent means "no newer
            release is known to this install", which is the ordinary case and
            is treated as current.
        home: The user's home directory, scrubbed out of the free text.

    Returns:
        An :class:`AssembledReport`. On refusal the document is EMPTY — a file
        that exists is a file that can be filed by mistake.
    """
    parsed = _parse(data)
    problems: list[ReportProblem] = list(parsed.problems)

    subsystem = parsed.handler or parsed.values.get("summary", "")
    currency = assess_currency(
        installed=daemon_version,
        latest=latest_version or daemon_version,
        subsystem=subsystem,
        notes=release_notes,
    )
    if not currency.may_report:
        problems.append(ReportProblem(reason=currency.detail))

    if parsed.citation is None:
        problems.append(
            ReportProblem(
                reason=(
                    "`source_citation` is missing. Reading the daemon's source is what "
                    "separates a defect from a misunderstanding, and a `file:line` is the "
                    "part of that a report can actually carry."
                )
            )
        )
        citation_detail = ""
    else:
        verdict = check_source_citation(parsed.citation, daemon_root=daemon_root)
        citation_detail = verdict.detail
        if not verdict.resolved:
            problems.append(ReportProblem(reason=verdict.detail))

    fields = ReportFields(
        summary=parsed.values["summary"],
        expected=parsed.values["expected"],
        observed=_with_findings(
            parsed.values["observed"], currency.detail, citation_detail
        ),
        reproduction=parsed.values["reproduction"],
        daemon_version=daemon_version,
        generated_at=generated_at,
        platform=platform_text,
        install_mode=install_mode,
        config_considered=parsed.considerations,
        handler=parsed.handler,
        source_citation=parsed.citation,
    )

    # Assembly runs even when a gate already refused, so its field-level
    # findings arrive in the SAME response. Short-circuiting here would mean a
    # reporter with a blank summary and a dead citation fixes the citation,
    # resubmits, and only then learns about the summary — one refusal per round
    # trip, which is the thing this module exists to avoid.
    assembled = assemble_report(fields, project_root=project_root, home=home)
    problems.extend(assembled.problems)

    if problems:
        return AssembledReport(problems=tuple(problems))
    return assembled


def _with_findings(observed: str, currency_detail: str, citation_detail: str) -> str:
    """Append what the gates FOUND to the report body.

    A report that merely passed its checks looks identical to one that was
    never checked. Carrying the findings is what makes the difference visible
    to a maintainer, and it is the same reason `assess_currency` returns a
    sentence rather than a bare boolean.
    """
    findings = [detail for detail in (currency_detail, citation_detail) if detail]
    if not findings:
        return observed
    lines = "\n".join(f"- {detail}" for detail in findings)
    return f"{observed.strip()}\n\n**Checks run when this report was generated:**\n\n{lines}"
