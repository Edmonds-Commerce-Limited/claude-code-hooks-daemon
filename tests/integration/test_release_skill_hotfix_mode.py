"""`/release hotfix` prints the hotfix fast path (Plan 00576).

The v3.73.1 emergency patch took as long as a feature release because the
pipeline had one speed. `hotfix` on the invocation selects RELEASING.md's
"Hotfix fast path"; these tests pin what `invoke.sh` prints for it, and that
the standard invocation is unchanged by its arrival.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.constants import Timeout

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_RELEASE_INVOKE: Final[Path] = _REPO_ROOT / ".claude" / "skills" / "release" / "invoke.sh"
_RELEASING: Final[Path] = _REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md"

_FAST_PATH_HEADING: Final[str] = "Hotfix fast path"
_MODE_RECORD: Final[str] = '"mode": "hotfix"'
_ACCEPT_FLAG: Final[str] = "release-slate-check --accept"
_EXIT_USAGE: Final[int] = 2


def _invoke(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_RELEASE_INVOKE), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.REQUEST_DEFAULT,
    )


class TestTheHotfixVariant:
    @pytest.mark.parametrize(
        ("args", "version"),
        [(("hotfix",), "patch"), (("3.73.2", "hotfix"), "3.73.2")],
        ids=["bare", "explicit-version"],
    )
    def test_hotfix_prints_the_fast_path(self, args: tuple[str, ...], version: str) -> None:
        result = _invoke(*args)

        assert result.returncode == 0, result.stderr
        assert f"Version: {version}" in result.stdout
        assert _FAST_PATH_HEADING in result.stdout
        assert _MODE_RECORD in result.stdout

    def test_hotfix_auto_accepts_in_flight_work_at_the_slate_gate(self) -> None:
        """Owner ruling: the slate report still prints, the release does not stop on it."""
        result = _invoke("hotfix")

        assert _ACCEPT_FLAG in result.stdout

    def test_hotfix_names_what_it_skips_and_what_it_keeps(self) -> None:
        out = _invoke("hotfix").stdout

        for skipped in ("1H", "1c", "Step 7", "15.1"):
            assert skipped in out, f"the hotfix prompt does not mention skipping {skipped}"
        for kept in ("Release gate", "Step 8b", "Step 13", "merge freeze"):
            assert kept in out, f"the hotfix prompt does not say {kept} is kept"

    @pytest.mark.parametrize("bump", ["major", "minor"])
    def test_a_hotfix_is_never_a_major_or_minor_bump(self, bump: str) -> None:
        result = _invoke(bump, "hotfix")

        assert result.returncode == _EXIT_USAGE
        assert "patch" in result.stderr

    def test_the_section_it_points_at_exists(self) -> None:
        assert f"## {_FAST_PATH_HEADING}" in _RELEASING.read_text(encoding="utf-8")


class TestTheStandardInvocationIsUnchanged:
    def test_a_plain_release_does_not_take_the_fast_path(self) -> None:
        result = _invoke("patch")

        assert result.returncode == 0, result.stderr
        assert _FAST_PATH_HEADING not in result.stdout
        assert _MODE_RECORD not in result.stdout
        assert _ACCEPT_FLAG not in result.stdout

    def test_accept_wip_still_passes_accept(self) -> None:
        result = _invoke("3.73.2", "accept-wip")

        assert result.returncode == 0, result.stderr
        assert _ACCEPT_FLAG in result.stdout
        assert _FAST_PATH_HEADING not in result.stdout

    def test_no_argument_still_means_auto(self) -> None:
        result = _invoke()

        assert result.returncode == 0, result.stderr
        assert "Version: auto" in result.stdout
