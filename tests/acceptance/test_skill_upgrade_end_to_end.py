r"""Plan 00109 Phase 4 Task 4.3 — skill upgrade.sh shim full end-to-end gate.

The Phase 2 shim test (``test_skill_upgrade_shim.py``) proves the shim
correctly fetches and exec's a *stand-in* upgrade script. The Phase 1
metadata test (``test_upgrade_metadata_emission.py``) proves the *real*
Layer 1 ``scripts/upgrade.sh`` emits metadata when invoked directly.

This test closes the integration gap: it serves the REAL Layer 1 script
from a file:// fixture tree, runs the thin shim against an installed
daemon, and asserts the full pipeline produces both a running daemon
AND the ``<<<UPGRADE_METADATA`` block on stdout.

The combination matters because a regression in the shim's ``--project-root``
forwarding, base-URL handling, or exec arguments would not show up in
either of the existing tests:

  - Phase 1 test bypasses the shim entirely.
  - Phase 2 test uses a stand-in script that swallows whatever args
    the shim hands it without enforcing Layer 1's contract.

This test is the only gate that exercises shim → real Layer 1 → metadata
end-to-end with an actual installed daemon as the target.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_VERSION_SH = REPO_ROOT / "scripts" / "install_version.sh"
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
SKILL_UPGRADE_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "upgrade.sh"
)
BASH = shutil.which("bash") or "/bin/bash"

_TEST_HOSTNAME_PREFIX = "hooks-daemon-test-shim-e2e-"
_INSTALL_TIMEOUT_SECONDS = 180
_UPGRADE_TIMEOUT_SECONDS = 180
_OPEN_SENTINEL = "<<<UPGRADE_METADATA"
_CLOSE_SENTINEL = "UPGRADE_METADATA>>>"

_REQUIRED_METADATA_FIELDS = (
    "from_version",
    "to_version",
    "python_version",
    "python_path",
    "venv_path",
    "host",
    "daemon_dir",
    "project_root",
    "modified_files",
    "config_diff_summary",
)


def _make_test_hostname() -> str:
    return f"{_TEST_HOSTNAME_PREFIX}{os.getpid()}"


def _create_daemon_clone(daemon_dir: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "clone",
            "--no-hardlinks",
            "--local",
            "--quiet",
            str(REPO_ROOT),
            str(daemon_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(daemon_dir), "config", "protocol.file.allow", "always"],
        check=True,
        capture_output=True,
        text=True,
    )


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


def _extract_metadata_block(stdout: str) -> dict[str, str]:
    pattern = re.compile(
        re.escape(_OPEN_SENTINEL) + r"\n(.*?)\n" + re.escape(_CLOSE_SENTINEL),
        re.DOTALL,
    )
    match = pattern.search(stdout)
    if not match:
        return {}
    parsed: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


@pytest.mark.slow
def test_skill_upgrade_shim_end_to_end_emits_metadata(tmp_path: Path) -> None:
    """Skill shim + real Layer 1 must produce metadata on a real install.

    Sets up a fixture project with the daemon installed, then runs the
    thin skill shim with ``HOOKS_DAEMON_UPGRADE_BASE_URL`` pointed at a
    local file:// tree serving the REAL Layer 1 ``scripts/upgrade.sh``
    (copied from the cloned daemon dir). The shim must fetch the real
    script, exec it with ``--project-root``, and the real script must
    in turn run against the installed daemon and emit the metadata
    block on stdout.

    Skip conditions mirror the H-1 install gate: missing install script,
    missing Layer 1, or no ``uv`` interpreter.
    """
    if not INSTALL_VERSION_SH.is_file():
        pytest.skip(f"install_version.sh missing at {INSTALL_VERSION_SH}")
    if not LAYER1_UPGRADE_SH.is_file():
        pytest.skip(f"Layer 1 upgrade.sh missing at {LAYER1_UPGRADE_SH}")
    if not SKILL_UPGRADE_SH.is_file():
        pytest.skip(f"Skill shim missing at {SKILL_UPGRADE_SH}")
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
    _create_daemon_clone(daemon_dir)

    venv_python: Path | None = None
    env = os.environ.copy()

    try:
        env["HOSTNAME"] = _make_test_hostname()
        env.pop("CI", None)
        env.pop("HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP", None)
        env["NO_COLOR"] = "1"

        # Install baseline.
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

        # Serve the REAL Layer 1 script from a file:// fixture tree that
        # mirrors GitHub's raw-content layout: <base>/<ref>/scripts/upgrade.sh.
        # We copy the script from the cloned daemon dir (NOT the test-host
        # repo root) so the fixture is hermetic.
        fixture_base = tmp_path / "fixture-base"
        fixture_scripts = fixture_base / "main" / "scripts"
        fixture_scripts.mkdir(parents=True)
        real_layer1_in_clone = daemon_dir / "scripts" / "upgrade.sh"
        assert (
            real_layer1_in_clone.is_file()
        ), f"Cloned daemon dir must contain Layer 1 upgrade.sh at {real_layer1_in_clone}"
        shim_target = fixture_scripts / "upgrade.sh"
        shutil.copy2(real_layer1_in_clone, shim_target)
        shim_target.chmod(shim_target.stat().st_mode | 0o755)

        # The shim must fetch the script via curl. Set the base-URL override
        # so the curl call resolves to our file:// fixture instead of GitHub.
        env["HOOKS_DAEMON_UPGRADE_BASE_URL"] = f"file://{fixture_base}"
        env["HOOKS_DAEMON_UPGRADE_REF"] = "main"
        env["HOOKS_DAEMON_PYTHON"] = str(venv_python)

        # Resolve target tag from the clone — Layer 1 will checkout it
        # idempotently (already on it after install).
        tag_proc = subprocess.run(
            ["git", "-C", str(daemon_dir), "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            check=True,
        )
        target_tag = tag_proc.stdout.strip()
        assert target_tag, f"Could not resolve a tag in {daemon_dir}"

        # Invoke the SHIM (not Layer 1 directly). The shim should:
        #   1. Detect PROJECT_ROOT by walking up for .claude/hooks-daemon.yaml.
        #   2. curl fixture_base/main/scripts/upgrade.sh -> /tmp/upgrade.sh.
        #   3. exec bash /tmp/upgrade.sh --project-root <root> <target_tag>.
        # The exec'd real Layer 1 then emits the metadata block.
        result = subprocess.run(
            [BASH, str(SKILL_UPGRADE_SH), target_tag],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_UPGRADE_TIMEOUT_SECONDS,
            cwd=project_root,
        )

        if result.returncode != 0:
            pytest.fail(
                "Skill shim + real Layer 1 must exit 0 against an idempotent "
                "target tag.\n"
                f"returncode={result.returncode}\n"
                f"--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}"
            )

        assert _OPEN_SENTINEL in result.stdout, (
            f"Shim end-to-end must produce metadata block on stdout. "
            f"Sentinel '{_OPEN_SENTINEL}' missing — proves shim never "
            f"reached real Layer 1 (or Layer 1 silently dropped emission).\n"
            f"--- stdout (last 2000) ---\n{result.stdout[-2000:]}"
        )
        assert _CLOSE_SENTINEL in result.stdout, (
            f"Closing sentinel '{_CLOSE_SENTINEL}' missing from stdout.\n"
            f"--- stdout (last 2000) ---\n{result.stdout[-2000:]}"
        )

        metadata = _extract_metadata_block(result.stdout)
        missing = [f for f in _REQUIRED_METADATA_FIELDS if f not in metadata]
        assert not missing, (
            f"Metadata block missing required fields: {missing}.\n"
            f"Parsed: {metadata}\n"
            f"--- stdout (last 2000) ---\n{result.stdout[-2000:]}"
        )

        # project_root in metadata must match the fixture path — proves
        # the shim's PROJECT_ROOT detection forwarded correctly to Layer 1.
        assert metadata["project_root"] == str(project_root), (
            f"Metadata project_root must match the shim's detected root.\n"
            f"expected={project_root!r}\n"
            f"got={metadata['project_root']!r}"
        )

        # python_path must NOT be /usr/bin — same v3.9.x field-bug guard
        # as the Phase 1 metadata test.
        assert (
            "/usr/bin/" not in metadata["python_path"]
        ), f"python_path must never be /usr/bin/.\ngot={metadata['python_path']!r}"

    finally:
        if venv_python is not None:
            _stop_test_daemon(venv_python, project_root, env)
        if daemon_dir.exists():
            shutil.rmtree(daemon_dir, ignore_errors=True)
