"""Plan 00104 Phase 3 Task 3.2 — pipefail cascade test (xfail driver for Phase 4).

Risk F17 in PLAN.md: the canonical resolver library will be sourced into
arbitrary caller shells. Many of those callers run under
``set -euo pipefail`` (e.g. ``init.sh``). The contract Phase 4 must enforce:

  *Sourcing the resolver MUST NOT poison the caller's shell options nor kill
   the caller via a cascading pipefail/errexit failure.*

This is currently NOT met by ``scripts/venv-include.bash``:

  - Line 8 unconditionally runs ``set -euo pipefail``.
  - Bash sourcing executes in the caller's shell context, so the caller's
    pre-existing options are silently overwritten.
  - A caller that previously had ``set +e`` is now under errexit, and the
    very next non-zero command (a missing optional dep check, a
    diagnostic ``grep``, anything) kills the caller dead.

The test below sources the current shim from a controlled fixture and
verifies the caller's shell-option state is preserved across the source.
Today it fails. Phase 4 Task 4.1 specifies the canonical library uses an
internal subshell (or save/restore) so this xfail-strict flips to xpass.

The fixture mirrors ``test_venv_include_resolution.py`` so the two harnesses
share shape — diverging only in the assertion. We deliberately avoid
touching ``test_venv_include_resolution.py`` itself because that file
documents *current* behaviour; this one documents the *target*.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_INCLUDE = REPO_ROOT / "scripts" / "venv-include.bash"
PATHS_SSOT = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"


def _setup_fake_project(tmp_path: Path) -> Path:
    """Replicate the fixture from test_venv_include_resolution.py."""
    project = tmp_path / "project"
    (project / "scripts" / "install").mkdir(parents=True)
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    ssot_parent = project / "src" / "claude_code_hooks_daemon" / "daemon"
    ssot_parent.mkdir(parents=True)
    (ssot_parent / "paths.py").symlink_to(PATHS_SSOT)
    return project


def _fake_venv(path: Path) -> None:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python3").symlink_to(sys.executable)


def _run_caller_with_options(
    project: Path, pre_source_options: str, post_source: str
) -> tuple[int, str, str]:
    """Run a caller bash script that:

      1. Applies ``pre_source_options`` (e.g. ``set +e``).
      2. Sources ``venv-include.bash`` from the fixture project.
      3. Runs ``post_source`` after the source.

    Returns ``(returncode, stdout, stderr)``.
    """
    fake_script = project / "scripts" / "venv-include.bash"
    caller = f"{pre_source_options}\n" f'source "{fake_script}"\n' f"{post_source}\n"
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    result = subprocess.run(
        ["bash", "-c", caller],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def test_caller_under_default_options_survives_sourcing(tmp_path: Path) -> None:
    """Smoke: the resolver must succeed when a venv exists in the project.

    This test passes today and stays as a sanity check that the fixture
    is shaped correctly. It also pins the contract that the resolver does
    NOT itself crash the caller during the *successful* path.
    """
    project = _setup_fake_project(tmp_path)
    _fake_venv(project / "untracked" / "venv")

    rc, stdout, stderr = _run_caller_with_options(
        project,
        pre_source_options="# default options",
        post_source='echo "POST_SOURCE_REACHED"',
    )
    assert rc == 0, f"Caller died unexpectedly. stderr=\n{stderr}"
    assert "POST_SOURCE_REACHED" in stdout, f"Marker missing. stdout={stdout!r} stderr={stderr!r}"


def test_resolver_when_sourced_under_pipefail_does_not_kill_caller_shell(
    tmp_path: Path,
) -> None:
    """Caller has errexit OFF and runs a deliberately failing command
    after sourcing. The resolver MUST NOT poison the caller's shell
    options — otherwise the failing command kills the caller and the
    post-source marker is never printed.

    Plan 00104 Phase 4 Task 3.2 contract: the canonical library runs
    its internal logic in a subshell, and ``scripts/venv-include.bash``
    no longer enables errexit at file top — so the caller's pre-source
    shell-option state survives sourcing. ``false`` is non-fatal and
    ``STILL_ALIVE`` reaches stdout.
    """
    project = _setup_fake_project(tmp_path)
    _fake_venv(project / "untracked" / "venv")

    rc, stdout, stderr = _run_caller_with_options(
        project,
        pre_source_options="set +e\nset +o pipefail",
        post_source='false\necho "STILL_ALIVE"',
    )

    assert "STILL_ALIVE" in stdout, (
        "Caller was killed by the resolver poisoning its shell options.\n"
        f"returncode={rc}\nstdout={stdout!r}\nstderr={stderr!r}\n"
        "Phase 4 Task 4.1: canonical library must run internal logic in a "
        "subshell (or save/restore options) so the caller's pre-source "
        "shell-option state survives sourcing."
    )
    assert rc == 0, (
        f"Caller exited non-zero ({rc}) despite reaching STILL_ALIVE marker. " f"stderr=\n{stderr}"
    )
