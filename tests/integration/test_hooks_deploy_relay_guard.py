"""Integration tests: `deploy_all_hooks` + the Plan 00290 relay-guard step.

Pins the success criterion from DESIGN-socket-relay.md §6.1 and PLAN.md's
"Success Criteria": default config produces a byte-identical deploy; opting
in inserts the guard block; self-install mode never regenerates (the
deployed tree IS this repository's own tracked source there).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DEPLOY_SH = _REPO_ROOT / "scripts" / "install" / "hooks_deploy.sh"
_SOURCE_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"


def _run_deploy(
    daemon_dir: Path,
    project_root: Path,
    install_mode: str,
    *,
    venv_python: str = "",
) -> subprocess.CompletedProcess[str]:
    script = f"""
set -euo pipefail
source "{_HOOKS_DEPLOY_SH}"
deploy_all_hooks "{project_root}" "{daemon_dir}" "{install_mode}" "{venv_python}"
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


def _seed_daemon_dir(daemon_dir: Path) -> None:
    """A minimal daemon_dir shape deploy_hook_scripts/deploy_init_script needs."""
    source_hooks = daemon_dir / ".claude" / "hooks"
    source_hooks.mkdir(parents=True)
    for name in ("pre-tool-use", "post-tool-use", "status-line"):
        (source_hooks / name).write_text((_SOURCE_HOOKS_DIR / name).read_text())
    (daemon_dir / "init.sh").write_text((_REPO_ROOT / "init.sh").read_text())


def test_default_config_deploy_is_byte_identical(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_daemon_dir(daemon_dir)
    project_root.mkdir()

    result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    for name in ("pre-tool-use", "post-tool-use", "status-line"):
        deployed = (project_root / ".claude" / "hooks" / name).read_text()
        source = (_SOURCE_HOOKS_DIR / name).read_text()
        assert deployed == source, f"{name}: deployed content diverged from source by default"


def test_no_venv_python_deploy_is_byte_identical(tmp_path: Path) -> None:
    """No venv python resolved (e.g. an early caller): generation step skips cleanly."""
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_daemon_dir(daemon_dir)
    project_root.mkdir()

    result = _run_deploy(daemon_dir, project_root, "normal", venv_python="")

    assert result.returncode == 0, result.stderr
    deployed = (project_root / ".claude" / "hooks" / "pre-tool-use").read_text()
    source = (_SOURCE_HOOKS_DIR / "pre-tool-use").read_text()
    assert deployed == source


def test_relay_enabled_config_inserts_guard(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_daemon_dir(daemon_dir)
    (project_root / ".claude").mkdir(parents=True)
    (project_root / ".claude" / "hooks-daemon.yaml").write_text(
        "daemon:\n  transport:\n    relay_enabled: true\n"
    )

    result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    deployed = (project_root / ".claude" / "hooks" / "pre-tool-use").read_text()
    assert "relay hot path" in deployed
    assert '_rl_sock="$_rl_events_dir/pre-tool-use.sock"' in deployed
    # The rest of the forwarder body is untouched.
    assert 'send_request_stdin "PreToolUse"' in deployed


def test_self_install_mode_never_regenerates_even_when_relay_enabled(tmp_path: Path) -> None:
    """Self-install target IS the source tree — must never be rewritten."""
    project_root = tmp_path / "project"
    hooks_dir = project_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    original = (_SOURCE_HOOKS_DIR / "pre-tool-use").read_text()
    (hooks_dir / "pre-tool-use").write_text(original)
    (project_root / "init.sh").write_text("#!/bin/bash\necho init\n")
    (project_root / ".claude" / "hooks-daemon.yaml").write_text(
        "daemon:\n  transport:\n    relay_enabled: true\n"
    )

    # In self-install mode daemon_dir == project_root by convention.
    result = _run_deploy(project_root, project_root, "self-install", venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    assert (
        hooks_dir / "pre-tool-use"
    ).read_text() == original, (
        "self-install mode must never rewrite the repo's own tracked forwarders"
    )


def test_generated_forwarder_still_syntactically_valid_after_deploy(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_daemon_dir(daemon_dir)
    (project_root / ".claude").mkdir(parents=True)
    (project_root / ".claude" / "hooks-daemon.yaml").write_text(
        "daemon:\n  transport:\n    relay_enabled: true\n"
    )

    result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)
    assert result.returncode == 0, result.stderr

    for name in ("pre-tool-use", "post-tool-use", "status-line"):
        deployed_path = project_root / ".claude" / "hooks" / name
        check = subprocess.run(["bash", "-n", str(deployed_path)], capture_output=True, text=True)
        assert check.returncode == 0, f"{name}: {check.stderr}"
