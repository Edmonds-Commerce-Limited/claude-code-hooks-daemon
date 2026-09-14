"""Where an upstream issue report is filed (Plan 00403).

One constant and one command builder, because two surfaces have to agree about
which repository a defect report goes to: the CLI PRINTS the command to run,
and :mod:`...handlers.pre_tool_use.issue_filing_gate` decides whether a command
points at us. A gate that refused the command its own tooling printed would be
unsatisfiable, which is the failure ``reference_repo_freshness`` had to be
designed around — so neither side spells the repository out for itself.

The defect that produced this module is worth keeping, because it is invisible
in the daemon's own checkout. The CLI printed::

    gh issue create --body-file untracked/issue-reports/<report>.md

``gh`` resolves the target from the working directory when no ``--repo`` is
given. In a self-install that is this repository and the command is right; in a
CLIENT project — the only place the generator matters — it files a hooks-daemon
defect on the CLIENT'S OWN tracker, and the filing gate never engages, because
the gate judges the repository a command targets. Both halves fail in the same
direction, and both only in the environment nobody tests by hand.
"""

from __future__ import annotations

import shlex
from typing import Final

#: This project's tracker, lowercase, in the ``owner/name`` form ``gh --repo``
#: takes. Lowercase because it is the normalisation target: every other
#: spelling ``gh`` accepts — an https URL, an ssh URL, the scp-like form — is
#: reduced to this before comparison.
UPSTREAM_REPO_SLUG: Final[str] = "edmonds-commerce-limited/claude-code-hooks-daemon"

#: The owner/name pair as GitHub displays it. Used where the text is READ by a
#: person rather than compared, so a report does not carry a mangled repo name.
UPSTREAM_REPO_DISPLAY: Final[str] = "Edmonds-Commerce-Limited/claude-code-hooks-daemon"


def filing_command(report_path: str) -> str:
    """The exact ``gh`` command that files ``report_path`` upstream.

    Args:
        report_path: Where the generated document was written.

    Returns:
        A runnable command. ``--repo`` is always present: without it the target
        comes from the working directory, which in a client project is the
        client's own repository.
    """
    return f"gh issue create --repo {UPSTREAM_REPO_DISPLAY} --body-file {shlex.quote(report_path)}"
