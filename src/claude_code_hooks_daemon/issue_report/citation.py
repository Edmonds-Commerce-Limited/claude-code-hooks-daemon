"""Verify the source citation a report claims to have read (Plan 00403 Task 3.3).

The owner asked that a reporter "can and should read the hooks daemon source"
before concluding there is a defect. Nothing can verify that somebody READ
something — but a citation is a checkable artefact, and this is the move that
turns the unverifiable claim into one, the same way the remote-docs provenance
frontmatter does for a vendored document.

What it buys is worth stating precisely, because it is not honesty policing:

``a citation that does not resolve was read somewhere else``
    A ``file:line`` that does not exist in the INSTALLED version means the
    reporter was looking at a different version, at a fork, or at nothing. All
    three change how a maintainer should read the rest of the report, and none
    of them is visible from the citation alone.

``it is a lower bound, not a proof``
    A resolving citation proves the line exists, not that anyone understood it.
    That is fine. The cost of a wrong citation is a misleading report, and
    catching the wrong ones is worth more than pretending to catch everything.

Never raises. The caller is a report generator, and an exception there loses
the report rather than improving it — so a malformed citation, a traversal, a
directory and an unreadable file are all REPORTED.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Citations must name the daemon's own source tree. Reading your own code is
#: not reading the daemon's, and the report is about the daemon.
_SOURCE_PREFIX: Final[str] = "src/claude_code_hooks_daemon/"

_CITATION_RE: Final[re.Pattern[str]] = re.compile(r"\A(?P<path>[^:]+):(?P<line>\d+)\Z")

_SHAPE_HINT: Final[str] = (
    "Cite it as `file:line` relative to the daemon root, e.g. "
    "`src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py:210`."
)


@dataclass(frozen=True)
class CitationVerdict:
    """Whether a claimed source citation resolves in the installed version.

    Attributes:
        resolved: True only when the file exists under the daemon's source tree
            and is at least ``line`` lines long.
        detail: What to do about it. A bare "does not resolve" is not
            actionable; the length of the file, or the version question, is.
    """

    resolved: bool
    detail: str


def _refuse(detail: str) -> CitationVerdict:
    return CitationVerdict(resolved=False, detail=detail)


def check_source_citation(citation: str, *, daemon_root: Path) -> CitationVerdict:
    """Resolve a ``file:line`` citation against the installed daemon source.

    Args:
        citation: The claimed citation, relative to the daemon root.
        daemon_root: The installed daemon's root — this repository in
            self-install, ``.claude/hooks-daemon/`` in a client.

    Returns:
        A :class:`CitationVerdict`. Never raises.
    """
    text = citation.strip()
    if not text:
        return _refuse(f"No source citation was given. {_SHAPE_HINT}")

    match = _CITATION_RE.match(text)
    if match is None:
        return _refuse(f"{text!r} is not a source citation. {_SHAPE_HINT}")

    line = int(match.group("line"))
    if line < 1:
        return _refuse(f"Line numbers start at 1, so {line} cannot be cited. {_SHAPE_HINT}")

    relative = match.group("path")
    if not relative.startswith(_SOURCE_PREFIX):
        return _refuse(
            f"{relative!r} is not daemon source. A report about the daemon has to cite the "
            f"daemon's own code, under `{_SOURCE_PREFIX}` — reading your own project's code "
            f"answers a different question. {_SHAPE_HINT}"
        )

    # Resolved and re-checked against the root: `src/claude_code_hooks_daemon/
    # ../../../etc/passwd` satisfies the prefix test as TEXT while pointing
    # outside the tree entirely, so the prefix alone cannot be the containment
    # check.
    root = daemon_root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root / "src" / "claude_code_hooks_daemon"):
        return _refuse(f"{relative!r} resolves outside the daemon's source tree. {_SHAPE_HINT}")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _refuse(
            f"`{relative}` could not be read in the installed version ({exc.strerror}). "
            "That usually means the report was written against a different version of the "
            "daemon — check which version you are running with `hooks-daemon status`."
        )

    total = len(content.splitlines())
    if line > total:
        return _refuse(
            f"`{relative}` has {total} lines in the installed version, so line {line} does "
            "not exist. That usually means the source was read at a different version — "
            "re-read it in the installed one and cite the line you actually acted on."
        )

    return CitationVerdict(
        resolved=True,
        detail=f"`{relative}:{line}` resolves in the installed version ({total} lines).",
    )
