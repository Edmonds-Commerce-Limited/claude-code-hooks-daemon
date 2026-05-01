r"""Plan 00103 Phase 5 — v3.9.1 field-regression acceptance test.

Reproduces the field bug reported in ``context/2026-04-30-field-report.md``:

    Hosts where the system default ``python3`` is older than 3.11 (e.g.
    RHEL/CentOS where ``python3 -> 3.9``) saw every diagnostic helper
    crash, even when a compatible Python existed at a versioned path
    (``python3.11``, ``python3.13``) AND a usable venv was on disk.

Root cause was two-layered:

 1. ``paths.py`` imported ``tomllib`` at module top, crashing on 3.9.
 2. The SSOT-invoking bash wrappers fell back to bare ``python3`` and
    silenced its stderr, so the crash surfaced as a generic "venv not
    found" rather than the underlying ``ModuleNotFoundError``.

Plan 00103 fixed both layers (deferred ``tomllib`` import + venv-resident
``bin/python`` SSOT invocation + fail-fast on missing). This test exercises
the post-bootstrap path end-to-end:

  - Daemon dir contains a real venv (built against the in-test 3.11+).
  - ``PATH`` advertises only a *fake* ``python3`` that lies about being 3.9.
  - Sourcing ``_resolve-venv.sh`` MUST succeed and resolve to the venv's
    own ``bin/python`` — never the fake on PATH.

Two Docker fixtures (``tests/integration/fixtures/{multi-python,single-python-39}``)
ship full-fidelity reproductions for manual/CI runs against real Python 3.9.
The in-process test below runs in any environment without container support.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SCRIPT = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "_resolve-venv.sh"
)
PATHS_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
BASH = shutil.which("bash") or "/bin/bash"


def _real_python() -> Path:
    """Locate a real Python 3.11+ interpreter on the host running tests.

    Probes the same versioned-only candidates that ``find_compatible_python``
    uses (per Plan 00103 Decision 3 Rule B). Falls back to ``sys.executable``
    if no system-installed versioned interpreter is found — that is the
    interpreter currently running pytest, which (since the daemon project
    requires 3.11+) is guaranteed to satisfy the version requirement.
    """
    for name in ("python3.13", "python3.12", "python3.11"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    import sys

    return Path(sys.executable).resolve()


def _build_fake_path_dir(tmp_path: Path) -> Path:
    """Create a PATH directory whose only ``python3`` shim lies about its version.

    The shim:
      - Reports ``Python 3.9.0`` from ``--version``.
      - Crashes with ``ModuleNotFoundError: tomllib`` from ``-c "import tomllib"``.

    This faithfully reproduces the field-report environment without needing
    a real Python 3.9 on the test host. The acceptance contract is: even if
    the resolver were tempted to fall back to bare ``python3``, it would
    crash visibly — proving the fix that uses the venv's own ``bin/python``
    bypasses this hostile PATH entirely.
    """
    bin_dir = tmp_path / "fake_path"
    bin_dir.mkdir()

    shim = bin_dir / "python3"
    shim.write_text(
        textwrap.dedent(f"""\
            #!{BASH}
            case "$1" in
                --version)
                    echo "Python 3.9.0"
                    exit 0
                    ;;
                -c)
                    if [[ "$2" == *"import tomllib"* ]]; then
                        echo "ModuleNotFoundError: No module named 'tomllib'" >&2
                        exit 1
                    fi
                    exit 0
                    ;;
                *)
                    echo "ModuleNotFoundError: No module named 'tomllib'" >&2
                    exit 1
                    ;;
            esac
            """),
        encoding="utf-8",
    )
    shim.chmod(0o755)

    bash_path = shutil.which("bash")
    if bash_path:
        os.symlink(bash_path, bin_dir / "bash")

    return bin_dir


def _build_daemon_dir_with_venv(tmp_path: Path) -> Path:
    """Build a fake project ``DAEMON_DIR`` with a venv-resident interpreter.

    Layout:

        $tmp/daemon_dir/
            src/claude_code_hooks_daemon/daemon/paths.py    -> real source
            untracked/venv-py311-acceptance/bin/python      -> real py3.11+

    ``paths.py`` is symlinked from the real source tree so the resolver
    invokes the actual production code. The venv is minimal (just
    ``bin/python`` pointing at a real interpreter) — no metadata file means
    the resolver picks it up on step 4 of its precedence ladder ("first
    executable {daemon_dir}/untracked/venv-*/bin/python — scan fallback").
    """
    daemon_dir = tmp_path / "daemon_dir"

    paths_target = daemon_dir / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
    paths_target.parent.mkdir(parents=True)
    os.symlink(PATHS_PY, paths_target)

    venv_dir = daemon_dir / "untracked" / "venv-py311-acceptance"
    venv_bin = venv_dir / "bin"
    venv_bin.mkdir(parents=True)
    os.symlink(_real_python(), venv_bin / "python")

    return daemon_dir


def test_resolve_venv_succeeds_when_path_python3_is_broken(tmp_path: Path) -> None:
    """Field-regression test: hostile PATH must not break venv resolution.

    Reproduces the v3.9.0 field bug: ``python3`` on PATH is broken (lies
    about being 3.9, crashes on ``import tomllib``), but a usable venv
    exists at ``$DAEMON_DIR/untracked/venv-*/bin/python``.

    Pre-fix v3.9.0 behaviour: the SSOT-invoking wrappers shelled out to
    bare ``python3`` and silenced stderr, surfacing a generic "venv not
    found" message that hid the real ``ModuleNotFoundError``.

    Post-fix v3.9.1 behaviour: the wrapper invokes the venv's own
    ``bin/python`` directly, never touching ``python3`` on PATH. Stderr is
    NOT silenced, so any real failure surfaces with its actual cause.

    Assertions:
      - Resolver exits 0 (success).
      - ``PYTHON`` is exported and points at the venv-resident interpreter.
      - The hostile fake on PATH was NOT consulted (its path does not
        appear in stdout/stderr; if it had been called, its
        ``ModuleNotFoundError`` would surface in stderr).
    """
    fake_path_dir = _build_fake_path_dir(tmp_path)
    daemon_dir = _build_daemon_dir_with_venv(tmp_path)
    expected_python = daemon_dir / "untracked" / "venv-py311-acceptance" / "bin" / "python"

    env = {
        "PATH": str(fake_path_dir),
        "HOME": str(tmp_path),
        "DAEMON_DIR": str(daemon_dir),
    }
    cmd = [
        BASH,
        "-c",
        f'set -uo pipefail; source "{RESOLVE_VENV_SCRIPT}" && ' f'echo "RESOLVED=$PYTHON"',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)

    assert result.returncode == 0, (
        f"resolver must succeed when a venv exists, even with a broken PATH python3. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    resolved_line = ""
    for line in result.stdout.splitlines():
        if line.startswith("RESOLVED="):
            resolved_line = line.split("=", 1)[1]
            break
    assert resolved_line, f"resolver did not export PYTHON. stdout={result.stdout!r}"
    assert Path(resolved_line) == expected_python, (
        f"resolver must select the venv-resident interpreter, NOT the fake "
        f"python3 on PATH. Expected={expected_python}, got={resolved_line}"
    )

    assert "ModuleNotFoundError" not in result.stderr, (
        f"resolver must NOT have invoked the broken PATH python3 — its "
        f"ModuleNotFoundError leaked into stderr. stderr={result.stderr!r}"
    )


def test_resolve_venv_fails_fast_with_directive_when_no_venv(tmp_path: Path) -> None:
    """Decision 2 contract: missing venv must fail loudly, not silently.

    Pre-fix v3.9.0 behaviour: on a fresh project with no venv, the wrappers
    silently fell back to the retired ``untracked/venv/bin/python`` legacy
    path, then to bare ``python3``, masking the real "no venv exists yet"
    state behind a confusing generic error.

    Post-fix v3.9.1 behaviour: when no ``$DAEMON_DIR/untracked/venv-*/bin/python``
    exists and ``HOOKS_DAEMON_PYTHON``/``HOOKS_DAEMON_VENV_PATH`` are unset,
    the resolver exits non-zero with a directive pointing the user at
    ``/hooks-daemon install``.
    """
    daemon_dir = tmp_path / "daemon_dir"
    paths_target = daemon_dir / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
    paths_target.parent.mkdir(parents=True)
    os.symlink(PATHS_PY, paths_target)
    (daemon_dir / "untracked").mkdir()

    fake_path_dir = _build_fake_path_dir(tmp_path)

    env = {
        "PATH": str(fake_path_dir),
        "HOME": str(tmp_path),
        "DAEMON_DIR": str(daemon_dir),
    }
    cmd = [
        BASH,
        "-c",
        f'source "{RESOLVE_VENV_SCRIPT}" && echo "RESOLVED=$PYTHON"',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)

    assert result.returncode != 0, (
        f"resolver must fail fast when no venv exists — silent fallback "
        f"to legacy path or bare python3 would mask the user's broken "
        f"state. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined = result.stdout + "\n" + result.stderr
    assert "install" in combined.lower() or "venv" in combined.lower(), (
        f"failure message must direct the user at the install command. " f"stderr={result.stderr!r}"
    )
    assert "RESOLVED=" not in result.stdout or "RESOLVED=" + os.linesep in (
        result.stdout + os.linesep
    ), (f"resolver must not export PYTHON when resolution fails. " f"stdout={result.stdout!r}")
