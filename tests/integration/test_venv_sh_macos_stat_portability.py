"""Plan 00122 BUG 2 — venv.sh filesystem probe is portable on BSD/macOS.

``scripts/install/venv.sh`` proactively detects hardlink-hostile filesystems
(overlay/NFS) before the first ``uv sync`` using ``stat -f -c %T``. That flag
combination is GNU coreutils only: on BSD/macOS ``stat`` treats ``-f`` as the
format-string flag, so the probe errors with
``stat: %T: stat: No such file or directory`` mid-install (the exact line the
downstream macOS report observed).

Fix: probe only under GNU ``stat`` (Linux). overlayfs — the main
hardlink-hostile case — is Linux-only, so on other platforms we leave the
detection inconclusive and fall back to hardlink-first (the existing
warn-then-retry path still catches genuine hardlink failures). These tests
stub ``uname``/``stat``/``uv`` on PATH to assert:

  * on Darwin the GNU ``stat`` probe is NOT invoked (no stray error), and
    venv creation still succeeds hardlink-first; and
  * on Linux the probe still runs (overlay detection unchanged).
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

_BSD_STAT_ERROR_FRAGMENT = "stat: %T"
_DETECTED_COPY_FRAGMENT = "Detected hardlink-hostile filesystem"
_TIMEOUT_SECONDS = 30


def _write_stubs(tmp_path: Path, uname_value: str, stat_marker: Path) -> Path:
    """PATH dir with stub ``uname``, ``stat`` (BSD-failing), and ``uv``.

    - ``uname`` echoes ``uname_value`` (so ``uname -s`` is controllable).
    - ``stat`` mimics BSD stat under GNU flags: writes a marker file (proof it
      was invoked), prints the BSD error to stderr, and exits non-zero.
    - ``uv`` fabricates the venv and exits 0.
    """
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()

    uname_stub = stub_dir / "uname"
    uname_stub.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            printf '%s\\n' "{uname_value}"
            exit 0
            """
        )
    )
    uname_stub.chmod(0o755)

    stat_stub = stub_dir / "stat"
    stat_stub.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            # Mimic BSD/macOS stat called with GNU flags: record invocation,
            # emit the BSD error, fail.
            : > "{stat_marker}"
            echo "stat: %T: stat: No such file or directory" >&2
            exit 1
            """
        )
    )
    stat_stub.chmod(0o755)

    uv_stub = stub_dir / "uv"
    uv_stub.write_text(
        textwrap.dedent(
            """\
            #!/bin/bash
            if [ -n "${UV_PROJECT_ENVIRONMENT:-}" ]; then
                mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
                : > "$UV_PROJECT_ENVIRONMENT/bin/python"
                chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
            fi
            exit 0
            """
        )
    )
    uv_stub.chmod(0o755)

    return stub_dir


def _run_create_venv(
    tmp_path: Path, uname_value: str
) -> tuple[subprocess.CompletedProcess[str], bool]:
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    (daemon_dir / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n')
    venv_path = daemon_dir / "untracked" / "venv-test"

    stat_marker = tmp_path / "stat_was_called"
    stub_dir = _write_stubs(tmp_path, uname_value, stat_marker)

    harness = textwrap.dedent(
        f"""\
        set -euo pipefail
        export PATH="{stub_dir}:$PATH"
        . "{VENV_SH}"
        create_venv_at_path "{daemon_dir}" "{venv_path}"
        """
    )

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env.pop("UV_LINK_MODE", None)

    result = subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    return result, stat_marker.exists()


def test_darwin_skips_gnu_stat_probe_no_error(tmp_path: Path) -> None:
    """On Darwin the GNU stat probe must be skipped — no invocation, no error."""
    result, stat_called = _run_create_venv(tmp_path, uname_value="Darwin")

    assert result.returncode == 0, (
        f"create_venv_at_path must succeed on Darwin.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert _BSD_STAT_ERROR_FRAGMENT not in combined, (
        "BUG 2: the GNU `stat -f -c %T` probe must not run on Darwin — the "
        "BSD stat error leaked into output.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert not stat_called, (
        "BUG 2: `stat` was invoked on Darwin; the probe must be Linux-gated."
    )
    assert _DETECTED_COPY_FRAGMENT not in combined, (
        "On Darwin detection is inconclusive; the run stays hardlink-first."
    )


def test_linux_still_runs_stat_probe(tmp_path: Path) -> None:
    """On Linux the probe still runs (overlay/NFS detection preserved)."""
    _result, stat_called = _run_create_venv(tmp_path, uname_value="Linux")
    assert stat_called, (
        "BUG 2 regression: on Linux the GNU stat probe must still be invoked "
        "so overlay/NFS hardlink-hostile detection keeps working."
    )
