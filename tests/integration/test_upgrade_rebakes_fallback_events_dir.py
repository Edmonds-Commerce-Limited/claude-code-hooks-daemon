"""N98: the upgrade's hook redeploy re-bakes a renamed fallback events dir.

Forwarders bake the resolved events dir only when it is an AF_UNIX fallback
(relay guard, nc rung). N98 puts a hostname tag in that name, so a forwarder
deployed by an older daemon carries a path nothing listens on any more. The
upgrade scripts call ``deploy_all_hooks`` unconditionally (Step 8 of
``upgrade_version.sh`` and its idempotent fast path), and that copies the stock
forwarder and regenerates it from config, so no separate regeneration step is
needed. This test pins that behaviour from a stale deployed forwarder.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.daemon.paths import (
    get_event_socket_dir_from_untracked,
    get_untracked_dir,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DEPLOY_SH = _REPO_ROOT / "scripts" / "install" / "hooks_deploy.sh"
_SOURCE_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"
_HOOK = "pre-tool-use"


def _seed_daemon_dir(daemon_dir: Path) -> None:
    source_hooks = daemon_dir / ".claude" / "hooks"
    source_hooks.mkdir(parents=True)
    for name in (_HOOK, "post-tool-use", "status-line"):
        (source_hooks / name).write_text((_SOURCE_HOOKS_DIR / name).read_text())
    (daemon_dir / "init.sh").write_text((_REPO_ROOT / "init.sh").read_text())
    (daemon_dir / "provision.sh").write_text((_REPO_ROOT / "provision.sh").read_text())


def test_upgrade_redeploy_replaces_a_stale_fallback_events_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("HOSTNAME", "host-a")
    paths._resolve_hostname_from_env.cache_clear()

    project_root = tmp_path / ("p" * 100)
    (project_root / ".claude").mkdir(parents=True)
    (project_root / ".claude" / "hooks-daemon.yaml").write_text(
        "daemon:\n  transport:\n    relay_enabled: true\n"
    )
    daemon_dir = tmp_path / "daemon"
    _seed_daemon_dir(daemon_dir)

    events_dir = get_event_socket_dir_from_untracked(get_untracked_dir(project_root))
    assert events_dir.parent == runtime
    # Name an older daemon would have baked: no hostname tag.
    prefix, _tag, suffix = events_dir.name.rsplit("-", 2)
    stale_dir = runtime / f"{prefix}-{suffix}"
    assert stale_dir != events_dir

    hooks_dir = project_root / ".claude" / "hooks"
    hooks_dir.mkdir()
    stale = hooks_dir / _HOOK
    stale.write_text(f'_rl_events_dir="${{HOOKS_DAEMON_EVENTS_DIR:-{stale_dir}}}"\n')

    script = f"""
set -euo pipefail
source "{_HOOKS_DEPLOY_SH}"
deploy_all_hooks "{project_root}" "{daemon_dir}" "normal" "{sys.executable}"
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        env=dict(os.environ),
    )

    assert result.returncode == 0, result.stderr
    deployed = stale.read_text()
    assert str(events_dir) in deployed
    assert str(stale_dir) not in deployed
