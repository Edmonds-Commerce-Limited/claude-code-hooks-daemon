"""The version-currency rule, made mechanical (Plan 00403 Task 3.1).

The owner's rule, verbatim: a reporter "should ensure that they are running the
latest version but can report issues if on an older one and there is no changes
to the relevant system between current version and latest release".

That contains one genuine insight worth preserving rather than simplifying
away. Refusing every report from an older install would be easy to implement
and would silence most of the field; what actually matters is whether the
SUBSYSTEM the report names has changed since, because if it has not, the defect
is still live on the default branch and the report is as good as one filed from
the newest release.

So the question is answerable from the release notes for the versions in
between: they either mention the named subsystem or they do not. When they do,
the honest answer is "upgrade first" — the behaviour may already be gone. When
they do not, the report proceeds AND carries that finding, so a maintainer can
see the check ran instead of taking the version on trust.

Two failure directions are deliberately NOT symmetrical:

``ahead of the newest tag is fine``
    A contributor working on the default branch is ahead of the latest release,
    not behind it. Refusing them would silence exactly the people best placed
    to report.

``unable to check is a refusal, not a pass``
    An unparseable version or missing release notes means the question was
    never answered. Treating that as "answered, fine" is the failure mode this
    whole plan keeps finding: an unchecked thing and a checked-and-clean thing
    must never render the same.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from claude_code_hooks_daemon.install.version_parse import parse_version_tuple


@dataclass(frozen=True)
class CurrencyVerdict:
    """Whether an upstream report may proceed from this installed version.

    Attributes:
        may_report: False only when the check ANSWERED "upgrade first", or
            could not be answered at all.
        detail: The sentence the report carries, so the finding is visible to a
            maintainer rather than implied by the report's existence.
        versions_checked: The releases whose notes were read. Empty when the
            install is already current — there is nothing in between.
        mentions: The releases whose notes name the subsystem. Non-empty is
            exactly the refusal case.
    """

    may_report: bool
    detail: str
    versions_checked: tuple[str, ...] = ()
    mentions: tuple[str, ...] = ()


def _subsystem_pattern(subsystem: str) -> re.Pattern[str]:
    """Match a subsystem however it is written.

    A handler is `sed_blocker` in config, `sed-blocker` in a rule ID and "sed
    blocker" in prose, and release notes are prose. Matching only the config
    spelling would answer "no changes" for a release that rewrote it.
    """
    words = [word for word in re.split(r"[^A-Za-z0-9]+", subsystem) if word]
    if not words:
        return re.compile(r"(?!)")
    joined = r"[^A-Za-z0-9]*".join(re.escape(word) for word in words)
    return re.compile(joined, re.IGNORECASE)


def _versions_between(
    installed: tuple[int, ...], latest: str, notes: Mapping[str, str]
) -> list[str]:
    latest_tuple = parse_version_tuple(latest)
    between = [
        version for version in notes if installed < parse_version_tuple(version) <= latest_tuple
    ]
    return sorted(between, key=parse_version_tuple)


def assess_currency(
    *,
    installed: str,
    latest: str,
    subsystem: str,
    notes: Mapping[str, str],
) -> CurrencyVerdict:
    """Decide whether this installed version may file a report about ``subsystem``.

    Args:
        installed: The running daemon's version.
        latest: The newest released version.
        subsystem: What the report is about — a handler name, a rule ID or a
            component. Matched against the notes however it is spelled.
        notes: Version string to release-note body. Supplied by the caller so
            this stays a pure decision that a test can drive without a
            filesystem; in production it comes from
            ``install.release_notes.load_release_notes_between``.

    Returns:
        A :class:`CurrencyVerdict`. Never raises: the caller is a report
        generator, and an exception there loses the report rather than
        improving it.
    """
    try:
        installed_tuple = parse_version_tuple(installed)
        latest_tuple = parse_version_tuple(latest)
    except (ValueError, TypeError):
        return CurrencyVerdict(
            may_report=False,
            detail=(
                f"Version currency could not be established: {installed!r} or {latest!r} is "
                "not a version this daemon can parse. Run `hooks-daemon status` to confirm "
                "the installed version before reporting — an unchecked install and a "
                "checked one must not look the same in an issue."
            ),
        )

    if installed_tuple > latest_tuple:
        return CurrencyVerdict(
            may_report=True,
            detail=(
                f"Installed {installed} is AHEAD of the newest release {latest} — an "
                "unreleased build. Release notes cannot speak to it, so the behaviour "
                "described here is against code that has not shipped yet."
            ),
        )

    if installed_tuple == latest_tuple:
        return CurrencyVerdict(
            may_report=True,
            detail=f"Installed {installed} is the newest release; nothing to compare.",
        )

    checked = _versions_between(installed_tuple, latest, notes)
    if not checked:
        return CurrencyVerdict(
            may_report=False,
            detail=(
                f"Installed {installed} is behind {latest}, and no release notes for the "
                "versions in between are available, so whether "
                f"{subsystem!r} changed since is unknown. Upgrade and re-check, or run "
                "`hooks-daemon release-notes --from "
                f"{installed} --to {latest}` to see what is missing."
            ),
        )

    pattern = _subsystem_pattern(subsystem)
    mentions = tuple(version for version in checked if pattern.search(notes[version]))

    if mentions:
        return CurrencyVerdict(
            may_report=False,
            detail=(
                f"Installed {installed} is behind {latest}, and {subsystem!r} changed in "
                f"{', '.join(mentions)}. The behaviour reported here may already be fixed. "
                "Upgrade, confirm it still happens, and report from the newer version."
            ),
            versions_checked=tuple(checked),
            mentions=mentions,
        )

    return CurrencyVerdict(
        may_report=True,
        detail=(
            f"Installed {installed} is behind {latest}, but the release notes for "
            f"{', '.join(checked)} do not mention {subsystem!r} — so the behaviour is "
            "expected to be live on the newest release too."
        ),
        versions_checked=tuple(checked),
    )
