"""One-shot human approval for closing a plan (Plan 00367).

``plan_workflow.close_requires_human_approval`` is OFF by default: a fully
completed plan is closed by the agent that completed it. A project that turns
it on gets a real gate, and this module is the human's route through it: a
marker file under the daemon's untracked directory, keyed by plan number,
that the very next terminal status flip of THAT plan consumes.

The marker is deliberately outside git (nothing to commit, nothing to leak
into a client's history) and deliberately one-shot (an approval is for one
closing, not a standing waiver). It is pydantic-free like the rest of this
package: the handler and the CLI both call it, and neither needs the model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME
from claude_code_hooks_daemon.utils.one_shot_approval import (
    MARKER_SUFFIX,
    OneShotApprovalStore,
)

#: Directory under the daemon's untracked dir that holds the markers.
APPROVAL_SUBDIR: Final[str] = "plan-close-approvals"
#: Marker filename suffix; the stem is the zero-padded plan number.
APPROVAL_SUFFIX: Final[str] = MARKER_SUFFIX

_PLAN_NUMBER_WIDTH: Final[int] = 5
_FOLDER_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-")

_STORE: Final[OneShotApprovalStore] = OneShotApprovalStore(APPROVAL_SUBDIR)


def format_plan_number(plan_number: int) -> str:
    """``42`` -> ``00042``, the form every plan surface prints."""
    return f"{plan_number:0{_PLAN_NUMBER_WIDTH}d}"


def approval_marker_path(untracked_dir: Path, plan_number: int) -> Path:
    """Where the one-shot approval for ``plan_number`` lives."""
    return _STORE.path(untracked_dir, format_plan_number(plan_number))


def record_approval(untracked_dir: Path, plan_number: int) -> Path:
    """Write the approval marker (creating its directory) and return its path."""
    return _STORE.record(untracked_dir, format_plan_number(plan_number))


def consume_approval(untracked_dir: Path, plan_number: int) -> bool:
    """Remove the marker for ``plan_number``; True if there was one to consume."""
    return _STORE.consume(untracked_dir, format_plan_number(plan_number))


def plan_number_from_plan_doc_path(file_path: Path, plan_dir_rel: str) -> int | None:
    """Plan number from the ``NNNNN-name/PLAN.md`` folder under the plan dir.

    The folder name is the authority (not the document's title line): it is
    what the archive move, the index row and the counter all key on, and it
    is present even when the content being written has no title yet. A
    ``PLAN.md`` anywhere under the plan directory qualifies -- active root or
    an archive subdirectory -- so a human's approval is honoured wherever the
    folder sits at the moment of the flip.
    """
    if file_path.name != PLAN_DOC_FILENAME:
        return None
    normalised = str(file_path).replace("\\", "/")
    if f"/{plan_dir_rel.strip('/')}/" not in normalised:
        return None
    match = _FOLDER_NUMBER_RE.match(file_path.parent.name)
    return int(match.group(1)) if match else None
