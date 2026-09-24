"""Plan 00122 BUG 3 — skill install.sh "already installed" guard checks health.

The skill bootstrap ``install.sh`` bailed out of an existing install when the
``.claude/hooks-daemon/`` directory merely EXISTED:

    if [ -d "$DAEMON_DIR" ] && [ "$FORCE_FLAG" != "--force" ]; then
        echo "Daemon is already installed ..."; exit 0
    fi

A broken/partial install (directory present, but no working venv / the package
does not import) therefore could not be repaired with the documented
``/hooks-daemon install`` — only ``--force`` worked. The fix introduces
``_installation_is_healthy`` (venv python exists AND
``import claude_code_hooks_daemon`` succeeds). An unhealthy directory holding
a whole clone is repaired IN PLACE with the clone's own ``repair``, and never
escalated to ``--force`` (Plan 00456, GitHub issue #53: the force path's
``rm -rf`` took every other environment's venv with it).

These tests extract ``_installation_is_healthy`` from install.sh and exercise
it directly with stub venv pythons, mirroring the brace-extraction approach in
``test_init_sh_venv_resolution.py``.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "install.sh"
)
_TIMEOUT_SECONDS = 30


def _extract_function(name: str) -> str:
    text = INSTALL_SH.read_text()
    start = text.index(f"{name}() {{")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise RuntimeError(f"Could not find matching brace for {name}")
    return text[start:end]


def _make_venv_python(daemon_dir: Path, fingerprint: str, *, import_ok: bool) -> None:
    """Create ``$daemon_dir/untracked/venv-{fingerprint}/bin/python`` stub.

    The stub exits 0 for an ``import`` check when ``import_ok`` is True, else 1
    (mimicking ``ModuleNotFoundError``).
    """
    py = daemon_dir / "untracked" / f"venv-{fingerprint}" / "bin" / "python"
    py.parent.mkdir(parents=True, exist_ok=True)
    exit_code = 0 if import_ok else 1
    py.write_text(f"#!/bin/bash\nexit {exit_code}\n")
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_health_check(daemon_dir: Path) -> int:
    fn = _extract_function("_installation_is_healthy")
    script = f"#!/bin/bash\nset -uo pipefail\n{fn}\n_installation_is_healthy '{daemon_dir}'\n"
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    return result.returncode


def test_healthy_when_venv_python_imports(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "hooks-daemon"
    _make_venv_python(daemon_dir, "py311-deadbeef", import_ok=True)
    assert _run_health_check(daemon_dir) == 0


def test_unhealthy_when_directory_has_no_venv(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "hooks-daemon"
    daemon_dir.mkdir()
    assert _run_health_check(daemon_dir) != 0


def test_unhealthy_when_package_import_fails(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "hooks-daemon"
    _make_venv_python(daemon_dir, "py311-deadbeef", import_ok=False)
    assert _run_health_check(daemon_dir) != 0


def test_guard_never_escalates_to_force_on_a_broken_install() -> None:
    """The guard must repair, not force, when the probe fails (Plan 00456).

    Plan 00122 made an unhealthy directory escalate to --force. That repaired a
    broken single-environment install, but the force path's rm -rf also
    deleted every OTHER environment's venv, and in GitHub issue #53's state the
    probe can never pass. The guard still consults _installation_is_healthy,
    and nothing in the script may set FORCE_FLAG except the caller's own
    argument. The behaviour itself is pinned end to end by
    test_skill_install_never_auto_forces.py.
    """
    text = INSTALL_SH.read_text()
    guard_start = text.index('if [ -d "$DAEMON_DIR" ] && [ "$FORCE_FLAG" != "--force" ]')
    guard_region = text[guard_start : text.index("\nfi\n", guard_start)]
    assert "_installation_is_healthy" in guard_region, "guard block must use the health check"
    assert 'FORCE_FLAG="--force"' not in text, "only the caller may ask for --force"
    assert 'hooks-daemon" repair' in guard_region, "a whole clone is repaired in place"
