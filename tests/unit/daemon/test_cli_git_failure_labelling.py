"""A git failure at daemon start is reported as a git failure, not a config error (N446)."""

import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.support.git_fixtures import git_setup_timeout, run_git

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import _validate_installation

GIT_STDERR = "fatal: unknown repository extension found: relativeworktrees"


@pytest.fixture(autouse=True)
def reset_project_context() -> Iterator[None]:
    """Reset ProjectContext singleton around each test."""
    ProjectContext.reset()
    yield
    ProjectContext.reset()


def _write_config(project_root: Path, text: str) -> None:
    claude_dir = project_root / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text(text)


class TestValidateInstallationGitFailure:
    """_validate_installation names git, not the configuration, when git fails."""

    def test_git_failure_is_not_labelled_invalid_configuration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_config(tmp_path, "version: '1.0'\n")
        failed = subprocess.CompletedProcess(["git"], 128, "", GIT_STDERR + "\n")

        with patch("claude_code_hooks_daemon.utils.git_repo.subprocess.run", return_value=failed):
            with pytest.raises(SystemExit) as excinfo:
                _validate_installation(tmp_path)

        err = capsys.readouterr().err
        assert excinfo.value.code == 1
        assert "Invalid configuration" not in err
        assert "Fix the configuration file" not in err
        assert GIT_STDERR in err
        assert "128" in err
        assert str(tmp_path) in err
        assert "git" in err.lower()

    def test_real_config_error_is_still_invalid_configuration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_config(tmp_path, "version: '1.0'\ndaemon:\n  log_level: [unterminated\n")

        with patch.object(ProjectContext, "initialize"):
            with pytest.raises(SystemExit) as excinfo:
                _validate_installation(tmp_path)

        err = capsys.readouterr().err
        assert excinfo.value.code == 1
        assert "Invalid configuration" in err
        assert "Fix the configuration file" in err

    def test_pydantic_error_is_still_invalid_configuration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_config(tmp_path, "version: '1.0'\ndaemon:\n  log_level: NOT_A_LEVEL\n")

        with patch.object(ProjectContext, "initialize"):
            with pytest.raises(SystemExit) as excinfo:
                _validate_installation(tmp_path)

        err = capsys.readouterr().err
        assert excinfo.value.code == 1
        assert "Invalid configuration" in err


class TestRealRepositoryWithUnknownExtension:
    """A real repository git cannot read reproduces the field report on any git version."""

    def test_unknown_extension_surfaces_git_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run_git(tmp_path, "init", "-q")
        run_git(tmp_path, "config", "core.repositoryformatversion", "1")
        run_git(tmp_path, "config", "extensions.zzzunknownext", "true")
        _write_config(tmp_path, "version: '1.0'\n")
        assert git_setup_timeout() > 0

        with pytest.raises(SystemExit) as excinfo:
            _validate_installation(tmp_path)

        err = capsys.readouterr().err
        assert excinfo.value.code == 1
        assert "Invalid configuration" not in err
        assert "zzzunknownext" in err
