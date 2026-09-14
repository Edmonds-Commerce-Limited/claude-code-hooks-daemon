"""Make a diagnostic report publishable without losing what makes it useful.

Every route to a hooks-daemon bug report assembles the client's own config,
environment and absolute paths, and then points the reporter at a tracker that
is PUBLIC. A public issue cannot be retracted by editing or deleting it, so the
cost of leaking here is borne by the CLIENT and is permanent, while the cost of
over-scrubbing is one round-trip asking for more detail. The two are not
comparable, and this module is written accordingly.

Three rules carry the design:

``the project root is rewritten, not the path below it``
    `.claude/hooks-daemon/…` and `src/claude_code_hooks_daemon/…` ARE the
    substance of a daemon bug report — a report that lost them would be
    unusable. Only the PREFIX identifies anyone, so only the prefix is replaced.
    Judging what a path IS rather than what it looks like is the same rule that
    Plan 00401 learned the hard way on its own path matching.

``the most specific prefix is applied first``
    A project root usually sits inside `$HOME`. Scrubbing `$HOME` first turns
    `/home/j/acme/x.py` into `<home>/acme/x.py`, after which the project-root
    rule is looking for a literal that no longer exists — and the project name
    survives into the published report.

``a short value is never scrubbed``
    Replacing every occurrence of a two-character hostname would shred the
    document into placeholders. The length guard is what makes this safe to run
    over a whole report rather than over hand-picked fields, which is the
    property that lets callers apply it as a final step and not forget a field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

PROJECT_ROOT_PLACEHOLDER: Final[str] = "<project-root>"
HOME_PLACEHOLDER: Final[str] = "<home>"
HOSTNAME_PLACEHOLDER: Final[str] = "<hostname>"
REMOTE_PLACEHOLDER: Final[str] = "<git-remote>"

#: Shortest value worth replacing. A hostname of `ci` or a root of `/x` appears
#: inside ordinary English and inside unrelated paths, so substituting it
#: everywhere destroys more than it protects. Four is long enough that a
#: collision is deliberate rather than incidental.
MIN_SCRUBBABLE_LENGTH: Final[int] = 4


def _replace(text: str, value: str | None, placeholder: str) -> str:
    """Substitute ``value`` everywhere, or leave ``text`` alone.

    ``None`` and the empty string both mean "the caller does not know this" —
    and an empty needle would otherwise match between every character in the
    document.
    """
    if not value or len(value) < MIN_SCRUBBABLE_LENGTH:
        return text
    return text.replace(value, placeholder)


def scrub_report(
    text: str,
    *,
    project_root: Path,
    home: Path | None = None,
    hostname: str | None = None,
    git_remote: str | None = None,
    secret_terms: tuple[str, ...] = (),
) -> str:
    """Remove the client's identity from a diagnostic report.

    Args:
        text: The assembled report.
        project_root: The client's checkout. Its path is replaced wherever it
            appears; everything below it is preserved.
        home: The user's home directory, whose name is usually their username.
        hostname: The machine name, which in a corporate estate frequently
            names the client and the environment.
        git_remote: The remote URL, which names the client and often a private
            host.
        secret_terms: Terms from the project's gitignored secret word list.
            Applied unconditionally and last, because that layer is the one a
            project has explicitly declared must never appear anywhere.

    Returns:
        The report with each known identifier replaced by a placeholder. Safe
        to apply to a whole document: a value shorter than
        :data:`MIN_SCRUBBABLE_LENGTH` is skipped rather than substituted.
    """
    # Most specific prefix first — see the module docstring. Reversing these two
    # lines silently leaks the project name.
    scrubbed = _replace(text, str(project_root), PROJECT_ROOT_PLACEHOLDER)
    scrubbed = _replace(scrubbed, str(home) if home is not None else None, HOME_PLACEHOLDER)
    scrubbed = _replace(scrubbed, git_remote, REMOTE_PLACEHOLDER)
    scrubbed = _replace(scrubbed, hostname, HOSTNAME_PLACEHOLDER)

    # Imported lazily, and that is deliberate rather than incidental: with no
    # module-level package import, this file can be loaded BY PATH with no
    # package resolution at all. `scripts/debug_info.py` needs exactly that —
    # it must produce a scrubbed report on a bare interpreter, when the daemon's
    # dependencies are missing or broken, which is precisely when someone is
    # generating a bug report.
    #
    # Not guarded by length: the secret word list is a deliberate declaration,
    # and `redact_text` owns the matching rules (slug and separator variants).
    if secret_terms:
        from claude_code_hooks_daemon.utils.secret_redaction import redact_text

        scrubbed = redact_text(scrubbed, secret_terms)
    return scrubbed
