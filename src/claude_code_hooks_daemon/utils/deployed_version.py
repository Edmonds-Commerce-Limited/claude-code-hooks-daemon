"""The version the project's TRACKED daemon assets were deployed from.

`.claude/hooks-daemon/` is gitignored, so the installed clone is per-checkout and
disposable. The assets it deploys — hooks, settings, skills, config, the
`CLAUDE.md` block — are TRACKED, and they are the reviewed truth. When the two
disagree the daemon simply refuses to start, which is GitHub issue #38: a whole
session with every safety handler inactive under ``--dangerously-skip-permissions``.

**A machine-readable marker for this already exists**, which the issue concluded
it did not. `docs_generator` writes a header into the tracked
`.claude/HOOKS-DAEMON.md`::

    > Generated on 2026-09-11 (v3.63.0) by `generate-docs`. Regenerate: ...

The issue's author grepped for ``daemon_version``/``installed_version`` and found
nothing, because the version is spelled as prose rather than as a key. It is
still perfectly parseable, and `generated_doc_hand_edit` was already parsing it —
so this module is where that pattern now lives, and that check imports it from
here. A second parser for one line is how two parsers drift apart, and the one
that quietly stops matching is the one nobody notices.

Every read failure returns ``None`` rather than raising. A project that has never
generated the doc, or whose doc predates the header, is in a NORMAL state — not
an error — and a caller's only sensible response to any of those is the same:
say nothing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Repo-relative location of the tracked generated doc carrying the marker.
#: This is the default `generated_docs` manifest entry; a project that moves it
#: loses the marker, which is a documented limit rather than a silent one.
TRACKED_VERSION_DOC_REL_PATH: Final[str] = ".claude/HOOKS-DAEMON.md"

#: Mirrors the exact header ``docs_generator._render_header()`` emits. Narrow on
#: purpose: this is the ONE marker shape recognised, and any other wording is
#: skipped silently rather than guessed at.
VERSION_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"> Generated on \d{4}-\d{2}-\d{2} \(v(\d+\.\d+\.\d+)\) by"
)


def version_marker_in(text: str) -> str | None:
    """The version recorded in ``text``'s generated-doc header, if present."""
    match = VERSION_MARKER_RE.search(text)
    return match.group(1) if match else None


def read_tracked_deployed_version(project_root: Path) -> str | None:
    """The version the project's tracked assets were deployed from.

    ``None`` when the doc is absent, unreadable, or carries no marker — all
    normal states for a project, and all meaning the same thing to a caller:
    there is nothing to compare against, so say nothing.
    """
    doc = project_root / TRACKED_VERSION_DOC_REL_PATH
    if not doc.is_file():
        return None
    try:
        text = doc.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.debug("tracked deployed version: %s unreadable: %s", doc, e)
        return None
    return version_marker_in(text)
