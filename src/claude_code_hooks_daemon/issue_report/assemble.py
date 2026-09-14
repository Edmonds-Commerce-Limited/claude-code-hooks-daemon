"""Assemble an upstream issue report from controlled fields (Plan 00403 Task 2.1).

The difference between this and ``bin/hooks-daemon bug-report`` is a difference
in KIND, and it is the whole point.

``bug-report`` collects everything a diagnostician might want — the config file,
the environment, a window of logs — and then scrubs what it collected. That
order leaks the first field somebody forgets, and Phase 1 of this plan found
three such fields in a tool whose output the documentation told people to paste
into a public issue.

This module asks for a fixed set of fields by name. :class:`ReportFields` is the
entire input surface, so the hostname is not scrubbed out of the report — it is
never collected, and a field absent from that class cannot arrive by being
forgotten somewhere downstream. Scrubbing still runs, but as a BACKSTOP over
the free-text fields rather than as the mechanism.

Two rules govern what the free text may contain, and they are deliberately
different from each other:

``the reproduction is refused; the prose is scrubbed``
    A reproduction that names a client path is not a report needing cleanup —
    it is a report written the wrong way, and the fix is to build a synthetic
    one. Prose is where a report explains itself, so refusing it outright would
    leave the reporter no way to describe anything; it is scrubbed instead.

``scrub first, then hash``
    The provenance digest must cover the bytes that will actually be filed. A
    digest taken before scrubbing describes a document that never existed, and
    every verification of it would fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.issue_report.provenance import render_document
from claude_code_hooks_daemon.issue_report.reproduction import check_reproduction
from claude_code_hooks_daemon.utils.report_scrubbing import scrub_report


@dataclass(frozen=True)
class ConfigConsideration:
    """One configuration option ruled out, with the reason it is insufficient.

    The generator cannot know whether the reporter really read the source or
    really thought about configuration. It CAN require them to name an option
    and say why it does not solve the problem — the same move the remote-docs
    provenance frontmatter makes, turning an unverifiable claim into a
    checkable artefact.
    """

    option: str
    why_insufficient: str


@dataclass(frozen=True)
class ReportFields:
    """Everything an upstream issue report may carry.

    This class IS the redaction boundary. There is no ``hostname``, no
    ``git_remote``, no config dump, no log window and no transcript, and that
    absence is the guarantee — not a filter applied to them later.
    """

    summary: str
    expected: str
    observed: str
    reproduction: str
    daemon_version: str
    generated_at: str
    platform: str
    install_mode: str
    config_considered: tuple[ConfigConsideration, ...] = ()
    handler: str | None = None
    source_citation: str | None = None


@dataclass(frozen=True)
class ReportProblem:
    """One reason the report cannot be produced."""

    reason: str


@dataclass(frozen=True)
class AssembledReport:
    """The outcome of assembly.

    ``document`` is empty whenever ``problems`` is non-empty. A refused report
    must not leave a document behind: a file that exists is a file that can be
    filed by mistake, and the mistake is unretractable.
    """

    document: str = ""
    problems: tuple[ReportProblem, ...] = field(default_factory=tuple)


_NOT_STATED: Final[str] = "_not stated_"


def _sections(fields: ReportFields) -> list[str]:
    """The report body, in the order a maintainer reads it."""
    lines = [
        f"## {fields.summary.strip()}",
        "",
        "| | |",
        "| --- | --- |",
        f"| Daemon version | {fields.daemon_version} |",
        f"| Install mode | {fields.install_mode} |",
        f"| Platform | {fields.platform} |",
        f"| Handler | {fields.handler or _NOT_STATED} |",
        "",
        "## Expected",
        "",
        fields.expected.strip(),
        "",
        "## Observed",
        "",
        fields.observed.strip(),
        "",
        "## Reproduction",
        "",
        fields.reproduction.strip(),
        "",
        "## Configuration ruled out",
        "",
    ]
    lines.extend(
        f"- `{item.option}` — {item.why_insufficient.strip()}" for item in fields.config_considered
    )
    lines.extend(
        [
            "",
            "## Source read",
            "",
            fields.source_citation or _NOT_STATED,
        ]
    )
    return lines


def _field_problems(fields: ReportFields) -> list[ReportProblem]:
    problems: list[ReportProblem] = []

    for name, value in (
        ("summary", fields.summary),
        ("expected", fields.expected),
        ("observed", fields.observed),
    ):
        if not value.strip():
            problems.append(
                ReportProblem(
                    reason=(
                        f"`{name}` is empty. A report a maintainer cannot act on costs "
                        "triage and gets closed, which is worse for you than writing it out."
                    )
                )
            )

    problems.extend(
        ReportProblem(
            reason=(
                f"the reproduction cannot be published: {problem.reason} "
                f"(offending: {problem.offending!r})"
            )
        )
        for problem in check_reproduction(fields.reproduction)
    )

    if not fields.config_considered:
        problems.append(
            ReportProblem(
                reason=(
                    "no configuration option has been ruled out. Most reports against this "
                    "daemon are configuration, so name at least one option you considered "
                    "and say why it does not solve the problem — "
                    "`hooks-daemon explain-handler <name>` lists them."
                )
            )
        )

    return problems


def assemble_report(
    fields: ReportFields,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> AssembledReport:
    """Build a filable issue document, or explain why it cannot be built.

    Args:
        fields: The controlled field set. Nothing outside it reaches the
            document.
        project_root: The client's checkout, replaced wherever it appears in
            the free-text fields. Optional so this stays a pure function that
            a test can drive without a filesystem.
        home: The user's home directory, whose name is usually their username.

    Returns:
        An :class:`AssembledReport`. On success it carries the document with
        its provenance header and no problems; on failure, the problems and an
        EMPTY document.
    """
    problems = _field_problems(fields)
    if problems:
        return AssembledReport(problems=tuple(problems))

    body = "\n".join(_sections(fields))

    # Scrub BEFORE the digest is taken, so the header vouches for the bytes
    # that will actually be filed. Reversing these two lines produces a
    # document that fails its own verification every time.
    if project_root is not None:
        body = scrub_report(body, project_root=project_root, home=home)

    return AssembledReport(
        document=render_document(
            body,
            daemon_version=fields.daemon_version,
            generated_at=fields.generated_at,
        )
    )
