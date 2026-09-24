"""Plan 00466 N1 — ``_rv_pick_python``'s glob fallback probes runnability.

``scripts/lib/resolve_venv.sh::_rv_pick_python`` used to accept a scanned
``untracked/venv-*/bin/python(3)`` candidate on its executable bit alone
(``[ -x "$candidate" ]``). A venv built inside a container can be present,
``+x``, and still fail at exec time on the host -- wrong architecture/libc,
or a symlink into a container-only path (first observed in #55, Plan
00457's JOURNAL). The fallback would then report "resolved", so
``bin/hooks-daemon`` never reached its venv-free path
(``_run_venv_free_verb``) and instead crashed on a raw exec error.

These tests source the library directly and call ``_rv_pick_python`` (and
the public ``resolve_venv_python``) against a fixture ``untracked/`` laid
out with fake candidates: a good interpreter, one that exits non-zero, a
dangling symlink, and one that hangs. No real Python venv or ``paths.py``
call is needed for ``_rv_pick_python`` itself -- it is pure bash glob +
probe logic.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30


def _make_good_candidate(venv_dir: Path) -> Path:
    """A real, working interpreter -- symlinked to this test's own bash."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/bash\nexit 0\n")
    py.chmod(0o755)
    return py


def _make_failing_candidate(venv_dir: Path) -> Path:
    """Present, +x, exits non-zero -- executable-bit checks accept this."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/bash\nexit 1\n")
    py.chmod(0o755)
    return py


def _make_dangling_symlink_candidate(venv_dir: Path) -> Path:
    """``bin/python`` symlinked to a target that does not exist."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.symlink_to(venv_dir / "nonexistent-target")
    return py


def _make_hanging_candidate(venv_dir: Path) -> Path:
    """Present, +x, never exits on its own."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/bash\nsleep 100\n")
    py.chmod(0o755)
    return py


def _run_pick_python(
    daemon_dir: Path, *, probe_timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Source the library and call ``_rv_pick_python`` directly."""
    env_prelude = ""
    if probe_timeout is not None:
        env_prelude = f'export HOOKS_DAEMON_VENV_PROBE_TIMEOUT="{probe_timeout}"\n'
    harness = textwrap.dedent(f"""\
        {env_prelude}unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH
        . "{RESOLVE_VENV_SH}"
        _rv_pick_python "{daemon_dir}"
        """)
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_skips_candidate_that_exits_nonzero(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    _make_failing_candidate(daemon_dir / "untracked" / "venv-py999-broken")

    result = _run_pick_python(daemon_dir)

    assert result.returncode != 0, (
        "a candidate that exits non-zero must NOT be reported as resolved.\n"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_skips_dangling_symlink_candidate(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    _make_dangling_symlink_candidate(daemon_dir / "untracked" / "venv-py999-dangling")

    result = _run_pick_python(daemon_dir)

    assert result.returncode != 0, (
        "a dangling-symlink candidate must NOT be reported as resolved.\n"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_hanging_candidate_is_bounded_by_the_probe_timeout(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    _make_hanging_candidate(daemon_dir / "untracked" / "venv-py999-hangs")

    started = time.monotonic()
    result = _run_pick_python(daemon_dir, probe_timeout=1)
    elapsed = time.monotonic() - started

    assert result.returncode != 0, (
        "a hanging candidate must NOT be reported as resolved.\n"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert elapsed < 10.0, f"probe must respect its bound; took {elapsed:.2f}s"


def test_falls_through_to_good_second_candidate(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    _make_failing_candidate(daemon_dir / "untracked" / "venv-py999-aaa-broken")
    good = _make_good_candidate(daemon_dir / "untracked" / "venv-py999-zzz-good")

    result = _run_pick_python(daemon_dir)

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == str(good)


def test_all_candidates_bad_reports_miss(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    _make_failing_candidate(daemon_dir / "untracked" / "venv-py999-aaa-broken")
    _make_dangling_symlink_candidate(daemon_dir / "untracked" / "venv-py999-bbb-dangling")

    result = _run_pick_python(daemon_dir)

    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_good_candidate_alone_is_unaffected(tmp_path: Path) -> None:
    """Regression: a genuinely working candidate resolves exactly as before."""
    daemon_dir = tmp_path / "daemon"
    good = _make_good_candidate(daemon_dir / "untracked" / "venv-py999-ok")

    result = _run_pick_python(daemon_dir)

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == str(good)


def test_resolve_venv_python_falls_through_to_venv_free_message_when_all_bad(
    tmp_path: Path,
) -> None:
    """The PUBLIC ``resolve_venv_python`` entry point (not just the internal
    picker) must also fail rather than report a broken candidate as
    resolved -- this is what ``bin/hooks-daemon`` actually calls."""
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    _make_failing_candidate(daemon_dir / "untracked" / "venv-py999-broken")

    harness = textwrap.dedent(f"""\
        unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH
        . "{RESOLVE_VENV_SH}"
        resolve_venv_python "{daemon_dir}"
        """)
    result = subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )

    assert result.returncode != 0
    assert "no usable venv found" in result.stderr
    assert "repair" in result.stderr
