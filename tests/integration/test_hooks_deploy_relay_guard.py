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

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.install.forwarder_generator import strip_relay_guard_block

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
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
    )


def _seed_daemon_dir(daemon_dir: Path) -> None:
    """A minimal daemon_dir shape deploy_hook_scripts/deploy_init_script needs."""
    source_hooks = daemon_dir / ".claude" / "hooks"
    source_hooks.mkdir(parents=True)
    for name in ("pre-tool-use", "post-tool-use", "status-line"):
        (source_hooks / name).write_text((_SOURCE_HOOKS_DIR / name).read_text())
    (daemon_dir / "init.sh").write_text((_REPO_ROOT / "init.sh").read_text())


def test_default_config_deploy_is_byte_identical(tmp_path: Path) -> None:
    """Default (disabled) client config must deploy the GUARD-FREE canonical
    shape (Plan 00290 F1 fix). This repo dogfoods the relay (Plan 00290
    Phase 6+), so ``_SOURCE_HOOKS_DIR`` (this repo's own tracked
    ``.claude/hooks/*``, the deploy source) may already carry a guard block
    pointing at THIS repo's own paths — a disabled client config must strip
    that away rather than copy it forward verbatim (the canary-proven bug:
    a client's hooks silently answered by another project's daemon)."""
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_daemon_dir(daemon_dir)
    project_root.mkdir()

    result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    for name in ("pre-tool-use", "post-tool-use", "status-line"):
        deployed = (project_root / ".claude" / "hooks" / name).read_text()
        source = (_SOURCE_HOOKS_DIR / name).read_text()
        assert deployed == strip_relay_guard_block(
            source
        ), f"{name}: deployed content diverged from the guard-free canonical shape"
        assert "relay hot path" not in deployed


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


def _seed_contaminated_daemon_dir(daemon_dir: Path, foreign_untracked_dir: str) -> None:
    """A daemon_dir whose OWN tracked hooks already carry a relay guard
    baked for a DIFFERENT project (simulates this repo's dogfood state —
    Plan 00290 F1 canary finding — without depending on the live repo
    happening to be in that state right now)."""
    from claude_code_hooks_daemon.config.models import TransportConfig
    from claude_code_hooks_daemon.install.forwarder_generator import (
        INIT_SH_ANCHOR,
        build_relay_guard_block,
    )

    source_hooks = daemon_dir / ".claude" / "hooks"
    source_hooks.mkdir(parents=True)
    for name in ("pre-tool-use", "post-tool-use", "status-line"):
        plain = (_SOURCE_HOOKS_DIR / name).read_text()
        guard = build_relay_guard_block(
            name, TransportConfig(relay_enabled=True), Path(foreign_untracked_dir)
        )
        contaminated = plain.replace(INIT_SH_ANCHOR, guard + INIT_SH_ANCHOR)
        (source_hooks / name).write_text(contaminated)
    (daemon_dir / "init.sh").write_text((_REPO_ROOT / "init.sh").read_text())


def test_f1_contaminated_source_deploy_strips_foreign_guard_by_default(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_contaminated_daemon_dir(daemon_dir, "/some/other/project/untracked")
    project_root.mkdir()

    result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    deployed = (project_root / ".claude" / "hooks" / "pre-tool-use").read_text()
    assert "relay hot path" not in deployed
    assert "/some/other/project/untracked" not in deployed


def test_f2_contaminated_source_deploy_with_relay_enabled_uses_client_paths(
    tmp_path: Path,
) -> None:
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_contaminated_daemon_dir(daemon_dir, "/some/other/project/untracked")
    (project_root / ".claude").mkdir(parents=True)
    (project_root / ".claude" / "hooks-daemon.yaml").write_text(
        "daemon:\n  transport:\n    relay_enabled: true\n"
    )

    result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    deployed = (project_root / ".claude" / "hooks" / "pre-tool-use").read_text()
    assert "/some/other/project/untracked" not in deployed
    assert "relay hot path" in deployed
    assert str(project_root / ".claude" / "hooks-daemon" / "untracked") in deployed


def test_f4_flipping_relay_off_strips_guard_from_previously_generated_deploy(
    tmp_path: Path,
) -> None:
    daemon_dir = tmp_path / "daemon"
    project_root = tmp_path / "project"
    _seed_daemon_dir(daemon_dir)
    config_path = project_root / ".claude" / "hooks-daemon.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("daemon:\n  transport:\n    relay_enabled: true\n")

    enabled_result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)
    assert enabled_result.returncode == 0, enabled_result.stderr
    enabled_deployed = (project_root / ".claude" / "hooks" / "pre-tool-use").read_text()
    assert "relay hot path" in enabled_deployed  # sanity: guard really is there

    config_path.write_text("daemon:\n  transport:\n    relay_enabled: false\n")
    disabled_result = _run_deploy(daemon_dir, project_root, "normal", venv_python=sys.executable)
    assert disabled_result.returncode == 0, disabled_result.stderr

    disabled_deployed = (project_root / ".claude" / "hooks" / "pre-tool-use").read_text()
    assert "relay hot path" not in disabled_deployed
    source = (_SOURCE_HOOKS_DIR / "pre-tool-use").read_text()
    assert disabled_deployed == strip_relay_guard_block(source)


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
