"""Check ``plan-doc-size`` (Stage 1, tiered advise -> block; Plan 00190).

A plan document is read IN FULL at the start of every session that touches
the plan, so its size is a recurring context-budget cost paid before any work
begins. A journal is not read whole — it is tailed, grepped, or handed to a
sub-agent for archaeology — which is exactly why it may grow without limit
and this check never touches it.

That asymmetry is the whole design. The thresholds come from read cost
(:class:`PlanDocSizeLimits`), the scope comes from the shared classifier
(so journals and the plan index are exempt by construction), and the
remediation names TWO remedies because most oversized plans are over-scoped
rather than journal-polluted.

Guards keep the block from ever trapping an agent — only an edit that makes
the problem WORSE can be denied:

- **Shrinking edits are silent** — that is the remedy in progress, and
  otherwise an oversized plan could never be refactored downwards.
- **Non-growing edits never block.** Ticking a checkbox on an already-oversized
  plan is a same-size edit; denying it would leave the agent unable to update a
  plan they are legitimately working. It still advises, so the size stays
  visible. The check exists to stop plans GROWING into logs.
- **Grandfathered plans only advise**, via ``legacy_plan_allowlist``.
- **An escape hatch** (``MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason>``) downgrades
  a block to advice for a plan that genuinely warrants the size.
"""

import re
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import edit_target, level_for_plan
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    PlanDocSizeLimits,
    Stage,
)

CHECK_ID: Final[str] = "plan-doc-size"

# An in-content escape hatch rather than an env var: a Write/Edit carries no
# shell command to prefix, and keeping the justification IN the file means it
# survives, is reviewable, and explains itself to the next reader.
_ESCAPE_HATCH_RE: Final[re.Pattern[str]] = re.compile(
    r"MUST_EXCEED_PLAN_SIZE_BECAUSE\s*[:=]\s*(?P<reason>.*)"
)
_HTML_COMMENT_CLOSE: Final[str] = "-->"

_TIER_ADVISORY: Final[str] = "advisory"
_TIER_WARNING: Final[str] = "warning"
_TIER_BLOCK: Final[str] = "block"

_BYTES_PER_TOKEN: Final[float] = 3.97

_REMEDY: Final[str] = (
    "Two remedies, and NEITHER is deletion: (1) RELOCATE the narrative — dated "
    "progress notes, incident write-ups, hand-off prose — into this plan's "
    "JOURNAL/ day-file, which is append-only and unbounded by design; or "
    "(2) SPLIT the plan if the task tree itself is the bulk, since an "
    "over-scoped plan is not fixed by better journalling. Keep PLAN.md lean, "
    "current and correct — history belongs in git and in JOURNAL/."
)

_ESCAPE_HATCH_HINT: Final[str] = (
    " If this plan genuinely warrants its size, record why in the file: "
    "`<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->`."
)


@dataclass(frozen=True)
class _Tier:
    """One threshold band. Ordered highest-first by the caller."""

    name: str
    max_bytes: int
    max_lines: int
    level: Level


def _tiers(limits: PlanDocSizeLimits) -> tuple[_Tier, ...]:
    """Tiers, highest first, so the first match is the most severe."""
    return (
        _Tier(_TIER_BLOCK, limits.block_bytes, limits.block_lines, Level.BLOCK),
        _Tier(_TIER_WARNING, limits.warning_bytes, limits.warning_lines, Level.ADVISE),
        _Tier(_TIER_ADVISORY, limits.advisory_bytes, limits.advisory_lines, Level.ADVISE),
    )


def _has_justified_escape_hatch(content: str) -> bool:
    """Whether the file declares a REASON for exceeding the limit.

    A bare marker is not an escape hatch — the point is the justification, so
    ``MUST_EXCEED_PLAN_SIZE_BECAUSE:`` with nothing after it (or only the HTML
    comment closer) does not count.
    """
    match = _ESCAPE_HATCH_RE.search(content)
    if match is None:
        return False
    reason = match.group("reason").strip()
    if reason.endswith(_HTML_COMMENT_CLOSE):
        reason = reason[: -len(_HTML_COMMENT_CLOSE)].strip()
    return bool(reason)


