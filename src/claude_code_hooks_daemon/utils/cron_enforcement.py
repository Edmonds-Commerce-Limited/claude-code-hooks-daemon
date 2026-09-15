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


def _normalised_prompt_prefix(prompt: str) -> str:
    """The declared prompt, truncated to the same cap the wire delivers."""
    return prompt[:PROMPT_DELIVERY_CAP]


def _strip_truncation_marker(prompt: str) -> str:
    """The delivered prompt with any trailing truncation marker removed."""
    return _TRUNCATION_MARKER_RE.sub("", prompt)


def cron_is_asserted(declared: PersistentCronConfig, session_crons: list[SessionCron]) -> bool:
    """Whether ``declared`` has a matching entry among ``session_crons``.

    Args:
        declared: One of this project's ``persistent_crons`` jobs.
        session_crons: The session's actual crons (never ``None`` -- resolve
            the conditional-absence case with ``parse_session_crons`` first).

    Returns:
        True if some entry shares ``declared``'s schedule and its prompt
        matches once both sides are normalised to ``PROMPT_DELIVERY_CAP``
        (constraint 2) -- never by ``id``, which the contract does not
        guarantee round-trips (constraint 3).
    """
    declared_prefix = _normalised_prompt_prefix(declared.prompt)
    return any(
        actual.schedule == declared.schedule
        and _strip_truncation_marker(actual.prompt) == declared_prefix
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
    lines.append(
        "Once CronCreate has been called for every job above, stopping is safe "
        "again."
    )
    return "\n".join(lines)
