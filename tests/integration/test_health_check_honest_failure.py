"""Plan 00122 BUG 4 — health-check.sh reports a reason on any non-zero exit.

The downstream macOS report observed ``health-check.sh`` exiting 1 with ZERO
output. Under ``set -euo pipefail`` an unguarded command failure (e.g. sourcing
``_resolve-venv.sh`` when venv resolution dies) terminates the script silently,
leaving the operator nothing to act on.

Fix: an ``EXIT`` trap that, on a non-zero exit, prints a clear reason (script
name, exit code, failing line) to stderr. On success it stays silent.

This test copies health-check.sh next to a stub ``_resolve-venv.sh`` that
exits non-zero, runs it against a synthetic project, and asserts the script
exits non-zero WITH a reason on stderr (no silent failure). Bootstrap is
skipped via ``HOOKS_DAEMON_SKIP_BOOTSTRAP=1`` to keep the test offline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HEALTH_CHECK = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "health-check.sh"
)
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30


def _setup(tmp_path: Path) -> Path:
    """Project with a copied health-check.sh + a failing stub _resolve-venv.sh."""
    project = tmp_path / "project"
    scripts_dir = project / ".claude" / "hooks-daemon" / "scripts"
    scripts_dir.mkdir(parents=True)
    (project / ".claude" / "hooks-daemon.yaml").write_text("self_install_mode: false\n")

    shutil.copy(HEALTH_CHECK, scripts_dir / "health-check.sh")
    # Stub sibling that dies non-zero under set -e (simulates a venv-resolution
    # failure) — the exact silent-exit shape the trap must make honest.
    (scripts_dir / "_resolve-venv.sh").write_text("#!/bin/bash\nexit 3\n")
    return project


def _run(project: Path) -> subprocess.CompletedProcess[str]:
    script = project / ".claude" / "hooks-daemon" / "scripts" / "health-check.sh"
    env = os.environ.copy()
    env["HOOKS_DAEMON_SKIP_BOOTSTRAP"] = "1"
    return subprocess.run(
        [BASH, str(script)],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_non_zero_exit_emits_reason(tmp_path: Path) -> None:
    project = _setup(tmp_path)
    result = _run(project)

    assert result.returncode != 0, "stub _resolve-venv.sh exits 3 — health-check must fail"
    combined = (result.stdout + result.stderr).strip()
    assert combined, (
        "BUG 4: health-check.sh exited non-zero with ZERO output — it must emit "
        "a reason on failure."
    )
    # The trap should name the failure (script + exit code).
    assert "health-check" in combined.lower(), (
        f"failure message should identify the script.\noutput:\n{combined}"
    )
    assert "3" in combined, f"failure message should surface the exit code.\noutput:\n{combined}"
