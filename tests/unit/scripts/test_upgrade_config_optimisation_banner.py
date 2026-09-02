"""Contract tests for the post-upgrade config-optimisation banner (Plan 00322).

Plan 00308 made the config-optimisation review (``/optimise``) a MANDATORY
closing step of every upgrade, and ``scripts/upgrade_version.sh`` prints the
banner that carries that mandate to the agent driving the upgrade. A field
report showed the mandate being filed as an optional follow-up ("run
/optimise at some point") — because the banner scheduled itself for "your
NEXT Claude Code session", directly after a block telling the agent to exit
the session it was in. A mandatory step addressed to a session that does not
exist yet cannot be performed by the agent reading it.

These tests lock the wording contract: the banner must claim the CURRENT
session, and must be read BEFORE the restart instruction — not after it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_UPGRADE_SCRIPT: Final[Path] = _REPO_ROOT / "scripts" / "upgrade_version.sh"

#: The banner's opening line, and the restart block it must precede.
_MANDATE: Final[re.Pattern[str]] = re.compile(r"MANDATORY NEXT STEP")
_RESTART: Final[re.Pattern[str]] = re.compile(r"[Rr]estart Claude Code to activate upgraded hooks")

#: Phrasings that hand the step to a future session. The skip branch may say
#: "run it later" — the human opted out there — so these target the mandate's
#: own deferral, which is what the field report tripped over.
_DEFERRALS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"in your next\b", re.IGNORECASE),
    re.compile(r"at some point", re.IGNORECASE),
)

#: The banner must name the session that is running the upgrade.
_CURRENT_SESSION: Final[re.Pattern[str]] = re.compile(
    r"this session|the session that ran this", re.IGNORECASE
)

#: How far past the mandate line the current-session imperative may sit.
_BANNER_LINES: Final[int] = 12


def _lines() -> list[str]:
    return _UPGRADE_SCRIPT.read_text(encoding="utf-8").splitlines()


def _first_match(pattern: re.Pattern[str]) -> int:
    for index, line in enumerate(_lines()):
        if pattern.search(line):
            return index
    raise AssertionError(f"pattern {pattern.pattern!r} not found in {_UPGRADE_SCRIPT}")


class TestMandateClaimsTheCurrentSession:
    def test_banner_is_present(self) -> None:
        assert _first_match(_MANDATE) >= 0

    def test_banner_names_the_current_session(self) -> None:
        start = _first_match(_MANDATE)
        banner = "\n".join(_lines()[start : start + _BANNER_LINES])
        assert _CURRENT_SESSION.search(banner), (
            "the mandatory banner must tell the agent to run the review in the "
            f"session it is already in; got:\n{banner}"
        )

    def test_banner_does_not_defer_to_a_future_session(self) -> None:
        start = _first_match(_MANDATE)
        banner = "\n".join(_lines()[start : start + _BANNER_LINES])
        for pattern in _DEFERRALS:
            assert not pattern.search(banner), (
                f"deferral phrasing {pattern.pattern!r} makes the mandatory step "
                f"read as an optional follow-up; got:\n{banner}"
            )


class TestOrdering:
    def test_mandate_is_printed_before_the_restart_instruction(self) -> None:
        assert _first_match(_MANDATE) < _first_match(_RESTART), (
            "the agent must read the mandatory review step BEFORE being told to "
            "exit its session, or the step has no session left to run in"
        )


class TestOptOutSurvives:
    def test_skip_branch_still_short_circuits_the_banner(self) -> None:
        body = _UPGRADE_SCRIPT.read_text(encoding="utf-8")
        assert '"--skip-config-optimisation"' in body
        assert "Config-optimisation review skipped" in body
