r"""Plan 00125 — proactive copy mode in containers, no hardlink warning.

`create_venv_at_path` (scripts/install/venv.sh) already picks copy mode up front
on hardlink-hostile *filesystems* (overlay/NFS) by probing the target fs type.
But in a typical container the project + its `untracked/` dir are bind-mounted
from the host, so the venv target sits on the host fs (ext4/xfs/btrfs) while
uv's cache lives on the container's overlay fs. The two are cross-device, so
`uv` hardlink fails even though the target fs type is NOT overlay/nfs — the
type probe misses it and the warn-then-retry fallback fires on every container
upgrade (the noise the user reported).

Fix: detect the container environment and choose UV_LINK_MODE=copy up front,
the same way the overlay/nfs branch does — one clean sync, no failed attempt,
no warning.

Container detection signals (see `_uv_in_container` in venv.sh): the `container`
env var (Podman/systemd set `container=podman`), Podman's /run/.containerenv,
Docker's /.dockerenv. The marker paths are overridable via
HOOKS_DAEMON_CONTAINERENV_PATH / HOOKS_DAEMON_DOCKERENV_PATH so the NEGATIVE
case can be exercised from inside a real container (this very test runner has
/run/.containerenv).

Stubs `uv` and `stat` on PATH for determinism (same approach as
test_venv_sh_overlay_fs_proactive_copy.py). The `uv` stub never emits
"Failed to hardlink", proving the proactive path took a single clean sync.
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
# Production-truth signal of the proactive container copy-mode branch.
_DETECTED_CONTAINER_FRAGMENT = "Detected container environment"
# The overlay/nfs branch's signal — must NOT be what fires in these tests
# (we use a normal target fs to isolate the container signal).
_DETECTED_FS_FRAGMENT = "Detected hardlink-hostile filesystem"
_TIMEOUT_SECONDS = 30


def _write_stub_dir(tmp_path: Path, fs_type: str, uv_log: Path) -> Path:
    """PATH dir with stub `uv` and `stat` (mirrors the overlay-fs test)."""
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()

    uv_stub = stub_dir / "uv"
    uv_stub.write_text(textwrap.dedent(f"""\
        #!/bin/bash
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


def _no_container_env(tmp_path: Path) -> dict[str, str]:
    """Env that neutralises ALL container signals, even inside a real container.

    Unsets the `container` env var and points the marker-file overrides at
    paths that do not exist — so the test runner's own /run/.containerenv does
    not leak a false positive.
    """
    return {
        "container": "",
        "HOOKS_DAEMON_CONTAINERENV_PATH": str(tmp_path / "no-containerenv"),
        "HOOKS_DAEMON_DOCKERENV_PATH": str(tmp_path / "no-dockerenv"),
    }


def test_container_uses_copy_mode_up_front_no_warning(tmp_path: Path) -> None:
    """In a container (container=podman) on a normal target fs, the first and
    only sync uses copy mode — no 'uv hardlink failed' warning."""
    result, _log = _run_create_venv(
        tmp_path,
        fs_type="ext2/ext3",
        extra_env={"container": "podman"},
    )

    assert result.returncode == 0, (
        f"create_venv_at_path must succeed in a container.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert _HARDLINK_WARNING_FRAGMENT not in combined, (
        "Container install must NOT emit the 'uv hardlink failed' warning — "
        "copy mode should be chosen proactively before the first sync.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert _DETECTED_CONTAINER_FRAGMENT in combined, (
        "A container environment must trigger the proactive container copy-mode "
        f"detection ({_DETECTED_CONTAINER_FRAGMENT!r}).\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_containerenv_marker_file_triggers_copy(tmp_path: Path) -> None:
    """Docker-style detection: no `container` env var, but a marker file exists."""
    marker = tmp_path / "containerenv"
    marker.write_text("")
    result, _log = _run_create_venv(
        tmp_path,
        fs_type="ext2/ext3",
        extra_env={
            "container": "",
            "HOOKS_DAEMON_CONTAINERENV_PATH": str(marker),
            "HOOKS_DAEMON_DOCKERENV_PATH": str(tmp_path / "absent"),
        },
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert _HARDLINK_WARNING_FRAGMENT not in combined, combined
    assert _DETECTED_CONTAINER_FRAGMENT in combined, (
        "A present /run/.containerenv-style marker must trigger container "
        f"copy-mode detection.\n--- stderr ---\n{result.stderr}"
    )


def test_non_container_normal_fs_uses_hardlink_first(tmp_path: Path) -> None:
    """With every container signal neutralised and a normal fs, NEITHER the
    container nor the overlay/nfs copy-mode detection fires — hardlink-first."""
    result, _log = _run_create_venv(
        tmp_path,
        fs_type="ext2/ext3",
        extra_env=_no_container_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert _DETECTED_CONTAINER_FRAGMENT not in combined, (
        "Outside a container the container copy-mode detection must NOT fire.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert _DETECTED_FS_FRAGMENT not in combined, (
        "On a normal fs the overlay/nfs detection must NOT fire either.\n"
        f"--- stderr ---\n{result.stderr}"
    )


def test_explicit_link_mode_respected_in_container(tmp_path: Path) -> None:
    """An explicit UV_LINK_MODE wins even in a container — auto-detection skipped."""
    result, _log = _run_create_venv(
        tmp_path,
        fs_type="ext2/ext3",
        extra_env={"container": "podman", "UV_LINK_MODE": "hardlink"},
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert _DETECTED_CONTAINER_FRAGMENT not in combined, (
        "With an explicit UV_LINK_MODE the container detection must be skipped "
        "(operator value used verbatim).\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
