"""Plan 00477 - install and upgrade record the expected version and deploy provision.sh.

The full install and upgrade are slow acceptance tests; this pins the two
seams they reach through, by sourcing the real libraries.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_LIB = REPO_ROOT / "scripts" / "install"
BASH = shutil.which("bash") or "/bin/bash"


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - fixed argv, no shell
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.REQUEST_LONG,
        env={**os.environ, "NO_COLOR": "1"},
    )


class TestRecordExpectedVersionLibrary:
    def test_writes_the_running_daemon_version_through_the_venv_python(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / ".claude" / "hooks-daemon.yaml"
        config.parent.mkdir()
        config.write_text("daemon:\n  log_level: INFO\n")

        result = _run(
            f'source "{INSTALL_LIB}/output.sh"\n'
            f'source "{INSTALL_LIB}/expected_version.sh"\n'
            f'record_expected_version "{sys.executable}" "{tmp_path}"\n'
        )

        assert result.returncode == 0, result.stdout + result.stderr
        from claude_code_hooks_daemon.version import __version__

        assert yaml.safe_load(config.read_text())["daemon"]["expected_version"] == __version__

    def test_requires_both_arguments(self) -> None:
        result = _run(
            f'source "{INSTALL_LIB}/output.sh"\n'
            f'source "{INSTALL_LIB}/expected_version.sh"\n'
            'record_expected_version "" ""\n'
        )

        assert result.returncode != 0

    def test_both_the_install_and_the_upgrade_script_call_it(self) -> None:
        for name in ("install_version.sh", "upgrade_version.sh"):
            text = (REPO_ROOT / "scripts" / name).read_text()
            assert 'source "$INSTALL_LIB_DIR/expected_version.sh"' in text, name
            assert 'record_expected_version "$VENV_PYTHON" "$PROJECT_ROOT"' in text, name


class TestDeployProvisionScript:
    def _deploy(self, project: Path, mode: str) -> subprocess.CompletedProcess[str]:
        return _run(
            f'source "{INSTALL_LIB}/output.sh"\n'
            f'source "{INSTALL_LIB}/hooks_deploy.sh"\n'
            f'deploy_provision_script "{project}" "{REPO_ROOT}" "{mode}"\n'
        )

    def test_copies_an_executable_file_beside_init_sh(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()

        result = self._deploy(tmp_path, "normal")

        target = tmp_path / ".claude" / "provision.sh"
        assert result.returncode == 0, result.stdout + result.stderr
        assert target.read_bytes() == (REPO_ROOT / "provision.sh").read_bytes()
        assert not target.is_symlink()
        assert os.access(target, os.X_OK)

    def test_refreshes_a_stale_copy(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "provision.sh").write_text("# old\n")

        assert self._deploy(tmp_path, "normal").returncode == 0

        assert (tmp_path / ".claude" / "provision.sh").read_bytes() == (
            REPO_ROOT / "provision.sh"
        ).read_bytes()

    def test_self_install_leaves_the_repositorys_own_link_alone(self) -> None:
        link = REPO_ROOT / ".claude" / "provision.sh"
        assert link.is_symlink(), "the daemon repository links .claude/provision.sh to its own"

        result = self._deploy(REPO_ROOT, "self-install")

        assert result.returncode == 0, result.stdout + result.stderr
        assert link.is_symlink()

    def test_deploy_all_hooks_deploys_it(self) -> None:
        text = (INSTALL_LIB / "hooks_deploy.sh").read_text()

        assert 'deploy_provision_script "$project_root" "$daemon_dir" "$install_mode"' in text
