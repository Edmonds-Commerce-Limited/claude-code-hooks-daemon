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
``import claude_code_hooks_daemon`` succeeds); an unhealthy directory
auto-escalates to a forced repair instead of bailing.

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


def test_guard_auto_escalates_to_force_on_broken_install() -> None:
    """The guard must set --force (repair) rather than exit 0 on a broken dir.

    Static contract check on install.sh: the 'already installed' guard now
    consults _installation_is_healthy and, on the unhealthy branch, sets
    FORCE_FLAG="--force" instead of `exit 0`.
    """
    text = INSTALL_SH.read_text()
    assert "_installation_is_healthy" in text, "guard must call the health helper"
    guard_start = text.index('if [ -d "$DAEMON_DIR" ]')
    guard_region = text[guard_start : guard_start + 800]
    assert "_installation_is_healthy" in guard_region, "guard block must use the health check"
    assert (
        'FORCE_FLAG="--force"' in guard_region
    ), "unhealthy install must escalate to forced repair"
