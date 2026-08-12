r"""Plan 00114 Phase 5 Task 5.1 — old-shim → new Layer 1 artifact end-to-end.

The field report (``untracked/hooks-daemon-upgrade-broken.md``, 2026-05-29)
showed a pre-v3.15 ``upgrade.sh`` skill shim self-bootstrapping by re-exec'ing
the release artifact (Layer 1 ``scripts/upgrade.sh``) with a trailing
``--already-bootstrapped`` flag. Layer 1 rejected the flag — a bootstrap
deadlock. Phase 1 (F1) made Layer 1 accept-and-ignore the flag.

This acceptance test closes the integration gap end-to-end: it installs a real
daemon into a fixture project, then invokes the REAL Layer 1
``scripts/upgrade.sh`` with the exact argument shape an old shim produces
(``--project-root <root> --already-bootstrapped <tag>``) and asserts the full
upgrade runs to completion AND emits the ``<<<UPGRADE_METADATA`` block — i.e.
the legacy flag no longer aborts a real upgrade.

Modelled on ``test_skill_upgrade_end_to_end.py``. Wired into the RELEASING.md
Step 12.0 H-1 acceptance gate (Plan 00114 Task 5.2).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from tests.acceptance.conftest import assert_clone_is_pinned, create_daemon_clone

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_VERSION_SH = REPO_ROOT / "scripts" / "install_version.sh"
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
BASH = shutil.which("bash") or "/bin/bash"

_TEST_HOSTNAME_PREFIX = "hooks-daemon-test-legacy-shim-"
_INSTALL_TIMEOUT_SECONDS = 180
_UPGRADE_TIMEOUT_SECONDS = 180
_OPEN_SENTINEL = "<<<UPGRADE_METADATA"
_CLOSE_SENTINEL = "UPGRADE_METADATA>>>"
_UNKNOWN_OPTION_MARKER = "Unknown option"
_LEGACY_FLAG = "--already-bootstrapped"


def _make_test_hostname() -> str:
    return f"{_TEST_HOSTNAME_PREFIX}{os.getpid()}"


def _stop_test_daemon(venv_python: Path, project_root: Path, env: dict[str, str]) -> None:
    if not venv_python.is_file():
        return
    subprocess.run(
        [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli", "stop"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=Timeout.DAEMON_SHUTDOWN,
        env=env,
    )


@pytest.mark.slow
def test_legacy_already_bootstrapped_flag_upgrade_succeeds(tmp_path: Path) -> None:
    """Layer 1 with the old shim's --already-bootstrapped flag must upgrade cleanly."""
    if not INSTALL_VERSION_SH.is_file():
        pytest.skip(f"install_version.sh missing at {INSTALL_VERSION_SH}")
    if not LAYER1_UPGRADE_SH.is_file():
        pytest.skip(f"Layer 1 upgrade.sh missing at {LAYER1_UPGRADE_SH}")
    if shutil.which("uv") is None:
        pytest.skip("uv not installed in this environment")

    project_root = tmp_path / "fresh-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/fake.git"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )

    daemon_dir = project_root / ".claude" / "hooks-daemon"
    # Pinned to its newest tag BEFORE installing, so the baseline is stamped
    # with the version this test then upgrades to. See conftest's docstring.
    target_tag = create_daemon_clone(daemon_dir)

    venv_python: Path | None = None
    env = os.environ.copy()

    try:
        env["HOSTNAME"] = _make_test_hostname()
        env.pop("CI", None)
        env.pop("HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP", None)
        env["NO_COLOR"] = "1"

        install_result = subprocess.run(
            [BASH, str(INSTALL_VERSION_SH), str(project_root), str(daemon_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_INSTALL_TIMEOUT_SECONDS,
            cwd=project_root,
        )
        if install_result.returncode != 0:
            pytest.fail(
                "Pre-upgrade install must exit 0.\n"
                f"returncode={install_result.returncode}\n"
                f"stdout:\n{install_result.stdout}\n"
                f"stderr:\n{install_result.stderr}"
            )

        venv_candidates = sorted((daemon_dir / "untracked").glob("venv-*py3*"))
        assert venv_candidates, f"Install must produce venv under {daemon_dir}/untracked/"
        venv_python = venv_candidates[0] / "bin" / "python"
        assert venv_python.is_file(), f"venv Python must exist: {venv_python}"

        env["HOOKS_DAEMON_PYTHON"] = str(venv_python)

        # The upgrade below must be IDEMPOTENT — that is the premise the
        # metadata assertion rests on. Re-check it now, so a drift fails here
        # by name rather than as an opaque uv error inside a subprocess.
        assert_clone_is_pinned(daemon_dir, target_tag)

        # Invoke the INSTALLED Layer 1 directly with the EXACT shape an old
        # pre-v3.15 shim produces: --project-root <root> --already-bootstrapped
        # <tag>. This is the F1 deadlock scenario, end-to-end against a real
        # install.
        installed_layer1 = daemon_dir / "scripts" / "upgrade.sh"
        result = subprocess.run(
            [
                BASH,
                str(installed_layer1),
                "--project-root",
                str(project_root),
                _LEGACY_FLAG,
                target_tag,
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_UPGRADE_TIMEOUT_SECONDS,
            cwd=project_root,
        )

        combined = result.stdout + result.stderr
        assert _UNKNOWN_OPTION_MARKER not in combined, (
            "Layer 1 must NOT reject the legacy --already-bootstrapped flag "
            "(F1 bootstrap deadlock).\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        if result.returncode != 0:
            pytest.fail(
                "Legacy-flag upgrade must exit 0 against an idempotent target tag.\n"
                f"returncode={result.returncode}\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )
        assert _OPEN_SENTINEL in result.stdout and _CLOSE_SENTINEL in result.stdout, (
            "Legacy-flag upgrade must reach Layer 2 and emit metadata.\n"
            f"--- stdout (last 2000) ---\n{result.stdout[-2000:]}"
        )

    finally:
        if venv_python is not None:
            _stop_test_daemon(venv_python, project_root, env)
        if daemon_dir.exists():
            shutil.rmtree(daemon_dir, ignore_errors=True)
