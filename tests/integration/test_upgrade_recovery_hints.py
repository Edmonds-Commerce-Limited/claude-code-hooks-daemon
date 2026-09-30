r"""Plan 00114 Phase 4 (F4) — surface recovery hints in hard-failure messages.

Field report ``untracked/hooks-daemon-upgrade-broken.md`` (2026-05-29): the only
thing that unstuck the client was ``HOOKS_DAEMON_SKIP_BOOTSTRAP=1`` — an
internal env var surfaced nowhere in the error output. A client without an
agent willing to read the shim source would be hard stuck.

F4 makes the remaining hard-failure paths self-documenting:

  1. Layer 1 ``scripts/upgrade.sh`` python-discovery ``_fail`` (when even the
     F2 self-fetch cannot obtain ``python_discovery.sh``) must name actionable
     recovery: run the target's own Layer 1 out of the installed clone, and
     the ``HOOKS_DAEMON_SKIP_BOOTSTRAP=1`` escape hatch.
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
    # Plan 00376: the recovery is the TARGET's own Layer 1 with its lib/ beside
    # it. HOOKS_DAEMON_PYTHON is not one: the missing helper is what reads it.
    assert "archive VERSION scripts" in combined, (
        "the discovery-helper failure must name the target's own Layer 1, "
        f"extracted with its lib/.\n--- output ---\n{combined}"
    )
    assert "HOOKS_DAEMON_PYTHON" not in combined, (
        "HOOKS_DAEMON_PYTHON cannot recover a missing discovery helper, which "
        f"is the code that reads it.\n--- output ---\n{combined}"
    )
    assert "HOOKS_DAEMON_SKIP_BOOTSTRAP=1" in combined, (
        "F4: the discovery-helper failure must surface the "
        "HOOKS_DAEMON_SKIP_BOOTSTRAP=1 escape hatch.\n"
        f"--- output ---\n{combined}"
    )
    assert ".claude/hooks-daemon" in combined, (
        "F4: the failure should point the user at the installed clone."
        f"\n--- output ---\n{combined}"
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


def test_shim_fetch_failure_recommends_the_targets_own_layer1(tmp_path: Path) -> None:
    """Review MAJOR 2: the INSTALLED Layer 1 may predate the pre-deploy gate.

    It then reports a stopped upgrade as success and rejects the confirmation
    flag, so the recovery runs the target release's own Layer 1 out of the
    clone instead, and a pinned ref must be no older than the target.
    """
    combined = _run_shim_with_unreachable_fetch(tmp_path).stderr
    assert "show" in combined and ":scripts/upgrade.sh" in combined, combined
    assert "v3.16.0" not in combined, "an old pinned ref brings back a pre-gate Layer 1"


def _help(script: Path, *args: str) -> str:
    result = subprocess.run(
        [BASH, str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    return result.stdout + result.stderr


def test_every_usage_line_names_the_confirmation_flag() -> None:
    """Review NIT 2: the shim's --help and Layer 1's unknown-option usage."""
    assert "--skip-reading-confirmation=" in _help(SKILL_UPGRADE_SH, "--help")
    assert "--skip-reading-confirmation=" in _help(LAYER1_UPGRADE_SH, "--no-such-flag")
