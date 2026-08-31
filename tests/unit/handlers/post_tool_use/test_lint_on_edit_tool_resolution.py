"""Guard: lint tools installed in the project venv must actually be found.

DOGFOODING BUG. ``lint_on_edit`` builds its extended Python command as the bare
string ``ruff check {file}`` and hands it to ``subprocess.run`` without a shell,
so the executable is resolved against ``PATH`` only. In this repository — and in
any Python project that keeps its tooling in a virtualenv, which is the normal
case — ``ruff`` is installed in the venv's ``bin/`` and is NOT on ``PATH``. The
handler therefore raised ``FileNotFoundError`` on every single ``.py`` edit and
degraded to an advisory reading:

    ⚠️ Python lint tool not found (ruff) - install to enable lint checking

Two failures in one:

1. The lint-on-edit guard was silently inert in the daemon's own repo, and in
   every client repo with a venv. A guard that reports "not available" instead
   of running is indistinguishable from a guard that passed.
2. The advice was wrong. It told the user to install software that was already
   installed, so following it could not fix anything.

The strategy module already had the answer in the line above: the DEFAULT Python
command is built as ``f"{sys.executable} -m py_compile ..."``, deliberately
using the running interpreter "works in any environment". Only the extended
command was left resolving against PATH.

WHY RESOLUTION, NOT ``python -m ruff``: rewriting the command to
``{sys.executable} -m ruff check`` would find ruff here but would be actively
harmful in a client whose daemon venv lacks it — ``python -m ruff`` exits
NON-ZERO ("No module named ruff") rather than raising ``FileNotFoundError``, and
a non-zero extended lint result is a DENY. That converts "tool absent" from a
harmless advisory into a hard block on the user's file edit, with a baffling
reason. Resolving the executable to an absolute path keeps the two cases
distinct: found -> run it; genuinely absent -> advise, never block.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.workspace import ProjectRegistry
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import (
    LintOnEditHandler,
)
from claude_code_hooks_daemon.strategies.lint.python_strategy import PythonLintStrategy

_MODULE = "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit"

# The interpreter running the daemon lives in the project venv's bin/ directory,
# which is where that venv's console scripts (ruff, black, mypy) also live.
_VENV_BIN: Final[Path] = Path(sys.executable).parent


class TestLintToolResolution:
    """The handler resolves a bare tool name before deciding it is missing."""

    def test_resolves_tool_installed_in_the_daemon_venv(self) -> None:
        """A tool in the venv bin/ resolves, even when absent from PATH.

        This is the exact condition that made the handler inert: ruff present in
        ``<venv>/bin/ruff``, nothing named ruff anywhere on PATH.
        """
        handler = LintOnEditHandler()

        resolved = handler._resolve_executable("ruff")

        assert resolved is not None, (
            "ruff did not resolve. It is installed in the project venv at "
            f"{_VENV_BIN / 'ruff'}; a resolver that misses it leaves the "
            f"lint-on-edit guard inert for every venv-based project."
        )
        assert Path(resolved).is_file(), f"Resolved to {resolved!r}, which is not a file."

    def test_absolute_paths_pass_through_unchanged(self) -> None:
        """An already-absolute command (e.g. sys.executable) is not rewritten."""
        handler = LintOnEditHandler()

        assert handler._resolve_executable(sys.executable) == sys.executable

    def test_genuinely_missing_tool_returns_none(self) -> None:
        """Absence is still reported as absence — NOT silently resolved.

        Control. A resolver that returned some path for every input would make
        the first test pass while breaking the graceful-degradation path, so the
        handler would try to execute nonsense instead of advising.
        """
        handler = LintOnEditHandler()

        assert handler._resolve_executable("definitely-not-a-real-linter-xyzzy") is None

    def test_python_extended_command_still_names_ruff(self) -> None:
        """The strategy keeps a bare tool name; resolution is the handler's job.

        Guards against "fixing" this by hardcoding an absolute venv path into
        the strategy constant, which would break every OTHER environment.
        """
        command = PythonLintStrategy().extended_lint_command

        assert command is not None
        assert command.startswith("ruff "), (
            f"Expected the extended command to invoke ruff by name, got {command!r}. "
            f"The strategy must stay environment-independent."
        )


class TestMissingToolIsAdvisoryNotBlocking:
    """A missing linter must never deny the user's edit."""

    def test_missing_tool_allows_and_explains(self) -> None:
        """An unresolvable tool yields ALLOW with actionable context."""
        from claude_code_hooks_daemon.core import Decision

        handler = LintOnEditHandler()

        result = handler._run_lint_command(
            {},
            "definitely-not-a-real-linter-xyzzy check {file}",
            "/tmp/example.py",
            "Python",
        )

        assert result is not None, "A missing tool must report, not pass silently."
        assert result.decision == Decision.ALLOW, (
            "A missing linter must never DENY. Blocking a user's edit because a "
            "tool is not installed is the failure mode this guard exists to "
            "prevent — see the module docstring on `python -m ruff`."
        )


