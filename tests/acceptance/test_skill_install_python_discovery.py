"""Plan 00110 Phase 5 Task 5.1 — host-a field-report acceptance test.

Replays the host-a scenario end-to-end against the production
``src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/install.sh``:
when default ``python3`` is too old (3.9) but newer ``python3.13`` /
``python3.14`` are on PATH, the skill bootstrap MUST auto-pick the
latest compatible interpreter without operator intervention.

Background — the host-a field report
(``untracked/hooks-daemon-upgrade-python-version.md``):

  - Host had ``python3`` → 3.9.21 (system), ``python3.13`` and ``python3.14``
    installed alongside but NOT as ``python3``.
  - Pre-Plan-00110 install.sh probed only ``python3`` and aborted with a
    hardcoded suggestion to install ``python3.11`` — even though 3.13/3.14
    were already present and would have worked.
  - Plan 00110 Task 4.3 rewired the install.sh pre-check to delegate to
    ``scripts/lib/python_discovery.sh::find_latest_python`` which globs
    ``$PATH`` for ``python3.NN`` and picks the highest meeting the floor.

These tests pin both halves of the closure:

  1. **Positive (the host-a scenario)** — when 3.9 / 3.13 / 3.14 coexist,
     install.sh selects ``python3.14`` (highest meeting the >=3.11 floor)
     and proceeds without requiring ``HOOKS_DAEMON_PYTHON``.
  2. **Negative (no compatible interpreter)** — when only ``python3.9`` is
     present, install.sh aborts and the diagnostic NAMES the observed
     ``python3.9 (3.9.21)`` interpreter — never a hardcoded
     ``python3.11`` suggestion that may not exist on the host.

Implementation notes:

  - We synthesise fake ``python3.NN`` interpreters as tiny POSIX shell
    scripts that print ``Python X.Y.Z`` to stdout when invoked with
    ``--version`` (same pattern used by ``test_python_discovery_bash.py``).
  - We shim ``curl`` in PATH to serve the repo's local
    ``pyproject.toml`` and ``scripts/lib/python_discovery.sh`` instead of
    hitting GitHub — keeps the test deterministic and offline.
  - We point install.sh at a synthetic project root whose
    ``.claude/hooks-daemon/`` directory already exists, so install.sh
    exits cleanly with "Daemon is already installed" after the
    pre-check succeeds. We assert the pre-check's
    ``Using Python: ...`` output line; full daemon installation is
    out of scope.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "install.sh"
)
PYPROJECT = REPO_ROOT / "pyproject.toml"
DISCOVERY_HELPER = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"
BASH = shutil.which("bash") or "/bin/bash"

_FAKE_PYTHON_TEMPLATE = """\
#!/bin/sh
case "$1" in
    --version) echo "Python {version}" ;;
    -c) shift; eval "echo 'Python {version}'" ;;
    *) echo "Python {version}" ;;
esac
"""

_CURL_SHIM_TEMPLATE = """\
#!/bin/sh
# Curl shim for the host-a acceptance test. Maps the two URLs install.sh
# fetches (pyproject.toml + python_discovery.sh) to local repo files.
# Any other URL is passed through to the real curl so install.sh can fail
# naturally if it tries a network fetch we did not anticipate.
output=""
url=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) output="$2"; shift 2 ;;
        -sSL|-sS|-s|-S|-L|-fsSL) shift ;;
        https://*|http://*) url="$1"; shift ;;
        *) shift ;;
    esac
done
case "$url" in
    *pyproject.toml*) cp "{pyproject}" "$output" ;;
    *python_discovery.sh*) cp "{discovery}" "$output" ;;
    *)
        # Unanticipated URL — fall through to the real curl so the test
        # surfaces the gap rather than silently masking it.
        exec "{real_curl}" -sSL "$url" -o "$output"
        ;;
