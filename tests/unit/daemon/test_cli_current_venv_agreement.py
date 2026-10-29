"""GitHub #120 / N460: ``list-venvs`` and ``prune-venvs`` name the venv the resolver selects.

Venvs are keyed on the DAEMON directory (``.claude/hooks-daemon/`` in a client
install, the project root in self-install). The header, the ``current`` marker
and ``prune-venvs`` must all ask the one resolver, never re-derive a
fingerprint from the project root, so the header names a venv that exists and
the marker sits on that venv, in both install modes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.paths import (
    current_venv_dir,
    project_path_slug,
    python_venv_fingerprint,
)


def _make_venv(path: Path) -> None:
    """Create a venv whose bin/python is a symlink to the real interpreter, proven stale."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    (path / "pyvenv.cfg").write_text(
        f"home = {Path(sys.executable).resolve().parent}\n"
        f"version_info = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
    )
    (path / ".daemon-version").write_text("v3.5.0")
    (path / ".daemon-metadata.json").write_text(
        json.dumps({"python_path": str(path / "bin" / "python"), "lock_hash": "sha256:" + "0" * 64})
    )


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


@pytest.fixture(autouse=True)
def _isolated_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """No venv override, and the project root is the one the test passes."""
    monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
    monkeypatch.setattr(cli, "get_project_path", lambda override=None: Path(str(override)))


@pytest.fixture
def client_install(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A client install: (project root, daemon dir, the venv the bootstrap built)."""
    project = tmp_path / "app"
    daemon_dir = project / ".claude" / "hooks-daemon"
    (project / ".git").mkdir(parents=True)
    daemon_dir.mkdir(parents=True)
    (daemon_dir / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    live = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
    _make_venv(live)
    return project, daemon_dir, live


@pytest.fixture
def self_install(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A self-install whose live venv carries a fingerprint other than this interpreter's.

    Returns (project root, daemon dir, live venv). The resolver reaches the live
    venv through its scan fallback, the N460 shape.
    """
    project = tmp_path / "selfproj"
    (project / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    (project / ".claude").mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    live = project / "untracked" / f"venv-{project_path_slug(project)}-py311-81c29529"
    _make_venv(live)
    return project, project, live


class TestCurrentVenvDir:
    def test_client_install_is_keyed_on_the_daemon_dir(
        self, client_install: tuple[Path, Path, Path]
    ) -> None:
        _, daemon_dir, live = client_install

        assert current_venv_dir(daemon_dir) == live

    def test_self_install_follows_the_resolver_scan(
        self, self_install: tuple[Path, Path, Path]
    ) -> None:
        _, daemon_dir, live = self_install

        assert current_venv_dir(daemon_dir) == live


class TestListVenvsClientInstall:
    def test_header_names_the_venv_that_exists(
        self, client_install: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        project, _, live = client_install

        assert cli.cmd_list_venvs(_args(project)) == 0

        out = capsys.readouterr().out
        fingerprint = live.name.removeprefix("venv-")
        assert fingerprint in out.splitlines()[0]
        assert project_path_slug(project) not in out.splitlines()[0]

    def test_live_venv_is_marked_current(self, client_install: tuple[Path, Path, Path]) -> None:
        project, _, live = client_install

        entries = {e["path"]: e for e in cli._enumerate_venvs(project)}

        assert entries[str(live)]["is_current"] is True

    def test_table_marks_the_venv_the_header_names(
        self, client_install: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        project, _, live = client_install

        cli.cmd_list_venvs(_args(project))

        rows = [line for line in capsys.readouterr().out.splitlines() if str(live) in line]
        assert len(rows) == 1
        assert "current" in rows[0]


class TestListVenvsSelfInstall:
    def test_header_names_the_resolved_venv_not_a_fresh_fingerprint(
        self, self_install: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        project, _, live = self_install

        cli.cmd_list_venvs(_args(project))

        out = capsys.readouterr().out
        assert live.name.removeprefix("venv-") in out.splitlines()[0]
        rows = [line for line in out.splitlines() if str(live) in line]
        assert len(rows) == 1
        assert "current" in rows[0]

    def test_a_different_fingerprint_for_a_new_venv_is_stated(
        self, self_install: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        project, daemon_dir, _ = self_install

        cli.cmd_list_venvs(_args(project))

        assert f"venv-{python_venv_fingerprint(daemon_dir)}" in capsys.readouterr().out


class TestPruneNeverSelectsCurrentVenv:
    @pytest.mark.parametrize("mode", ["stale", "legacy"])
    def test_client_install_dry_run_never_lists_live_venv(
        self,
        client_install: tuple[Path, Path, Path],
        mode: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project, _, live = client_install

        rc = cli.cmd_prune_venvs(_args(project, dry_run=True, **{mode: True}))

        out = capsys.readouterr().out
        assert rc == 0
        assert "Pruning" not in out
        assert live.name.removeprefix("venv-") in out

    def test_client_install_force_stale_keeps_live_venv_and_removes_the_other(
        self, client_install: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        project, daemon_dir, live = client_install
        other = daemon_dir / "untracked" / f"venv-{project_path_slug(daemon_dir)}-py311-00000000"
        _make_venv(other)

        rc = cli.cmd_prune_venvs(_args(project, stale=True, force=True))

        out = capsys.readouterr().out
        assert rc == 0
        assert live.is_dir(), "the live venv was deleted"
        assert not other.exists()
        assert f"Current venv preserved: {live.name.removeprefix('venv-')}" in out

    def test_self_install_message_names_the_resolved_venv(
        self, self_install: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        project, _, live = self_install

        rc = cli.cmd_prune_venvs(_args(project, stale=True, dry_run=True))

        assert rc == 0
        assert f"Current venv: {live.name.removeprefix('venv-')}" in capsys.readouterr().out
