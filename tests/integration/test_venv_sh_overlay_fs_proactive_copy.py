r"""Plan 00114 Phase 3 (F3) — proactive copy mode on overlay-fs/NFS, no warning.

Field report ``untracked/hooks-daemon-upgrade-broken.md`` (2026-05-29) flags the
``⚠ uv hardlink failed (likely overlay-fs) — retrying …`` warning as noise
emitted on EVERY container/overlay-fs install. The hardlink-first approach
ALWAYS fails on overlay-fs, prints a scary warning, then retries with copy —
two syncs and a warning where one quiet sync would do.

F3 (Decision 3): detect the target filesystem with ``stat -f -c %T`` BEFORE the
first ``uv sync``. On hardlink-hostile filesystems (overlay/NFS) set
``UV_LINK_MODE=copy`` up front — one sync, no failed attempt, no warning (an
informational line at most). On normal disks keep hardlink-first. Respect an
explicit ``UV_LINK_MODE`` from the environment (no blanket ``unset``). The loud
warn-then-retry fallback is preserved for genuine hardlink failures the
detection did not anticipate.

This test stubs both ``uv`` and ``stat`` on PATH for determinism. The ``uv``
stub records, per invocation, whether ``UV_LINK_MODE`` was set in its env and
appends a line to a log; the ``stat`` stub reports a configurable fs type.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
BASH = shutil.which("bash") or "/bin/bash"

_HARDLINK_WARNING_FRAGMENT = "uv hardlink failed"
_TIMEOUT_SECONDS = 30


def _write_stub_dir(tmp_path: Path, fs_type: str, uv_log: Path) -> Path:
    """Create a PATH dir with stub `uv` and `stat` executables.

    - ``uv`` records whether UV_LINK_MODE is set in its env and creates the
      target venv (so verify steps in venv.sh do not abort), then exits 0.
      It never emits "Failed to hardlink" — proving the proactive path took a
      single, clean sync.
    - ``stat`` echoes the configured fs type (mimics ``stat -f -c %T``).
    """
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()

    uv_stub = stub_dir / "uv"
    uv_stub.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        # Stub uv. Record link-mode env and fabricate the venv.
        echo "uv_sync link_mode=${{UV_LINK_MODE:-UNSET}}" >> "{uv_log}"
        if [ -n "${{UV_PROJECT_ENVIRONMENT:-}}" ]; then
            mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
            : > "$UV_PROJECT_ENVIRONMENT/bin/python"
            chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
        fi
        exit 0
        """))
    uv_stub.chmod(0o755)

    stat_stub = stub_dir / "stat"
    stat_stub.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        # Stub stat. `stat -f -c %T <path>` reports the fs type.
        printf '%s\\n' "{fs_type}"
        exit 0
        """))
    stat_stub.chmod(0o755)

    return stub_dir


def _run_create_venv(
    tmp_path: Path,
    fs_type: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    (daemon_dir / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n')
    venv_path = daemon_dir / "untracked" / "venv-test"

    uv_log = tmp_path / "uv_calls.log"
    uv_log.write_text("")
    stub_dir = _write_stub_dir(tmp_path, fs_type, uv_log)

    harness = textwrap.dedent(f"""\
        set -euo pipefail
        export PATH="{stub_dir}:$PATH"
        . "{VENV_SH}"
        create_venv_at_path "{daemon_dir}" "{venv_path}"
        """)

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    # Drop any ambient UV_LINK_MODE so fs-detection (not a leaked env var from
    # another test or the host) drives the link-mode choice. The explicit-mode
    # case re-adds it via extra_env below.
    env.pop("UV_LINK_MODE", None)
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    log_lines = [ln for ln in uv_log.read_text().splitlines() if ln.strip()]
    return result, log_lines


def test_overlay_fs_uses_copy_mode_up_front_no_warning(tmp_path: Path) -> None:
    """On overlay-fs the first (and only) sync uses copy mode; no warning."""
    result, log_lines = _run_create_venv(tmp_path, fs_type="overlayfs")

    assert result.returncode == 0, (
        f"create_venv_at_path must succeed on overlay-fs.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert _HARDLINK_WARNING_FRAGMENT not in combined, (
        "F3: overlay-fs must NOT emit the 'uv hardlink failed' warning — copy "
        "mode should be chosen proactively before the first sync.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert len(log_lines) == 1, (
        f"F3: overlay-fs must run exactly ONE uv sync (no failed hardlink "
        f"attempt + retry). Got {len(log_lines)}: {log_lines}"
    )
    assert "link_mode=copy" in log_lines[0], (
        f"F3: the single overlay-fs sync must run with UV_LINK_MODE=copy.\n"
        f"uv log: {log_lines}"
    )


def test_normal_fs_uses_hardlink_first(tmp_path: Path) -> None:
    """On a normal disk the first sync is hardlink mode (UV_LINK_MODE unset)."""
    result, log_lines = _run_create_venv(tmp_path, fs_type="ext2/ext3")

    assert result.returncode == 0, (
        f"create_venv_at_path must succeed on a normal fs.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert log_lines, "uv must have been invoked at least once"
    assert "link_mode=UNSET" in log_lines[0], (
        "F3: on a normal filesystem the first sync must stay hardlink-first "
        f"(UV_LINK_MODE unset), not be forced to copy.\nuv log: {log_lines}"
    )


def test_explicit_link_mode_copy_is_respected(tmp_path: Path) -> None:
    """An explicit UV_LINK_MODE=copy from the env must be honoured (no unset)."""
    result, log_lines = _run_create_venv(
        tmp_path,
        fs_type="ext2/ext3",
        extra_env={"UV_LINK_MODE": "copy"},
    )

    assert result.returncode == 0, (
        f"create_venv_at_path must succeed.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert log_lines, "uv must have been invoked at least once"
    assert "link_mode=copy" in log_lines[0], (
        "F3: an explicit UV_LINK_MODE=copy in the environment must be respected "
        "— the blanket `unset UV_LINK_MODE` must be removed.\n"
        f"uv log: {log_lines}"
    )
