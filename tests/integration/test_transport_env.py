"""Integration tests: `append_transport_probe_env_lines` (Plan 00290 Phase 5).

Pins the byte-identical-by-default contract for hooks-daemon.env: with no
config, or a config that leaves both transport rungs off, the function must
append nothing. Only an explicitly nc-enabled config threads a probe-derived
line in, closing the Phase 4 deferral recorded in the journal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRANSPORT_ENV_SH = _REPO_ROOT / "scripts" / "install" / "transport_env.sh"

_BASE_ENV_CONTENT = 'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'


def _run(
    project_root: Path, env_file: Path, *, venv_python: str = ""
) -> subprocess.CompletedProcess[str]:
    script = f"""
set -euo pipefail
source "{_TRANSPORT_ENV_SH}"
append_transport_probe_env_lines "{project_root}" "{env_file}" "{venv_python}"
"""
    bash = shutil.which("bash") or "/bin/bash"
    return subprocess.run(
        [bash, "-c", script],
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
    )


def _write_config(project_root: Path, transport_lines: str) -> None:
    config_dir = project_root / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    body = "daemon:\n  transport:\n" + textwrap.indent(transport_lines, "    ")
    (config_dir / "hooks-daemon.yaml").write_text(body)


def test_no_venv_python_leaves_env_file_untouched(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    env_file = tmp_path / "hooks-daemon.env"
    env_file.write_text(_BASE_ENV_CONTENT)

    result = _run(project_root, env_file, venv_python="")

    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == _BASE_ENV_CONTENT


def test_no_config_leaves_env_file_untouched(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    env_file = tmp_path / "hooks-daemon.env"
    env_file.write_text(_BASE_ENV_CONTENT)

    result = _run(project_root, env_file, venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == _BASE_ENV_CONTENT


def test_config_with_both_rungs_off_leaves_env_file_untouched(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_config(project_root, "relay_enabled: false\nnc_enabled: false\n")
    env_file = tmp_path / "hooks-daemon.env"
    env_file.write_text(_BASE_ENV_CONTENT)

    result = _run(project_root, env_file, venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == _BASE_ENV_CONTENT


def test_nc_enabled_appends_capability_line(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_config(project_root, "nc_enabled: true\n")
    env_file = tmp_path / "hooks-daemon.env"
    env_file.write_text(_BASE_ENV_CONTENT)

    # A stub `nc` with no -U in its usage text -> present but not-capable.
    # Prepended (not replacing PATH) so bash's own coreutils stay reachable.
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake_nc = fake_bin / "nc"
    fake_nc.write_text("#!/bin/sh\necho 'usage: nc [options]'\n")
    fake_nc.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    result = _run(project_root, env_file, venv_python=sys.executable)

    assert result.returncode == 0, result.stderr
    content = env_file.read_text()
    assert content.startswith(_BASE_ENV_CONTENT)
    assert 'HOOKS_DAEMON_NC_UNIX_CAPABLE="0"' in content
