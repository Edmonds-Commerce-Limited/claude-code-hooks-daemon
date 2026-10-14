"""The workable-issues cache (Plan 00470 Phase 7).

An idle stop that defers workable issues to the next cron tick is refused on
facts. The Stop hook may not call GitHub, so the decision points that already
talk to it (``work-queue done`` and ``issue-validity --list-eligible``) leave a
small file in the daemon's untracked state directory: the WORKABLE issue
numbers and when they were recorded. The Stop gate reads only that file.

**Workable** is *eligible* (``issue-validity``'s author rule) and not labelled
``agent-needs-human``. Labels arrive in the same ``gh issue list`` call the
eligibility check already makes.

Every read is total: a missing or malformed file is "no cache", which the gate
treats as "stand aside".
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.github_issue_validity import (
    AuthorWhitelistCheck,
    IssueValidityService,
    ValidityReport,
    Verdict,
)

logger = logging.getLogger(__name__)

WORKABLE_ISSUES_FILENAME: Final[str] = "workable-issues.json"

#: An issue carrying this label waits on a human; the loop must not start it.
NEEDS_HUMAN_LABEL: Final[str] = "agent-needs-human"

_KEY_NUMBERS: Final[str] = "numbers"
_KEY_RECORDED_AT: Final[str] = "recorded_at"


@dataclass(frozen=True, slots=True)
class WorkableIssues:
    """The workable issue numbers as of ``recorded_at`` (epoch seconds)."""

    numbers: tuple[int, ...]
    recorded_at: float

    def is_fresh(self, *, now: float, max_age_seconds: float) -> bool:
        """Whether the record is no older than ``max_age_seconds`` and not future-dated."""
        age = now - self.recorded_at
        return 0 <= age <= max_age_seconds


def workable_numbers(reports: Iterable[ValidityReport]) -> list[int]:
    """The issue numbers that are eligible and not waiting on a human."""
    return [
        report.number
        for report in reports
        if report.verdict is Verdict.VALID and NEEDS_HUMAN_LABEL not in report.labels
    ]


def write_workable(path: Path, numbers: Sequence[int], *, now: float) -> None:
    """Atomically write the cache.

    Raises:
        OSError: The directory cannot be created or the file cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {_KEY_NUMBERS: list(numbers), _KEY_RECORDED_AT: now}
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload))
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _parse(raw: object) -> WorkableIssues | None:
    if not isinstance(raw, dict):
        return None
    numbers = raw.get(_KEY_NUMBERS)
    recorded_at = raw.get(_KEY_RECORDED_AT)
    if not isinstance(numbers, list) or isinstance(recorded_at, bool):
        return None
    if not isinstance(recorded_at, (int, float)):
        return None
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
        return None
    return WorkableIssues(numbers=tuple(numbers), recorded_at=float(recorded_at))


def read_workable(path: Path) -> WorkableIssues | None:
    """The cache, or None when it is missing, unreadable or malformed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable workable-issues cache {path} reads as no cache (None), which makes the Stop gate stand aside",
            level=logging.DEBUG,
        )
        return None
    return _parse(raw)


def refresh_workable_cache(
    path: Path,
    service: IssueValidityService,
    approved: Sequence[str] | None,
    *,
    now: float,
) -> list[int]:
    """List open issues once, write the workable ones, return them.

    Raises:
        GhError: The listing failed; the cache is left as it was.
        OSError: The cache could not be written.
    """
    reports = service.check_open_issues([AuthorWhitelistCheck(approved)])
    numbers = workable_numbers(reports)
    write_workable(path, numbers, now=now)
    return numbers
