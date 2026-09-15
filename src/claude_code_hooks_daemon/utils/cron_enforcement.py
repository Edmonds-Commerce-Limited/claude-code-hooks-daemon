"""Stop/SubagentStop cron-enforcement primitives (Plan 00416 Task 1.1).

``persistent_cron_assertor`` (SessionStart) can only DECLARE what a project
wants and instruct a ``CronList`` reconcile -- ``session_crons`` is not
delivered to ``SessionStart``, so the daemon has no way to VERIFY anything
that early. It IS delivered to ``Stop`` and ``SubagentStop``
(``contracts/claude-code-hooks/Stop.json``), which is what lets the teeth in
this module exist: compare declared (``persistent_crons``) against actual
(``session_crons``) and report what never got created.

Three contract constraints, established from the vendored contract rather
than guessed, shape every function here:

1. ``session_crons`` is CONDITIONAL, not merely optional-with-a-sane-default.
   An ABSENT field means "no information" and must never be read as "no
   crons exist" -- ``parse_session_crons`` returns ``None`` for absent,
   distinct from the empty list a present-but-empty field parses to.
2. ``prompt`` is delivered CAPPED at ``PROMPT_DELIVERY_CAP`` characters with
   an in-string truncation marker, so a declared prompt longer than the cap
   (this project's own ``issue-sdlc`` job) can never equal the delivered
   value by exact string comparison. ``cron_is_asserted`` normalises both
   sides to the cap instead.
3. Matching is on ``schedule`` plus the normalised ``prompt`` -- never on
   ``id``. The daemon's declaration carries a stable id, but nothing in the
   contract guarantees a session's own ``CronCreate`` call echoed that id
   back into ``session_crons``.
4. The delivered ``prompt`` is LAYOUT-UNSTABLE, and this one is not from the
   contract -- it was measured after the first three shipped and the handler
   still blocked every stop (ledger 00419 N4). A declared prompt reaches
   ``CronCreate`` only by being rendered into a SessionStart advisory and
   retyped by an agent, and that round trip re-flows it: this project's own
   576-character declaration arrived as 580 characters with blank lines
   inserted, untruncated. Matching therefore compares the WORDS.

The fourth is the one worth remembering when extending this module. The first
three each describe what the WIRE does to a field; none describes what the
round trip through a rendered advisory does to it, and that round trip is the
only way ``session_crons`` is ever populated. A delivery MECHANISM and a
delivery PATH are different things to reason about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.config.models import PersistentCronConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField

#: The delivered ``prompt`` (and, per the contract, ``description``/
#: ``command`` on other capped fields) is truncated to this many characters.
PROMPT_DELIVERY_CAP: Final[int] = 1000

#: Strips the in-string truncation marker Claude Code appends to a capped
#: field -- e.g. ``"... [+1200 chars]"``. Matches both a plain ASCII ellipsis
#: and a Unicode one (the contract's own prose renders it both ways across
#: sources), and tolerant of the exact whitespace around ``[+N chars]``,
#: since the wire format is documented, not pinned to a byte-for-byte example.
_TRUNCATION_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"(?:\.\.\.|…)\s*\[\+\d+\s*chars\]\s*$")


def _normalise_whitespace(prompt: str) -> str:
    """The prompt's WORDS, with every whitespace-only difference removed.

    The delivered prompt is not the declared prompt's bytes. It is that text
    after a round trip through a rendered advisory and an agent's
    ``CronCreate`` call, and that round trip re-flows it: a real ``Stop``
    capture showed this project's own ``issue-sdlc`` prompt arriving 4
    characters longer than declared, with blank lines inserted between
    paragraphs. Nothing had truncated it.

    That is not a transport quirk to special-case. The same capture showed the
    three live crons disagreeing with each other — one kept single newlines,
    two did not — so delivered whitespace is simply not a stable property and
    cannot be part of an identity test.

    So each line is stripped and blank lines are dropped. The WORDS all
    survive, which is what actually distinguishes one declared job from
    another; only the layout is discarded.
    """
    return "\n".join(line.strip() for line in prompt.splitlines() if line.strip())


@dataclass(frozen=True)
class SessionCron:
    """One entry from the Stop/SubagentStop ``session_crons`` field.

    ``recurring`` is deliberately not carried here: matching never reads it
    (see the module docstring's constraint 3), so keeping it out of this type
    means a caller cannot accidentally start depending on a field this
    module's comparison logic ignores.
    """

    id: str
    schedule: str
    prompt: str


def parse_session_crons(hook_input: dict[str, Any]) -> list[SessionCron] | None:
    """The session's actual crons, or ``None`` when there is no information.

    Args:
        hook_input: The Stop/SubagentStop event payload.

    Returns:
        ``None`` when ``session_crons`` is absent, ``null``, or not a list --
        all three are "no information", not "no crons exist" (constraint 1).
        Otherwise the parsed entries, skipping any malformed one rather than
        failing the whole parse: a single bad entry must not hide every
        other genuine cron from the comparison.
    """
    raw = hook_input.get(HookInputField.SESSION_CRONS)
    if not isinstance(raw, list):
        return None
    crons: list[SessionCron] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        cron_id = entry.get("id")
        schedule = entry.get("schedule")
        prompt = entry.get("prompt")
        if not isinstance(cron_id, str) or not isinstance(schedule, str):
            continue
        if not isinstance(prompt, str):
            continue
        crons.append(SessionCron(id=cron_id, schedule=schedule, prompt=prompt))
    return crons


def _strip_truncation_marker(prompt: str) -> str:
    """The delivered prompt with any trailing truncation marker removed."""
    return _TRUNCATION_MARKER_RE.sub("", prompt)


def _was_truncated(delivered: str, without_marker: str) -> bool:
    """Whether the wire cut this prompt short.

    The marker is the reliable signal. The length test behind it is a
    fallback for a delivery that caps without annotating -- the contract
    documents the marker but a byte-for-byte guarantee is not something to
    rely on for a check whose failure mode is blocking every stop.
    """
    return without_marker != delivered or len(without_marker) >= PROMPT_DELIVERY_CAP


def _prompts_match(declared: str, delivered: str) -> bool:
    """Whether two prompts are the same job, ignoring layout and truncation.

    Prefix matching is used ONLY when the delivered prompt was actually cut
    short. That restriction is what keeps the check honest: a genuinely
    shorter prompt is a different job, and accepting every prefix would make
    a one-line cron match a ten-line declaration.

    Truncation is applied before normalisation on purpose. The wire cuts the
    RE-RENDERED text, so the cap falls at a different point than it would in
    the declared text, and comparing normalised prefixes is the only form
    that survives both transformations at once.
    """
    without_marker = _strip_truncation_marker(delivered)
    delivered_norm = _normalise_whitespace(without_marker)
    declared_norm = _normalise_whitespace(declared)
    if _was_truncated(delivered, without_marker):
        return declared_norm.startswith(delivered_norm)
    return declared_norm == delivered_norm


def cron_is_asserted(declared: PersistentCronConfig, session_crons: list[SessionCron]) -> bool:
    """Whether ``declared`` has a matching entry among ``session_crons``.

    Args:
        declared: One of this project's ``persistent_crons`` jobs.
        session_crons: The session's actual crons (never ``None`` -- resolve
            the conditional-absence case with ``parse_session_crons`` first).

    Returns:
        True if some entry shares ``declared``'s schedule and its prompt is
        the same job once truncation (constraint 2) and layout are both
        normalised away -- never by ``id``, which the contract does not
        guarantee round-trips (constraint 3).

        ``schedule`` IS compared exactly, and that asymmetry is deliberate:
        the captured payload showed it arriving byte-identical to the
        declaration, and it is a five-field expression where any difference
        is a real difference. Only the prompt makes the round trip through a
        rendering that re-flows it.
    """
    return any(
        actual.schedule == declared.schedule and _prompts_match(declared.prompt, actual.prompt)
        for actual in session_crons
    )


def find_missing_crons(
    declared_jobs: list[PersistentCronConfig], session_crons: list[SessionCron]
) -> list[PersistentCronConfig]:
    """The declared jobs with no matching entry among ``session_crons``.

    Args:
        declared_jobs: This project's active ``persistent_crons`` jobs.
        session_crons: The session's actual crons.

    Returns:
        The subset of ``declared_jobs`` that ``cron_is_asserted`` could not
        find -- empty when every declared job is present.
    """
    return [job for job in declared_jobs if not cron_is_asserted(job, session_crons)]


def render_missing_crons_reason(missing: list[PersistentCronConfig]) -> str:
    """The Stop-block DENY reason naming the exact ``CronCreate`` to run.

    Args:
        missing: The declared jobs ``find_missing_crons`` reported absent.
            Must be non-empty -- callers only reach this when there is
            something to report.

    Returns:
        A message naming, per missing job, its id, schedule and prompt in
        full, so the agent can act without having to go looking for the
        declaration elsewhere.
    """
    plural = "job" if len(missing) == 1 else "jobs"
    lines = [
        f"DECLARED PERSISTENT CRON{'' if len(missing) == 1 else 'S'} MISSING "
        f"({len(missing)} {plural}) -- this session cannot end quietly while a "
        "declared cron was never created.",
        "",
        "Run CronCreate (recurring: true) for each job below, using the schedule "
        "and prompt exactly as given:",
        "",
    ]
    for job in missing:
        heading = f"  • {job.id}"
        if job.description:
            heading = f"{heading} — {job.description}"
        lines.append(heading)
        lines.append(f"    schedule (recurring): {job.schedule}")
        lines.append("    prompt:")
        lines.extend(f"      {line}" for line in job.prompt.splitlines() or [""])
    lines.append("")
    lines.append("Once CronCreate has been called for every job above, stopping is safe again.")
    return "\n".join(lines)