esac
"""


def _make_fake_python(bin_dir: Path, command_name: str, version: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / command_name
    path.write_text(_FAKE_PYTHON_TEMPLATE.format(version=version))
    path.chmod(0o755)
    return path


def _make_curl_shim(bin_dir: Path) -> Path:
    real_curl = shutil.which("curl")
    if real_curl is None:
        pytest.skip("real curl required for fallback URL — not installed in test env")
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / "curl"
    path.write_text(
        _CURL_SHIM_TEMPLATE.format(
            pyproject=str(PYPROJECT),
            discovery=str(DISCOVERY_HELPER),
            real_curl=real_curl,
        )
    )
    path.chmod(0o755)
    return path


# The minimal set of binaries install.sh + python_discovery.sh invoke.
# We symlink each into the test's bin_dir so PATH can be set to bin_dir
# ALONE — preventing the host's ``/usr/bin/python3.NN`` interpreters from
# leaking into the discovery glob and corrupting the test fixture.
_REQUIRED_COREUTILS = (
    "cp",
    "mkdir",
    "rm",
    "dirname",
    "basename",
    "grep",
    "head",
    "wc",
    "cat",
    "sh",
    "ls",
    "tr",
    "awk",
    "sed",
    "env",
    "printf",
    "echo",
    "test",
    "[",
    "uname",
    "tee",
    # Plan 00122 BUG 3: the "already installed" guard now runs a health probe
    # (_installation_is_healthy) that uses mktemp for a throwaway probe file.
    "mktemp",
)


def _symlink_coreutils(bin_dir: Path) -> None:
    """Symlink the minimal set of binaries install.sh needs into ``bin_dir``
    so the test can run with ``PATH=$bin_dir`` (no system paths) — keeping
    the host's ``/usr/bin/python3.NN`` interpreters out of the discovery
    glob.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    for util in _REQUIRED_COREUTILS:
        src = shutil.which(util)
        if src is None:
            continue
        dst = bin_dir / util
        if dst.exists() or dst.is_symlink():
            continue
        dst.symlink_to(src)


def _make_already_installed_project(tmp_path: Path) -> Path:
    """Build a synthetic project root with a HEALTHY existing install so
    ``install.sh`` exits cleanly after the pre-check (printing "Daemon is
    already installed").

    Plan 00122 BUG 3: the guard now requires a *healthy* install — a venv
    python that imports ``claude_code_hooks_daemon`` — not just the directory.
    A bare ``.claude/hooks-daemon/`` is now (correctly) treated as broken and
    would trigger a repair, so the fixture provisions a fake venv python whose
    ``-c`` invocation exits 0 (import "succeeds").
    """
    project = tmp_path / "project"
    daemon_dir = project / ".claude" / "hooks-daemon"
    daemon_dir.mkdir(parents=True)
    venv_bin = daemon_dir / "untracked" / "venv-py311-test" / "bin"
    _make_fake_python(venv_bin, "python", "3.11.0")
    return project


def _invoke_install_sh(
    *,
    project_root: Path,
    bin_dir: Path,
) -> subprocess.CompletedProcess[str]:
    """Run install.sh from ``project_root`` with ``PATH=bin_dir`` ONLY.
    The host's ``/usr/bin/python3.NN`` interpreters MUST NOT leak into
    discovery — that would defeat the fixture. Required coreutils are
    symlinked into ``bin_dir`` by ``_symlink_coreutils`` so the install
    script can still run cp/mkdir/dirname/grep/etc.
    """
    env = {
        "PATH": str(bin_dir),
        "HOME": os.environ.get("HOME", "/tmp"),
        # CRITICAL: clear any inherited HOOKS_DAEMON_PYTHON so the test
        # exercises the rung-2 glob-and-sort discovery, not the rung-1
        # explicit-override path.
    }
    return subprocess.run(
        [BASH, str(INSTALL_SH)],
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.DAEMON_STARTUP,
    )


# ----- positive: host-a scenario -----


