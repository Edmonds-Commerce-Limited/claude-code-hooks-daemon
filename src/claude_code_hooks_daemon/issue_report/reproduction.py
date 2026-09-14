"""The minimal synthetic reproduction rule (Plan 00403 Task 2.2).

Every other field in an upstream issue report is assembled by the generator
from values it controls. The reproduction is the ONE place a client's own
material can enter, because a human or an agent writes it in free text — so
this is the load-bearing rule of the whole redaction design.

A reproduction authored against invented fixtures under ``untracked/scratch/``
cannot leak, removes most of the remaining surface in a single move, and
independently produces a better issue: a maintainer can actually run it.

Three rules carry the design.

``daemon paths are ours; client paths are not``
    ``.claude/hooks-daemon/…`` and ``src/claude_code_hooks_daemon/…`` ARE the
    substance of a daemon bug report, and one that could not name the handler's
    source file would be useless. What identifies somebody is the project root
    that PREFIXES a path, which is why an absolute path is refused whatever it
    points at — the daemon's own directory name cannot redeem a prefix that
    carries a username.

``the escape waives the requirement, not the checks``
    A bug that genuinely cannot be reproduced synthetically is still
    reportable. The report says so explicitly, with the sentinel, and carries
    no client data instead. What the sentinel waives is the requirement to HAVE
    steps; it is not a free-text field that skips inspection.

``over-refusing costs a rewrite; under-refusing cannot be undone``
    The tracker is public and an issue cannot be retracted, so where a judgement
    is close this module refuses. That only stays workable because the refusal
    names the rule and the directory a reproduction may use — a refusal nobody
    can act on just gets worked around.

Deliberately NOT refused, and worth stating rather than leaving to be
discovered: a BARE filename with no directory (``PayrollExporter.php``). It
carries no project root and so identifies no one, but it can still name a
client's domain concept. Refusing it would also refuse ``README.md``,
``package.json`` and ``conftest.py``, which are exactly what a legitimate
reproduction cites — so the noise would buy very little. What actually
addresses this is the instruction to build the reproduction synthetically in
the first place, which is a rule about how the report is WRITTEN rather than a
filter over what it contains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Where a synthetic reproduction's fixtures live. Gitignored and inside the
#: working tree, so a fixture survives a container restart without ever
#: reaching review — the same directory `project_containment` already directs
#: scratch work to.
SCRATCH_PREFIX: Final[str] = "untracked/scratch/"

#: Declares that no synthetic reproduction exists. Must be the FIRST thing in
#: the reproduction, so that merely discussing the possibility cannot waive the
#: requirement.
CANNOT_REPRODUCE_SENTINEL: Final[str] = "CANNOT-REPRODUCE-SYNTHETICALLY"

#: Path prefixes that are the DAEMON's, identical in every install and
#: therefore carrying nothing about who is running it. `.claude/hooks-daemon/`
#: is where a client install lives; `src/claude_code_hooks_daemon/` is this
#: repository's own tree; the two config files are named the same everywhere
#: (their CONTENTS are the client's, and the generator never copies those).
_DAEMON_PREFIXES: Final[tuple[str, ...]] = (
    SCRATCH_PREFIX,
    ".claude/hooks-daemon/",
    ".claude/hooks-daemon.yaml",
    ".claude/hooks-daemon.env",
    ".claude/project-handlers/",
    "src/claude_code_hooks_daemon/",
    "tests/",
    "bin/hooks-daemon",
    "scripts/",
)

#: The only host a reproduction may link to. A URL is a path to a machine, and
#: an internal tracker's hostname names the client and often the environment
#: too. Anything else can be described in words.
_ALLOWED_URL_HOST: Final[str] = "github.com"

_URL_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:https?|ftp|ssh|git)://(?P<host>[^/\s]+)")

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[^\s'\"`,;()\[\]{}<>]+")

#: A Windows path: a drive letter (`C:\Users\…`) or a UNC share
#: (`\\server\share`). Claude Code runs on Windows, and these carry a username
#: or a hostname exactly as their POSIX equivalents do — but every other rule
#: here is built around `/`, so without this they pass unexamined.
_WINDOWS_PATH_RE: Final[re.Pattern[str]] = re.compile(r"\A(?:[A-Za-z]:[\\/]|\\\\[^\\]+)")

#: A path segment must plausibly be a filename: a dot-extension, a dot-prefix,
#: or a known directory name. Without this, "allow/deny" reads as a path.
_LOOKS_LIKE_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^[~/.])|(?:/\.)|(?:\.[A-Za-z0-9]{1,8}(?:[:/]|$))|(?:^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/)"
)


@dataclass(frozen=True)
class ReproductionProblem:
    """One reason a reproduction cannot be published.

    ``offending`` is echoed back so the author can find what to change, and is
    safe to show BECAUSE it never leaves the client's machine — this check runs
    locally, before anything is filed.
    """

    offending: str
    reason: str


def _is_url(token: str) -> bool:
    return bool(_URL_RE.match(token))


def _url_problem(token: str) -> ReproductionProblem | None:
    match = _URL_RE.match(token)
    if match is None:
        return None
    host = match.group("host").lower()
    if host == _ALLOWED_URL_HOST or host.endswith(f".{_ALLOWED_URL_HOST}"):
        return None
    return ReproductionProblem(
        offending=token,
        reason=(
            f"a URL to {host!r} names a machine, and an internal host names the client. "
            f"Only {_ALLOWED_URL_HOST} links are allowed; describe anything else in words."
        ),
    )


def _looks_like_a_path(token: str) -> bool:
    """Is this token a path rather than prose that happens to contain a slash?

    Deliberately narrow. "and/or", "allow/deny" and "100/50" all contain a
    slash and none of them is a path, so a token has to carry some other mark
    of being one: a leading ``/``, ``~`` or ``.``; a dot-directory inside it; a
    file extension; or three or more segments.
    """
    if _WINDOWS_PATH_RE.match(token):
        return True
    if "/" not in token and not token.startswith("~"):
        return False
    return bool(_LOOKS_LIKE_PATH_RE.search(token))


def _path_problem(token: str) -> ReproductionProblem | None:
    if _WINDOWS_PATH_RE.match(token):
        return ReproductionProblem(
            offending=token,
            reason=(
                "a Windows drive or UNC path names the user's account or a host. "
                f"Reproduce against a fixture under {SCRATCH_PREFIX} and name it "
                "relatively, with forward slashes."
            ),
        )
    if token.startswith("/"):
        return ReproductionProblem(
            offending=token,
            reason=(
                "an absolute path carries the project root, and usually the username with "
                f"it. Reproduce against a fixture under {SCRATCH_PREFIX} and name it "
                "relatively."
            ),
        )
    if token.startswith("~"):
        return ReproductionProblem(
            offending=token,
            reason=(
                "a home-relative path names the user's account. Reproduce against a "
                f"fixture under {SCRATCH_PREFIX} instead."
            ),
        )
    normalised = token.removeprefix("./")
    if normalised.startswith(_DAEMON_PREFIXES):
        return None
    return ReproductionProblem(
        offending=token,
        reason=(
            "this path is the client's own code, not the daemon's, so it cannot be "
            f"published. Build a fixture under {SCRATCH_PREFIX} that reproduces the "
            "behaviour, or declare "
            f"{CANNOT_REPRODUCE_SENTINEL} if the bug genuinely resists that."
        ),
    )


def _declares_no_reproduction(text: str) -> bool:
    """Only a reproduction that OPENS with the sentinel is making the claim.

    Matching it anywhere would mean that merely discussing the possibility —
    "I wondered whether this was a CANNOT-REPRODUCE-SYNTHETICALLY situation" —
    silently waived the requirement.
    """
    return text.lstrip().startswith(CANNOT_REPRODUCE_SENTINEL)


def check_reproduction(text: str) -> tuple[ReproductionProblem, ...]:
    """Every reason this reproduction cannot go into a public issue.

    Args:
        text: The reproduction as written, in free text.

    Returns:
        An empty tuple when the reproduction is publishable, otherwise one
        problem per distinct offending token. ALL problems are returned rather
        than the first, because an author who fixes one refusal at a time
        learns the rule one refusal at a time.
    """
    problems: list[ReproductionProblem] = []
    seen: set[str] = set()

    for token in _TOKEN_RE.findall(text):
        if token in seen:
            continue
        problem = _url_problem(token) if _is_url(token) else None
        if problem is None and not _is_url(token) and _looks_like_a_path(token):
            problem = _path_problem(token)
        if problem is not None:
            seen.add(token)
            problems.append(problem)

    # Checked after the path rules, so a leak is never hidden behind one of
    # these structural messages.
    declares_none = _declares_no_reproduction(text)

    if not declares_none and CANNOT_REPRODUCE_SENTINEL in text:
        problems.append(
            ReproductionProblem(
                offending=CANNOT_REPRODUCE_SENTINEL,
                reason=(
                    "this declaration must be the FIRST thing in the reproduction. "
                    "Buried mid-text it is ambiguous whether the report is claiming no "
                    "reproduction exists or merely discussing the possibility, and a "
                    "maintainer scanning for the token cannot tell which. Move it to the "
                    "start, or remove it."
                ),
            )
        )

    if not declares_none and not text.strip():
        problems.append(
            ReproductionProblem(
                offending="",
                reason=(
                    "a reproduction is required. Build a minimal synthetic one under "
                    f"{SCRATCH_PREFIX}, or state {CANNOT_REPRODUCE_SENTINEL} as the first "
                    "thing in this field and say what makes it resist reproduction."
                ),
            )
        )

    return tuple(problems)
