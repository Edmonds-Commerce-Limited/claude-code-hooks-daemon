r"""Plan 00114 Phase 4 (F4) — surface recovery hints in hard-failure messages.

Field report ``untracked/hooks-daemon-upgrade-broken.md`` (2026-05-29): the only
thing that unstuck the client was ``HOOKS_DAEMON_SKIP_BOOTSTRAP=1`` — an
internal env var surfaced nowhere in the error output. A client without an
agent willing to read the shim source would be hard stuck.

F4 makes the remaining hard-failure paths self-documenting:

  1. Layer 1 ``scripts/upgrade.sh`` python-discovery ``_fail`` (when even the
     F2 self-fetch cannot obtain ``python_discovery.sh``) must name actionable
     recovery: run from the installed daemon dir, set ``HOOKS_DAEMON_PYTHON``,
     and the ``HOOKS_DAEMON_SKIP_BOOTSTRAP=1`` escape hatch.
  2. The skill thin-shim ``upgrade.sh`` fetch-failure path must mention the
     ``HOOKS_DAEMON_UPGRADE_REF`` pin and running the installed daemon's
     ``upgrade.sh`` directly.

These are behavioural assertions on the live scripts (run as subprocesses with
an unreachable ``file://`` base-URL to force each failure).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
SKILL_UPGRADE_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "upgrade.sh"
)
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 60


def _run_layer1_with_no_helper(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run Layer 1 from /tmp with no local helper and an unreachable fetch."""
    tmp_run_dir = tmp_path / "tmp-run"
    tmp_run_dir.mkdir()
    tmp_script = tmp_run_dir / "upgrade.sh"
    shutil.copy2(LAYER1_UPGRADE_SH, tmp_script)
    tmp_script.chmod(tmp_script.stat().st_mode | 0o755)

    project_root = tmp_path / "client-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()

    env = os.environ.copy()
    env["HOOKS_DAEMON_UPGRADE_BASE_URL"] = f"file://{tmp_path / 'no-such-base'}"
    env["HOOKS_DAEMON_UPGRADE_REF"] = "main"
    env["NO_COLOR"] = "1"

    return subprocess.run(
        [BASH, str(tmp_script), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_layer1_discovery_fail_names_recovery_hints(tmp_path: Path) -> None:
    """Layer 1's missing-helper abort must be actionable."""
    result = _run_layer1_with_no_helper(tmp_path)
    combined = result.stdout + result.stderr

    assert result.returncode != 0, "Expected Layer 1 to fail with no helper available"
    assert "HOOKS_DAEMON_PYTHON" in combined, (
        "F4: the discovery-helper failure must mention HOOKS_DAEMON_PYTHON as a "
        f"recovery.\n--- output ---\n{combined}"
    )
    assert "HOOKS_DAEMON_SKIP_BOOTSTRAP=1" in combined, (
        "F4: the discovery-helper failure must surface the "
        "HOOKS_DAEMON_SKIP_BOOTSTRAP=1 escape hatch.\n"
        f"--- output ---\n{combined}"
    )
    assert ".claude/hooks-daemon" in combined, (
        "F4: the failure should point the user at running from the installed "
        f"daemon dir.\n--- output ---\n{combined}"
    )


def _run_shim_with_unreachable_fetch(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    project_root = tmp_path / "fixture-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()
    (project_root / ".claude" / "hooks-daemon.yaml").write_text("daemon: {}\n")

    env = os.environ.copy()
    env["HOOKS_DAEMON_UPGRADE_BASE_URL"] = f"file://{tmp_path / 'does-not-exist'}"
    env["HOOKS_DAEMON_UPGRADE_REF"] = "main"
    env["HOOKS_DAEMON_SKIP_BOOTSTRAP"] = "1"
    env["NO_COLOR"] = "1"

    return subprocess.run(
        [BASH, str(SKILL_UPGRADE_SH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
        cwd=project_root,
    )


def test_shim_fetch_failure_names_recovery_hints(tmp_path: Path) -> None:
    """The thin-shim fetch failure must mention the ref pin and the manual run."""
    result = _run_shim_with_unreachable_fetch(tmp_path)
    combined = result.stdout + result.stderr

    assert result.returncode != 0, "Expected the shim to fail on an unreachable fetch"
    assert "HOOKS_DAEMON_UPGRADE_REF" in combined, (
        "F4: the shim fetch failure must mention the HOOKS_DAEMON_UPGRADE_REF "
        f"pin as a recovery.\n--- output ---\n{combined}"
    )
    assert ".claude/hooks-daemon" in combined, (
        "F4: the shim fetch failure should point at running the installed "
        f"daemon's upgrade.sh directly.\n--- output ---\n{combined}"
    )
