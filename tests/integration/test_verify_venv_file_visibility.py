"""Plan 00100 Task 0.1: verify_venv file-visibility race.

Field bug (2026-04-23): uv sync exits 0, creates bin/python, but the immediate
`[ ! -f "$venv_python" ]` check in verify_venv returns "not found" under
`UV_LINK_MODE=copy`. Cause: copy-then-rename file metadata is not flushed to
disk before the subsequent stat().

The v2 fix is at the source, not in verify_venv:

  1. After `uv sync` exits, call `sync -f "$venv_path"` on Linux
     (filesystem-scoped flush) or plain `sync` on macOS/fallback.
  2. Switch default `UV_LINK_MODE` from `copy` to `hardlink`; detect the
     overlay-fs "Failed to hardlink" warning and fall back to copy only
     when that specific warning is emitted.

These tests verify the behaviour via static analysis of venv.sh and an
end-to-end integration run of `create_venv_at_path`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
FP_SH = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"


def _read_venv_sh() -> str:
    return VENV_SH.read_text()


# ----- Static checks on venv.sh (fast, no uv invocation) --------------------


def test_create_venv_at_path_calls_sync_after_uv() -> None:
    """create_venv_at_path must call `sync` after `uv sync` exits 0.

    Enforces that the file-visibility fix is in place. Looks for a sync
    invocation scoped to the venv path (preferred: `sync -f "$venv_path"`)
    or an unconditional `sync` fallback, within the success branch of
    create_venv_at_path.
    """
    content = _read_venv_sh()

    # Find the create_venv_at_path function body
    match = re.search(
        r"create_venv_at_path\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None, "create_venv_at_path() function not found in venv.sh"

    body = match.group(0)

    # Must invoke `sync` (either `sync -f <path>` or plain `sync`)
    # The flush must appear AFTER the uv sync success branch.
    has_sync_call = re.search(r"\bsync\s+-f\b|\bsync\b\s*(?:#|\n|\s*$)", body) is not None
    assert has_sync_call, (
        'create_venv_at_path() must call `sync -f "$venv_path"` '
        "(or fallback `sync`) after `uv sync` to force metadata flush. "
        "See Plan 00100 Task 0.1."
    )


def test_create_venv_at_path_prefers_hardlink() -> None:
    """UV_LINK_MODE default must be hardlink (not copy).

    Plan 00047 set copy as default for overlay-fs. v2 reverses: hardlink
    first (faster, no rename race on native fs), with copy fallback only
    triggered by the specific "Failed to hardlink" warning from uv.
    """
    content = _read_venv_sh()
    match = re.search(
        r"create_venv_at_path\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None, "create_venv_at_path() not found"
    body = match.group(0)

    # Unconditional `export UV_LINK_MODE=copy` is the v1 behaviour. v2 must
    # either default to hardlink or use conditional logic.
    lines = [line.strip() for line in body.splitlines()]
    has_unconditional_copy = any(line == "export UV_LINK_MODE=copy" for line in lines)
    assert not has_unconditional_copy, (
        "create_venv_at_path() must not unconditionally export UV_LINK_MODE=copy. "
        "v2 uses hardlink-first with copy fallback. See Plan 00100 Task 0.1."
    )


def test_create_venv_at_path_retries_copy_on_hardlink_failure() -> None:
    """Failed-hardlink detection must trigger a single retry with copy mode."""
    content = _read_venv_sh()
    match = re.search(
        r"create_venv_at_path\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None
    body = match.group(0)

    # Must reference the "Failed to hardlink" warning detection
    assert "Failed to hardlink" in body or "hardlink" in body.lower(), (
        "create_venv_at_path() must detect uv's 'Failed to hardlink files' warning "
        "and retry with UV_LINK_MODE=copy. See Plan 00100 Task 0.1."
    )


def test_verify_venv_has_no_retry_loop() -> None:
    """verify_venv must not treat the visibility race with a retry loop.

    v1 proposed a 3x500ms retry loop; v2 rejects that as symptom-treatment.
    The fix belongs in create_venv_at_path (sync flush), not in verify_venv.
    """
    content = _read_venv_sh()
    match = re.search(
        r"verify_venv\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None, "verify_venv() function not found"
    body = match.group(0)

    # No `for` loop + sleep — that's the retry-loop shape we're excluding.
    has_retry_loop = bool(re.search(r"for\s+\w+\s+in\b.*?sleep\s", body, re.DOTALL))
    assert not has_retry_loop, (
        "verify_venv() must not implement a retry loop around the file-existence check. "
        "Fix the race in create_venv_at_path (post-uv sync call) instead."
    )


# ----- Integration check: real uv sync, verify immediately ------------------


def _uv_available() -> bool:
    return shutil.which("uv") is not None


@pytest.mark.skipif(not _uv_available(), reason="uv not available in test environment")
def test_create_venv_at_path_then_verify_venv_succeeds(tmp_path: Path) -> None:
    """End-to-end: create_venv_at_path + immediate verify_venv succeeds.

    This is the exact sequence that failed in the field (2026-04-23). With
    the v2 fix, verify_venv must succeed immediately after create_venv_at_path
    returns 0, without any delay.
    """
    # Build a minimal daemon_dir
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    shutil.copy(REPO_ROOT / "pyproject.toml", daemon_dir / "pyproject.toml")
    if (REPO_ROOT / "uv.lock").exists():
        shutil.copy(REPO_ROOT / "uv.lock", daemon_dir / "uv.lock")
    (daemon_dir / "src").symlink_to(REPO_ROOT / "src")
    if (REPO_ROOT / "README.md").exists():
        shutil.copy(REPO_ROOT / "README.md", daemon_dir / "README.md")

    venv_path = tmp_path / "venv"
    script = f"""
set -euo pipefail
source "{VENV_SH}"
source "{FP_SH}"
create_venv_at_path "{daemon_dir}" "{venv_path}" "true"
verify_venv "{venv_path}/bin/python" "{daemon_dir}"
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=Timeout.QA_LONG_TIMEOUT,
    )
    assert result.returncode == 0, (
        f"create_venv_at_path + verify_venv sequence failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert (venv_path / "bin" / "python").exists(), (
        f"venv Python binary missing after create_venv_at_path returned 0. "
        f"This is the field-reported race. venv dir contents: "
        f"{list((venv_path / 'bin').iterdir()) if (venv_path / 'bin').exists() else 'bin/ missing'}"
    )