def _breached(tier: _Tier, byte_count: int, line_count: int) -> bool:
    """Either axis trips a tier; the threshold value itself is allowed."""
    return byte_count > tier.max_bytes or line_count > tier.max_lines


def _breached_limits(tier: _Tier, byte_count: int, line_count: int) -> str:
    """Describe ONLY the limit(s) actually exceeded.

    Citing both axes when one is comfortably under misstates the facts in the
    very message that is meant to explain the block.
    """
    parts = []
    if byte_count > tier.max_bytes:
        parts.append(f"{tier.max_bytes:,} bytes")
    if line_count > tier.max_lines:
        parts.append(f"{tier.max_lines:,} lines")
    return " and ".join(parts)


def _message(tier: _Tier, byte_count: int, line_count: int) -> str:
    tokens = round(byte_count / _BYTES_PER_TOKEN)
    size = f"{byte_count:,} bytes / {line_count:,} lines (~{tokens:,} tokens)"
    limit = _breached_limits(tier, byte_count, line_count)
    if tier.name == _TIER_BLOCK:
        return (
            f"PLAN.md is {size} — past the hard limit of {limit}. A plan this large "
            f"is re-read in full every session, so it taxes the context budget "
            f"before any work starts."
        )
    if tier.name == _TIER_WARNING:
        return (
            f"PLAN.md is {size} — well over the warning threshold of {limit}, and "
            f"approaching the hard limit at which edits are blocked. Act now rather "
            f"than at the block."
        )
    return (
        f"PLAN.md is {size} — over the advisory threshold of {limit}. Plans are read "
        f"in full every session; keep this one lean while it is still a small job."
    )


def _run(context: CheckContext) -> list[Finding]:
    limits = context.plan_doc_size
    if not limits.enabled:
        return []

    # Scope: PLAN.md only. edit_target() routes through the shared classifier,
    # so journals, the plan index and supporting docs are exempt by
    # construction rather than by a list this check has to maintain.
    target = edit_target(context)
    if target is None:
        return []

    content = context.file_content
    assert content is not None  # narrowed by edit_target succeeding

    # A shrinking edit is the remedy in progress — never penalise it, or an
    # oversized plan becomes impossible to refactor down.
    before = context.file_content_before
    if before is not None and len(content) < len(before):
        return []
    # An edit that does not GROW the file makes nothing worse. Ticking a
    # checkbox on an already-oversized plan is same-size, and denying it would
    # trap the agent in a plan they cannot update. Such edits still advise, so
    # the size stays visible, but they never block.
    grows = before is None or len(content) > len(before)

    byte_count = len(content.encode("utf-8"))
    line_count = content.count("\n")

    breached = next(
        (tier for tier in _tiers(limits) if _breached(tier, byte_count, line_count)),
        None,
    )
    if breached is None:
        return []

    level = breached.level if grows else Level.ADVISE
    remediation = _REMEDY
    if level is Level.BLOCK:
        # Grandfathered plans and a declared justification both downgrade the
        # block; the finding still surfaces so the size stays visible.
        if _has_justified_escape_hatch(content):
            level = Level.ADVISE
        else:
            level = level_for_plan(context, target.plan_number)
            remediation = _REMEDY + _ESCAPE_HATCH_HINT

    return [
        Finding(
            check_id=CHECK_ID,
            level=level,
            message=_message(breached, byte_count, line_count),
            remediation=remediation,
            path=target.rel_path,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    # No 00144 audit-catalogue sin: the plan-as-journal failure mode this
    # defends against was identified by Plan 00190, after that catalogue.
    sins=(),
    run=_run,
)
