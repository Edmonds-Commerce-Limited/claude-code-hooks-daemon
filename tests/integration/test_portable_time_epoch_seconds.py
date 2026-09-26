"""Plan 00466 N30 — ``scripts/lib/portable_time.sh``'s ``_hp_epoch_seconds``.

``date +%s`` is looked up on PATH. The scripts that build/repair a project's
venv (``scripts/venv_bootstrap.sh``, ``scripts/install/venv.sh``,
``scripts/install/daemon_control.sh``) exist to survive a hostile or
stripped PATH (the same hazard Plan 00466 N1 fixed for `sleep` in
``resolve_venv.sh``, commit 766677c1) — a narrowed bootstrap PATH is the
realistic case, not a host genuinely missing ``date``. Several of them fed
``$(date +%s)`` straight into an arithmetic expression or a numeric ``[ ]``
test: with `date` unreachable, that embeds an EMPTY string, which is not a
loud failure but a silently-wrong number that changes which branch runs
(exactly N1's hazard, just for `date` instead of `sleep`).

``_hp_epoch_seconds`` fixes this with a three-tier fallback:

  1. bash's own ``printf '%(%s)T' -1`` builtin (bash >= 4.2) — no PATH
     lookup at all, so a hostile/stripped PATH never matters on any modern
     bash.
  2. ``date +%s`` when it IS on PATH — the fallback for bash 3.2 (macOS's
     system ``/bin/bash``), which has no ``%()T`` builtin.
  3. Neither available: a loud, explicit failure (stderr diagnostic, exit
     1) — never a silently-empty/zero value.

Branch 1 is what actually runs on this test host's bash (>= 4.2), so
branches 2 and 3 are exercised by overriding the testable seam
``_hp_bash_supports_printf_time`` after sourcing — see its docstring in the
library for why that seam exists.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTABLE_TIME_SH = REPO_ROOT / "scripts" / "lib" / "portable_time.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30


def _run(harness: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_returns_a_plausible_epoch_second_count() -> None:
    before = int(time.time())
    result = _run(f'. "{PORTABLE_TIME_SH}"\n_hp_epoch_seconds\n')
    after = int(time.time())

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    value = int(result.stdout.strip())
    assert before - 2 <= value <= after + 2, f"value {value} not close to now ({before}-{after})"


def test_empty_path_does_not_break_it_on_modern_bash() -> None:
    """The builtin needs no PATH lookup, so a hostile/stripped PATH is a
    no-op on any bash new enough to have it — the exact case that broke
    the original N1 watchdog for `sleep`."""
    empty_path_harness = textwrap.dedent(f"""\
        . "{PORTABLE_TIME_SH}"
        PATH=""
        _hp_epoch_seconds
        """)
    result = _run(empty_path_harness)

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip().isdigit()


def test_falls_back_to_date_when_builtin_unsupported_and_date_on_path() -> None:
    """Simulates bash < 4.2 (macOS's system bash) via the testable seam."""
    harness = textwrap.dedent(f"""\
        . "{PORTABLE_TIME_SH}"
        _hp_bash_supports_printf_time() {{ return 1; }}
        _hp_epoch_seconds
        """)
    result = _run(harness)

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip().isdigit()


def test_loud_explicit_failure_when_neither_builtin_nor_date_available() -> None:
    """Bash < 4.2 AND no `date` on PATH: no silent wrong value -- an
    explicit stderr diagnostic and a non-zero return."""
    harness = textwrap.dedent(f"""\
        . "{PORTABLE_TIME_SH}"
        _hp_bash_supports_printf_time() {{ return 1; }}
        PATH=""
        _hp_epoch_seconds
        """)
    result = _run(harness)

    assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert (
        result.stdout.strip() == ""
    ), f"must not print a fabricated value; stdout={result.stdout!r}"
    assert "_hp_epoch_seconds" in result.stderr
    assert "no epoch-second source" in result.stderr.lower()


class TestTimestamp:
    """``_hp_timestamp <strftime-format> [--utc]`` -- the same three-tier
    fallback as ``_hp_epoch_seconds``, for the formatted (not raw-epoch)
    timestamps used in backup filenames, snapshot IDs and manifest/log
    entries across the hostile-PATH-survival file set."""

    def test_formats_using_the_given_pattern(self) -> None:
        result = _run(f'. "{PORTABLE_TIME_SH}"\n_hp_timestamp "%Y%m%d"\n')

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        value = result.stdout.strip()
        assert len(value) == 8 and value.isdigit(), f"value={value!r}"

    def test_utc_flag_matches_date_dash_u(self) -> None:
        result = _run(f'. "{PORTABLE_TIME_SH}"\n_hp_timestamp "%Y-%m-%dT%H:%M:%SZ" --utc\n')
        expected = subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True, check=True
        ).stdout.strip()

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        # Compare down to the minute -- a second may tick between the two calls.
        assert (
            result.stdout.strip()[:16] == expected[:16]
        ), f"got={result.stdout.strip()!r} expected~={expected!r}"

    def test_empty_path_does_not_break_it_on_modern_bash(self) -> None:
        harness = textwrap.dedent(f"""\
            . "{PORTABLE_TIME_SH}"
            PATH=""
            _hp_timestamp "%Y%m%d-%H%M%S"
            """)
        result = _run(harness)

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert result.stdout.strip() != ""

    def test_falls_back_to_date_when_builtin_unsupported_and_date_on_path(self) -> None:
        harness = textwrap.dedent(f"""\
            . "{PORTABLE_TIME_SH}"
            _hp_bash_supports_printf_time() {{ return 1; }}
            _hp_timestamp "%Y%m%d" --utc
            """)
        result = _run(harness)

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert result.stdout.strip() != ""

    def test_loud_explicit_failure_when_neither_builtin_nor_date_available(self) -> None:
        harness = textwrap.dedent(f"""\
            . "{PORTABLE_TIME_SH}"
            _hp_bash_supports_printf_time() {{ return 1; }}
            PATH=""
            _hp_timestamp "%Y%m%d"
            """)
        result = _run(harness)

        assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert result.stdout.strip() == ""
        assert "_hp_timestamp" in result.stderr
        assert "no timestamp source" in result.stderr.lower()
