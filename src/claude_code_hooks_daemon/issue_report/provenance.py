"""The provenance header on a generated issue report (Plan 00403 Task 2.3).

The filing gate has to tell a body the generator produced from one somebody
typed, and the header is how. What it is worth deserves stating precisely,
because overstating it would be exactly the false comfort this plan exists to
remove.

**This is tamper evidence, not authentication.** Nothing running in-process can
stop an agent that decides to compute a digest itself, and no scheme available
here would change that. What it reliably catches is the failure that actually
happens: a clean report is generated, then edited — to paste in the log
excerpt, the stack trace or the config snippet that seemed helpful — and filed.
That edit breaks the digest, and catching it is the whole job.

The header is an HTML comment so GitHub renders it invisibly: a reader sees the
report, not the bookkeeping, and the fields survive a copy-paste of the whole
body because they are part of it.

Parsing NEVER raises. The consumer is a PreToolUse handler, where an escaping
exception takes down the gate rather than reporting a bad document — the same
contract :mod:`claude_code_hooks_daemon.remote_docs.provenance` runs on, for
the same reason.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final

#: Names the generator inside the header. Distinctive enough that its presence
#: is a deliberate claim rather than a coincidence of prose.
PROVENANCE_MARKER: Final[str] = "hooks-daemon-issue-report"

#: The command that produces a valid document. Named in every refusal, because
#: a gate that says no without saying what to run instead gets worked around.
GENERATOR_COMMAND: Final[str] = "hooks-daemon issue-report"

_FIELD_VERSION: Final[str] = "daemon_version"
_FIELD_GENERATED_AT: Final[str] = "generated_at"
_FIELD_DIGEST: Final[str] = "body_sha256"

_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"\A\s*<!--\s*" + re.escape(PROVENANCE_MARKER) + r"\s*\n(?P<fields>.*?)\n\s*-->",
    re.DOTALL,
)
#: Field keys carry digits (`body_sha256`), so the class must include them —
#: a letters-only key pattern silently drops exactly the field that matters.
_FIELD_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<key>[a-z0-9_]+)\s*:\s*(?P<value>.*?)\s*$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ProvenanceProblem:
    """One reason a document cannot be accepted as generator-produced."""

    reason: str


def body_digest(body: str) -> str:
    """A digest of ``body`` that survives harmless editing but nothing more.

    Line endings are normalised and the edges are stripped, so a client whose
    editor writes CRLF or trims trailing whitespace on save is not refused for
    their editor's defaults. Everything else is significant: normalising more
    than this would eventually normalise away the change the digest exists to
    notice.
    """
    normalised = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def render_document(body: str, *, daemon_version: str, generated_at: str) -> str:
    """Wrap ``body`` in a provenance header the filing gate can check.

    Args:
        body: The assembled report, without a header.
        daemon_version: The version that generated it, so a maintainer knows
            which source the report describes.
        generated_at: An ISO date. Deliberately a DATE and not a timestamp —
            the hour someone generated a report says nothing diagnostic and
            narrows who they are.

    Returns:
        The full document: header comment, blank line, body.
    """
    return (
        f"<!-- {PROVENANCE_MARKER}\n"
        f"{_FIELD_VERSION}: {daemon_version}\n"
        f"{_FIELD_GENERATED_AT}: {generated_at}\n"
        f"{_FIELD_DIGEST}: {body_digest(body)}\n"
        "-->\n"
        "\n"
        f"{body.strip()}\n"
    )


def split_document(text: str) -> tuple[dict[str, str] | None, str]:
    """Separate the header fields from the body.

    Returns:
        ``(fields, body)``. ``fields`` is ``None`` when no well-formed header
        is present, in which case ``body`` is the whole input — a caller that
        wants to re-run content rules over a rejected document still can.
    """
    match = _HEADER_RE.match(text)
    if match is None:
        return None, text

    fields: dict[str, str] = {}
    for line in match.group("fields").splitlines():
        field = _FIELD_RE.match(line)
        if field is not None:
            fields[field.group("key")] = field.group("value")
    return fields, text[match.end() :]


def verify_document(text: str) -> tuple[ProvenanceProblem, ...]:
    """Every reason this document is not an unmodified generated report.

    Args:
        text: The candidate issue body.

    Returns:
        An empty tuple when the document carries a well-formed header whose
        digest matches its body, otherwise one problem per fault. Never raises:
        a malformed, truncated or empty document is reported, because the
        caller is a hook handler.
    """
    fields, body = split_document(text)

    if fields is None:
        return (
            ProvenanceProblem(
                reason=(
                    "this body carries no hooks-daemon provenance header, so it was not "
                    f"produced by `{GENERATOR_COMMAND}`. Generate the report with that "
                    "command and file the file it writes — a hand-written body is how "
                    "client paths, config and log excerpts reach a PUBLIC tracker that "
                    "cannot retract them."
                )
            ),
        )

    problems: list[ProvenanceProblem] = []
    for required in (_FIELD_VERSION, _FIELD_GENERATED_AT, _FIELD_DIGEST):
        if not fields.get(required):
            problems.append(
                ProvenanceProblem(
                    reason=(
                        f"the provenance header is missing `{required}`. Regenerate the "
                        f"report with `{GENERATOR_COMMAND}` rather than repairing the "
                        "header by hand."
                    )
                )
            )

    recorded = fields.get(_FIELD_DIGEST, "")
    if recorded and not _SHA256_RE.match(recorded):
        problems.append(
            ProvenanceProblem(
                reason=(
                    f"`{_FIELD_DIGEST}` is not a sha256 digest. Regenerate the report with "
                    f"`{GENERATOR_COMMAND}`."
                )
            )
        )
    elif recorded and recorded != body_digest(body):
        problems.append(
            ProvenanceProblem(
                reason=(
                    "the body has changed since it was generated, so what the header "
                    "vouches for is not what is about to be filed. Put the extra detail "
                    "into the reproduction and regenerate with "
                    f"`{GENERATOR_COMMAND}` — editing a generated report by hand is how "
                    "client material gets in after the checks have run."
                )
            )
        )

    if not body.strip():
        problems.append(
            ProvenanceProblem(
                reason=(
                    "the report has a provenance header and no body. Regenerate it with "
                    f"`{GENERATOR_COMMAND}`."
                )
            )
        )

    return tuple(problems)
