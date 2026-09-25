"""Plan 00466 N30 — proof that this wave's test methodology would have
caught the ORIGINAL watchdog defect (Plan 00466 N1, fixed at 766677c1).

DBF step 3 ("prove the rule fires on the originating instance, red before
green") for the detector this wave adds: the same "source the library, run
its watchdog against a live process under a PATH stripped of the tool it
depends on" methodology used throughout
``test_venv_bootstrap_hostile_path_epoch.py``,
``test_venv_lock_wait_hostile_path.py`` and
``test_daemon_control_pgrep_portability.py`` is applied here to a SCRATCH
COPY of ``resolve_venv.sh`` with 766677c1's fix reverted -- reconstructing
the exact pre-fix watchdog shape (``( sleep "$bound"; kill -KILL "$pid"
2>/dev/null ) &``, no ``_rv_wait_secs``). The pre-fix shape must fail this
test (RED); the real, current file must pass it (GREEN) -- already covered
by ``test_resolve_venv_runnability_probe.py::
test_good_candidate_resolves_when_path_has_no_sleep``, exercised again here
for the side-by-side contrast.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30

# The exact pre-766677c1 watchdog line this reverts back to.
_POST_FIX_WATCHDOG_LINE = (
    '    ( _rv_wait_secs "$_RV_PROBE_TIMEOUT_SECS" && kill -KILL "$pid" 2>/dev/null ) &'
)
_PRE_FIX_WATCHDOG_LINE = '    ( sleep "$_RV_PROBE_TIMEOUT_SECS"; kill -KILL "$pid" 2>/dev/null ) &'


def _make_good_candidate(venv_dir: Path) -> Path:
    """A working interpreter that takes ~2 real seconds before exiting 0 --
    long enough that the race is not timing-sensitive either way. The delay
    is a pure-bash wall-clock busy-wait on the builtin ``$SECONDS`` (no
    external `sleep`/`date`, so it works unmodified under the same empty
    PATH the probe itself runs under). This matters for the RED proof
    below: the pre-fix watchdog's erroneous kill lands within
    milliseconds of starting (`sleep` fails at once, falling straight
    through to `kill -KILL`), so ANY candidate slower than that -- not
    just a marginal one -- demonstrates the bug deterministically, with no
    dependence on host speed.
    """
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text(
        "#!/bin/bash\nstart=$SECONDS\nwhile (( SECONDS - start < 2 )); do :; done\nexit 0\n"
    )
    py.chmod(0o755)
    return py


def _make_reverted_scratch_copy(dest: Path) -> Path:
    """A scratch copy of resolve_venv.sh with 766677c1's fix undone.

    Reconstructs the ORIGINAL watchdog: ``( sleep "$bound"; kill -KILL
    "$pid" 2>/dev/null ) &`` -- a bare ``;`` list, not ``_rv_wait_secs``'s
    ``&&``-gated fallback. With no `sleep` on PATH, `sleep` fails at once
    (127) and the list proceeds straight to `kill -KILL`, killing a
    healthy, already-finished candidate -- the exact v3.9.1 field bug.
    """
    source = RESOLVE_VENV_SH.read_text()
    assert _POST_FIX_WATCHDOG_LINE in source, (
        "resolve_venv.sh's watchdog line has moved or been reworded -- "
        "update _POST_FIX_WATCHDOG_LINE to match the current source before "
        "trusting this proof."
    )
    reverted = source.replace(_POST_FIX_WATCHDOG_LINE, _PRE_FIX_WATCHDOG_LINE)
    dest.write_text(reverted)
    dest.chmod(0o755)
    return dest


def _run_pick_python(
    lib_path: Path, daemon_dir: Path, *, probe_timeout: float, path: Path
) -> subprocess.CompletedProcess[str]:
    harness = textwrap.dedent(f"""\
        export HOOKS_DAEMON_VENV_PROBE_TIMEOUT="{probe_timeout}"
        export PATH="{path}"
        unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH
        . "{lib_path}"
        _rv_pick_python "{daemon_dir}"
        """)
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_pre_fix_watchdog_shape_wrongly_kills_a_good_candidate_under_hostile_path(
    tmp_path: Path,
) -> None:
    """RED: the reverted (pre-766677c1) shape reproduces the original bug --
    this is the proof the detector methodology catches the class, not just
    this wave's own instances."""
    daemon_dir = tmp_path / "daemon"
    _make_good_candidate(daemon_dir / "untracked" / "venv-py999-ok")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    scratch_lib = _make_reverted_scratch_copy(tmp_path / "resolve_venv_reverted.sh")

    result = _run_pick_python(scratch_lib, daemon_dir, probe_timeout=5, path=empty_path)

    assert result.returncode != 0, (
        "RED PROOF FAILED: the reverted pre-fix shape was expected to wrongly reject "
        f"a healthy candidate under a PATH with no `sleep`, but it resolved anyway. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "timed out" in result.stderr, (
        f"expected the original bug's exact symptom (a healthy candidate reported as "
        f"timed out). stderr={result.stderr!r}"
    )


def test_current_fixed_file_resolves_the_same_scenario(tmp_path: Path) -> None:
    """GREEN: the real, current resolve_venv.sh does not have this bug --
    contrasted directly against the RED case above."""
    daemon_dir = tmp_path / "daemon"
    good = _make_good_candidate(daemon_dir / "untracked" / "venv-py999-ok")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()

    result = _run_pick_python(RESOLVE_VENV_SH, daemon_dir, probe_timeout=5, path=empty_path)

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == str(good)
