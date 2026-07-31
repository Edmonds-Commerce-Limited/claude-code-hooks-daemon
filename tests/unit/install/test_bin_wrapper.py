"""Tests for deploying the ``hooks-daemon`` bin wrapper (Plan 00192 Phase 2).

The wrapper is daemon-owned tooling: it is overwritten on every install and
upgrade (like ``mkplan.bash`` and the skill scripts) so a stale copy can never
outlive a fix. It must land executable, because a non-executable wrapper
reproduces the very "command not found" confusion Plan 00192 exists to remove.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from claude_code_hooks_daemon.install import bin_wrapper


class TestWrapperTemplate:
    """The bundled template must exist and be a real daemon-CLI wrapper."""

    def test_template_path_exists(self) -> None:
        assert bin_wrapper.wrapper_template_path().is_file()

    def test_template_execs_the_daemon_cli(self) -> None:
        body = bin_wrapper.wrapper_template_path().read_text(encoding="utf-8")
        assert "claude_code_hooks_daemon.daemon.cli" in body

    def test_template_does_not_depend_on_an_unset_shell_variable(self) -> None:
        """Regression guard: the wrapper must not reintroduce ``$PYTHON``-style
        reliance on a variable the caller is assumed to have exported."""
        body = bin_wrapper.wrapper_template_path().read_text(encoding="utf-8")
        assert 'exec "$PYTHON" -m' in body, "wrapper must set PYTHON itself before exec"
        assert "resolve_venv_python" in body, "wrapper must resolve the venv itself"

    def test_template_performs_no_network_access(self) -> None:
        """Hot-path commands must not depend on a release-manifest download."""
        body = bin_wrapper.wrapper_template_path().read_text(encoding="utf-8")
        assert "curl" not in body
        assert "bootstrap-checksums" not in body


class TestDeployBinWrapper:
    """Deployment is idempotent, overwriting, and always executable."""

    def test_creates_bin_dir_and_wrapper(self, tmp_path: Path) -> None:
        target = bin_wrapper.deploy_bin_wrapper(tmp_path)
        assert target == tmp_path / "bin" / "hooks-daemon"
        assert target.is_file()

    def test_wrapper_is_executable(self, tmp_path: Path) -> None:
        target = bin_wrapper.deploy_bin_wrapper(tmp_path)
        mode = target.stat().st_mode
        assert mode & stat.S_IXUSR
        assert mode & stat.S_IXGRP
        assert mode & stat.S_IXOTH

    def test_wrapper_is_not_world_writable(self, tmp_path: Path) -> None:
        """Least privilege — deployed tooling must never be world-writable."""
        target = bin_wrapper.deploy_bin_wrapper(tmp_path)
        assert not target.stat().st_mode & stat.S_IWOTH

    def test_content_matches_the_bundled_template(self, tmp_path: Path) -> None:
        target = bin_wrapper.deploy_bin_wrapper(tmp_path)
        expected = bin_wrapper.wrapper_template_path().read_text(encoding="utf-8")
        assert target.read_text(encoding="utf-8") == expected

    def test_overwrites_a_stale_wrapper(self, tmp_path: Path) -> None:
        """Daemon-owned: an upgrade must replace an outdated copy."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        stale = bin_dir / "hooks-daemon"
        stale.write_text("#!/bin/bash\necho stale\n", encoding="utf-8")

        target = bin_wrapper.deploy_bin_wrapper(tmp_path)

        assert "echo stale" not in target.read_text(encoding="utf-8")

    def test_restores_the_execute_bit_on_a_stale_non_executable_copy(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        stale = bin_dir / "hooks-daemon"
        stale.write_text("#!/bin/bash\n", encoding="utf-8")
        stale.chmod(0o644)

        target = bin_wrapper.deploy_bin_wrapper(tmp_path)

        assert os.access(target, os.X_OK)

    def test_is_idempotent(self, tmp_path: Path) -> None:
        first = bin_wrapper.deploy_bin_wrapper(tmp_path)
        first_content = first.read_text(encoding="utf-8")
        second = bin_wrapper.deploy_bin_wrapper(tmp_path)
        assert second == first
        assert second.read_text(encoding="utf-8") == first_content


class TestSelfInstallCopyDoesNotDrift:
    """This repo runs in self-install mode, so its own bin/hooks-daemon is a
    DEPLOYED artifact. A hand-edited copy that drifts from the bundled template
    would make the dogfood environment disagree with every client — the exact
    class of mode-specific divergence Plan 00192 exists to close."""

    def test_repo_wrapper_matches_the_bundled_template(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        deployed = repo_root / "bin" / "hooks-daemon"
        if not deployed.is_file():
            # Not yet deployed in this checkout — deployment is the installer's
            # job, so absence is not a failure.
            return
        template_body = bin_wrapper.wrapper_template_path().read_text(encoding="utf-8")
        assert deployed.read_text(encoding="utf-8") == template_body, (
            "bin/hooks-daemon has drifted from install/templates/hooks-daemon. "
            "Edit the TEMPLATE and redeploy; never hand-edit the deployed copy."
        )

    def test_repo_wrapper_is_executable_when_present(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        deployed = repo_root / "bin" / "hooks-daemon"
        if not deployed.is_file():
            return
        assert os.access(deployed, os.X_OK)