def test_host_a_scenario_selects_python_314(tmp_path: Path) -> None:
    """The host-a reproduction: ``python3`` (3.9), ``python3.13``, and
    ``python3.14`` coexist on PATH. install.sh MUST pick ``python3.14``
    via the glob-and-sort discovery and proceed without operator help.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    _make_curl_shim(bin_dir)
    _symlink_coreutils(bin_dir)
    project = _make_already_installed_project(tmp_path)

    result = _invoke_install_sh(project_root=project, bin_dir=bin_dir)

    assert result.returncode == 0, (
        f"install.sh must exit 0 (pre-check succeeds, then 'already installed' exit). "
        f"Got exit {result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    expected_path = str(bin_dir / "python3.14")
    assert f"Using Python: {expected_path}" in result.stdout, (
        f"install.sh must print the chosen interpreter on stdout. "
        f"Expected substring 'Using Python: {expected_path}'.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Aborting install" not in result.stdout, (
        f"install.sh must NOT abort when a compatible interpreter is present.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_host_a_scenario_selects_highest_minor_not_lowest(tmp_path: Path) -> None:
    """Discovery must pick the HIGHEST compatible minor (3.14), not the
    first one that meets the floor (3.13). Guards against any future
    refactor that switches to first-match semantics.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    _make_curl_shim(bin_dir)
    _symlink_coreutils(bin_dir)
    project = _make_already_installed_project(tmp_path)

    result = _invoke_install_sh(project_root=project, bin_dir=bin_dir)

    assert (
        result.returncode == 0
    ), f"Expected exit 0, got {result.returncode}. stderr:\n{result.stderr}"
    assert (
        f"Using Python: {bin_dir}/python3.14" in result.stdout
    ), f"Must pick python3.14 (highest), not python3.13.\nstdout:\n{result.stdout}"
    assert (
        f"Using Python: {bin_dir}/python3.13" not in result.stdout
    ), "Must NOT pick python3.13 when python3.14 is available"


# ----- negative: no compatible interpreter -----


def test_only_python_39_aborts_naming_observed(tmp_path: Path) -> None:
    """Only ``python3.9`` (3.9.21) on PATH, floor 3.11. install.sh MUST
    abort and the diagnostic MUST name ``python3.9 (3.9.21)`` — the
    interpreter we ACTUALLY observed, not a hardcoded suggestion of a
    version (``python3.11``) that may not be installable on this host.

    This is the host-a trap closer: under the pre-Plan-00110 code
    install.sh would have suggested ``python3.11`` even though the host
    had no python3.11 available. Plan 00110 routes through
    ``find_latest_python`` whose diagnostic names observed candidates.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _make_curl_shim(bin_dir)
    _symlink_coreutils(bin_dir)
    project = _make_already_installed_project(tmp_path)

    result = _invoke_install_sh(project_root=project, bin_dir=bin_dir)

    assert result.returncode == 1, (
        f"install.sh must exit 1 when no compatible interpreter exists. "
        f"Got exit {result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Aborting install" in result.stdout, (
        f"install.sh must print 'Aborting install' on the precheck-failure path.\n"
        f"stdout:\n{result.stdout}"
    )
    # The diagnostic MUST name the observed interpreter.
    combined = result.stdout + result.stderr
    assert "python3.9 (3.9.21)" in combined, (
        f"Diagnostic MUST name the observed interpreter 'python3.9 (3.9.21)' — "
        f"that is the host-a trap closer. Combined output:\n{combined}"
    )
    # And it must reference the floor explicitly.
    assert (
        "3.11" in combined
    ), f"Diagnostic MUST reference the required floor (3.11). Combined output:\n{combined}"


def test_no_python3_nn_on_path_aborts_with_clear_message(tmp_path: Path) -> None:
    """No ``python3.NN`` interpreter at all on PATH (only plain
    ``python3`` which the glob does NOT match). install.sh MUST abort
    with a clear "no python3.NN found" message — distinct from the
    "observed candidates below floor" branch tested above.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")  # plain python3 only
    _make_curl_shim(bin_dir)
    _symlink_coreutils(bin_dir)
    project = _make_already_installed_project(tmp_path)

    result = _invoke_install_sh(project_root=project, bin_dir=bin_dir)

    assert (
        result.returncode == 1
    ), f"Expected exit 1, got {result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Aborting install" in result.stdout, f"Must abort.\nstdout:\n{result.stdout}"
    combined = result.stdout + result.stderr
    assert "No python3.NN" in combined or "no python3.NN" in combined.lower(), (
        f"Diagnostic must explain that no python3.NN interpreter was found.\n"
        f"Combined output:\n{combined}"
    )
