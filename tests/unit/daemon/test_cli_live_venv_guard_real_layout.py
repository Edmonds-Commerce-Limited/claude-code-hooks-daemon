"""Plan 00517 Task 3.0 (N456): the live-venv guard over a REAL venv layout.

A real venv's ``bin/python`` is a symlink to the system interpreter, so
resolving that symlink yields the interpreter's prefix (``/usr``), never the
venv directory. The guard must identify the live venv by its DIRECTORY so no
``prune-venvs`` mode can select the venv the daemon is running from, even when
its fingerprint differs from the current one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli

_CLI = "claude_code_hooks_daemon.daemon.cli"


def _make_real_layout_venv(path: Path) -> None:
    """Create a venv whose bin/python is a symlink to the real system interpreter."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    (path / ".daemon-version").write_text("v3.5.0")


def _args(project_root: Path, **overrides: bool) -> argparse.Namespace:
    values = {
        "project_root": project_root,
        "json": False,
        "legacy": False,
        "stale": False,
        "all_except_current": False,
        "dry_run": False,
        "force": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Project with a live venv (non-current fingerprint) and an unrelated stale one."""
    (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    untracked = tmp_path / "untracked"
    live = untracked / "venv-workspace-py311-81c29529"
    other = untracked / "venv-workspace-py311-00000000"
    _make_real_layout_venv(live)
    _make_real_layout_venv(other)
    return tmp_path, live, other


class TestLiveVenvIdentifiedByDirectory:
    def test_resolver_python_symlink_is_not_followed_to_the_interpreter(
        self, project: tuple[Path, Path, Path]
    ) -> None:
        project_root, live, _ = project

        with patch(f"{_CLI}.resolve_existing_venv_python", return_value=live / "bin" / "python"):
            live_dirs = cli._live_venv_realpaths(project_root)

        assert live.resolve() in live_dirs

    def test_running_interpreter_prefix_is_live(self, project: tuple[Path, Path, Path]) -> None:
        project_root, live, _ = project

        with (
            patch(f"{_CLI}.resolve_existing_venv_python", return_value=project_root / "missing"),
            patch(f"{_CLI}.sys.prefix", str(live)),
        ):
            live_dirs = cli._live_venv_realpaths(project_root)

        assert live.resolve() in live_dirs

    def test_enumerate_marks_live_venv_current(self, project: tuple[Path, Path, Path]) -> None:
        project_root, live, other = project

        with patch(f"{_CLI}.resolve_existing_venv_python", return_value=live / "bin" / "python"):
            entries = {e["path"]: e for e in cli._enumerate_venvs(project_root)}

        assert entries[str(live)]["is_current"] is True
        assert entries[str(other)]["is_current"] is False


class TestPruneNeverSelectsLiveVenv:
    @pytest.mark.parametrize("mode", ["all_except_current", "stale", "legacy"])
    def test_dry_run_never_lists_live_venv(
        self,
        project: tuple[Path, Path, Path],
        mode: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_root, live, _ = project

        with (
            patch(f"{_CLI}.resolve_existing_venv_python", return_value=live / "bin" / "python"),
            patch(f"{_CLI}.get_project_path", return_value=project_root),
        ):
            rc = cli.cmd_prune_venvs(_args(project_root, dry_run=True, **{mode: True}))

        assert rc == 0
        assert str(live) not in capsys.readouterr().out

    def test_force_all_except_current_removes_only_the_other_venv(
        self, project: tuple[Path, Path, Path]
    ) -> None:
        project_root, live, other = project

        with (
            patch(f"{_CLI}.resolve_existing_venv_python", return_value=live / "bin" / "python"),
            patch(f"{_CLI}.get_project_path", return_value=project_root),
        ):
            rc = cli.cmd_prune_venvs(_args(project_root, all_except_current=True, force=True))

        assert rc == 0
        assert live.is_dir(), "the live venv was deleted"
        assert not other.exists()