def _make_executable(path: Path) -> Path:
    """Create a runnable stub at ``path`` (parents included)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class TestWorkspaceBinDirResolution:
    """A workspace's own tool binaries are searched first (Plan 00296 Task 2.2).

    ``vendor/bin`` (Composer) and ``node_modules/.bin`` (npm) are where a
    workspace actually keeps its linters. Searching only the daemon venv and
    PATH means the handler reports "install it to enable lint checking" about
    a tool that is already installed a few directories away.
    """

    def test_finds_a_linter_in_the_workspace_vendor_bin(self, tmp_path: Path) -> None:
        phpstan = _make_executable(tmp_path / "vendor" / "bin" / "phpstan")
        handler = LintOnEditHandler()

        resolved = handler._resolve_executable("phpstan", (tmp_path / "vendor" / "bin",))

        assert resolved == str(phpstan)

    def test_workspace_bin_wins_over_path(self, tmp_path: Path) -> None:
        """A workspace-pinned tool version must beat a global one."""
        local_tool = _make_executable(tmp_path / "node_modules" / ".bin" / "sh")
        handler = LintOnEditHandler()

        resolved = handler._resolve_executable("sh", (tmp_path / "node_modules" / ".bin",))

        assert resolved == str(local_tool), "the workspace copy must win over /bin/sh on PATH"

    def test_nonexistent_bin_dir_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """bin_dirs are constructed, not probed, so most will not exist."""
        handler = LintOnEditHandler()

        resolved = handler._resolve_executable("ruff", (tmp_path / "nope" / "bin",))

        assert resolved is not None, "must fall through to the daemon venv"
        assert Path(resolved).is_file()

    def test_missing_everywhere_still_returns_none(self, tmp_path: Path) -> None:
        """The return-None-rather-than-guess fallback is explicitly preserved."""
        handler = LintOnEditHandler()

        assert handler._resolve_executable("no-such-linter-xyzzy", (tmp_path,)) is None


class TestWorkingDirectoryIsTheFilesWorkspace:
    """The linter runs from the edited file's DECLARED project, not the daemon cwd."""

    @staticmethod
    def _declare(handler: LintOnEditHandler, root: Path, *roots: str) -> None:
        """Inject declared projects, as the daemon does at config load."""
        config = Config.model_validate(
            {"projects": [{"name": path, "root": path} for path in roots]}
        )
        handler._project_registry = ProjectRegistry.from_config(config, root)

    def test_runs_from_the_files_own_declared_project(self, tmp_path: Path) -> None:
        svc = tmp_path / "services" / "billing"
        svc.mkdir(parents=True)
        (svc / "pyproject.toml").write_text("[project]\nname = 'billing'\n", encoding="utf-8")
        edited = svc / "app.py"
        edited.write_text("x = 1\n", encoding="utf-8")

        handler = LintOnEditHandler()
        self._declare(handler, tmp_path, "services/billing")
        with (
            patch(f"{_MODULE}.resolve_project_root", return_value=str(tmp_path)),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            handler._run_lint_command(
                {}, f"{sys.executable} -m py_compile {{file}}", str(edited), "Python"
            )

        assert mock_run.call_args[1]["cwd"] == str(svc)

    def test_undeclared_subproject_runs_from_the_repository_root(self, tmp_path: Path) -> None:
        """Anti-inference pin: a pyproject.toml is not a declaration.

        `services/billing` has its own pyproject.toml and looks exactly like a
        project. Undeclared, the linter must still run from the repository
        root — running it from a guessed root would apply the wrong config.
        """
        svc = tmp_path / "services" / "billing"
        svc.mkdir(parents=True)
        (svc / "pyproject.toml").write_text("[project]\nname = 'billing'\n", encoding="utf-8")
        edited = svc / "app.py"
        edited.write_text("x = 1\n", encoding="utf-8")

        handler = LintOnEditHandler()
        self._declare(handler, tmp_path)
        with (
            patch(f"{_MODULE}.resolve_project_root", return_value=str(tmp_path)),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            handler._run_lint_command(
                {}, f"{sys.executable} -m py_compile {{file}}", str(edited), "Python"
            )

        assert mock_run.call_args[1]["cwd"] == str(tmp_path)

    def test_ansible_cfg_marker_still_selects_the_working_dir(self, tmp_path: Path) -> None:
        """NON-REGRESSION PIN for the resolver rollout.

        ``ansible.cfg`` is a ``_MODULE_ROOT_MARKERS`` entry but NOT a manifest
        in ``_MANIFEST_KINDS``, so the shared workspace resolver cannot find
        it. Routing this handler naively through the resolver would silently
        drop Ansible's working directory -- and per the comment on
        ``_MODULE_ROOT_MARKERS`` that makes the linter fail for the WRONG
        reason, a denial the author cannot act on.
        """
        infra = tmp_path / "infra"
        infra.mkdir(parents=True)
        (infra / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
        edited = infra / "roles" / "web" / "tasks" / "main.yml"
        edited.parent.mkdir(parents=True)
        edited.write_text("- name: noop\n", encoding="utf-8")

        handler = LintOnEditHandler()
        with (
            patch(f"{_MODULE}.resolve_project_root", return_value=str(tmp_path)),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            handler._run_lint_command(
                {}, f"{sys.executable} -m py_compile {{file}}", str(edited), "Ansible"
            )

        assert mock_run.call_args[1]["cwd"] == str(infra), (
            "Ansible lost its ansible.cfg working directory -- the marker lookup "
            "must take precedence over the manifest-only workspace resolver."
        )

    def test_go_mod_marker_is_unaffected(self, tmp_path: Path) -> None:
        """go.mod IS a manifest, so both mechanisms agree -- pinned regardless."""
        module = tmp_path / "cmd" / "server"
        module.mkdir(parents=True)
        (module / "go.mod").write_text("module example.com/server\n", encoding="utf-8")
        edited = module / "main.go"
        edited.write_text("package main\n", encoding="utf-8")

        handler = LintOnEditHandler()
        with (
            patch(f"{_MODULE}.resolve_project_root", return_value=str(tmp_path)),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            handler._run_lint_command(
                {}, f"{sys.executable} -m py_compile {{file}}", str(edited), "Go"
            )

        assert mock_run.call_args[1]["cwd"] == str(module)
