"""Tests for the ``forwarder_generator`` CLI/regeneration entry point.

``regenerate_deployed_hooks`` / ``main`` are what ``hooks_deploy.sh`` invokes
after its plain ``cp`` deploy step (Task 4.1) — this is the seam that turns a
byte-identical copy into the relay-guarded form when config opts in.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.install.forwarder_generator import (
    main,
    regenerate_deployed_hooks,
)

_SAMPLE = """#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

send_request_stdin "PreToolUse"
"""


def _make_project(tmp_path: Path, *, config_yaml: str | None) -> Path:
    project_root = tmp_path / "project"
    hooks_dir = project_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "pre-tool-use").write_text(_SAMPLE)
    (hooks_dir / "post-tool-use").write_text(_SAMPLE.replace("PreToolUse", "PostToolUse"))
    if config_yaml is not None:
        (project_root / ".claude" / "hooks-daemon.yaml").write_text(config_yaml)
    return project_root


def test_no_config_file_is_a_noop(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path, config_yaml=None)
    hooks_dir = project_root / ".claude" / "hooks"
    before = (hooks_dir / "pre-tool-use").read_text()

    rewritten = regenerate_deployed_hooks(project_root, hooks_dir)

    assert rewritten == []
    assert (hooks_dir / "pre-tool-use").read_text() == before


def test_relay_disabled_config_is_a_noop(tmp_path: Path) -> None:
    project_root = _make_project(
        tmp_path,
        config_yaml="daemon:\n  transport:\n    relay_enabled: false\n",
    )
    hooks_dir = project_root / ".claude" / "hooks"
    before = (hooks_dir / "pre-tool-use").read_text()

    rewritten = regenerate_deployed_hooks(project_root, hooks_dir)

    assert rewritten == []
    assert (hooks_dir / "pre-tool-use").read_text() == before


def test_relay_enabled_config_rewrites_every_forwarder(tmp_path: Path) -> None:
    project_root = _make_project(
        tmp_path,
        config_yaml="daemon:\n  transport:\n    relay_enabled: true\n",
    )
    hooks_dir = project_root / ".claude" / "hooks"

    rewritten = regenerate_deployed_hooks(project_root, hooks_dir)

    assert sorted(rewritten) == ["post-tool-use", "pre-tool-use"]
    content = (hooks_dir / "pre-tool-use").read_text()
    assert "relay hot path" in content
    assert '_rl_sock="$_rl_dir/events$_rl_sfx/pre-tool-use.sock"' in content
    post_content = (hooks_dir / "post-tool-use").read_text()
    assert '_rl_sock="$_rl_dir/events$_rl_sfx/post-tool-use.sock"' in post_content


def test_nc_only_enabled_config_rewrites_every_forwarder(tmp_path: Path) -> None:
    """Regression: nc_enabled must apply independently of relay_enabled.

    `regenerate_deployed_hooks` previously early-returned `[]` whenever
    `relay_enabled` was False, even when `nc_enabled` was True — silently
    skipping the nc-only rung's forwarder-side transform through the
    production CLI/install path entirely (found during Plan 00290 Phase 6
    measurement).
    """
    project_root = _make_project(
        tmp_path,
        config_yaml="daemon:\n  transport:\n    nc_enabled: true\n",
    )
    hooks_dir = project_root / ".claude" / "hooks"

    rewritten = regenerate_deployed_hooks(project_root, hooks_dir)

    assert sorted(rewritten) == ["post-tool-use", "pre-tool-use"]
    content = (hooks_dir / "pre-tool-use").read_text()
    assert "relay hot path" not in content
    assert 'send_request_stdin "PreToolUse" "" "pre-tool-use"' in content
    post_content = (hooks_dir / "post-tool-use").read_text()
    assert 'send_request_stdin "PostToolUse" "" "post-tool-use"' in post_content


def test_regenerate_is_idempotent(tmp_path: Path) -> None:
    project_root = _make_project(
        tmp_path,
        config_yaml="daemon:\n  transport:\n    relay_enabled: true\n",
    )
    hooks_dir = project_root / ".claude" / "hooks"

    first = regenerate_deployed_hooks(project_root, hooks_dir)
    assert first != []

    second = regenerate_deployed_hooks(project_root, hooks_dir)
    assert second == [], "already-generated content must not be rewritten again"


def test_cli_main_missing_hooks_dir_errors(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    missing = project_root / ".claude" / "hooks"

    rv = main(["--project-root", str(project_root), "--hooks-dir", str(missing)])

    assert rv == 1


def test_cli_main_success(tmp_path: Path) -> None:
    project_root = _make_project(
        tmp_path,
        config_yaml="daemon:\n  transport:\n    relay_enabled: true\n",
    )
    hooks_dir = project_root / ".claude" / "hooks"

    rv = main(["--project-root", str(project_root), "--hooks-dir", str(hooks_dir)])

    assert rv == 0
    assert "relay hot path" in (hooks_dir / "pre-tool-use").read_text()
