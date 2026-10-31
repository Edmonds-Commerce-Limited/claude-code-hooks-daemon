"""Plan 00517 Tasks 3.2 and 3.3: UNPROVEN venvs are surfaced with evidence and removed by name.

A venv with missing or unreadable metadata, or another view's slug, is not
proven stale. ``list-venvs`` and ``prune-venvs --dry-run`` show it with the
facts that decide whether it is safe; ``prune-venvs --unproven <path> --force``
removes that one venv, and refuses whenever a process uses it or it is live.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.paths import project_path_slug, python_venv_fingerprint

STALE_HASH = "sha256:" + "0" * 64
_CLI = "claude_code_hooks_daemon.daemon.cli"
_RESOLVER = "claude_code_hooks_daemon.daemon.paths.resolve_existing_venv_python"
# The fixture's bin/python IS the running interpreter, so its pyvenv.cfg must
# record that version or the venv reads as interpreter-drifted (Plan 00555).
_CFG_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}.2"


def _args(project_root: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "project_root": project_root,
        "json": False,
        "legacy": False,
        "stale": False,
        "unproven": None,
        "all_except_current": False,
        "dry_run": False,
        "force": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _venv(path: Path, lock_hash: str | None = None) -> Path:
    """A venv whose bin/python is a symlink to the real interpreter."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    (path / "pyvenv.cfg").write_text(f"home = /usr/bin\nversion = {_CFG_VERSION}\n")
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(path / "bin" / "python"), "lock_hash": lock_hash})
        )
    return path


def _sleeper(venv: Path) -> subprocess.Popen[bytes]:
    """A process started through the venv's python, so its argv[0] names the venv."""
    return subprocess.Popen(
        [str(venv / "bin" / "python"), "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """A project whose resolver finds no venv, so none of the test venvs is live.

    The real resolver would serve a metadata-less venv as a last resort, which
    is exactly a venv the daemon uses; the live-venv tests patch it themselves.
    """
    (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "untracked").mkdir()
    with patch(_RESOLVER, return_value=tmp_path / "no-venv" / "bin" / "python"):
        yield tmp_path


def _run(func: Callable[[argparse.Namespace], int], project: Path, **overrides: object) -> int:
    with patch(f"{_CLI}.get_project_path", return_value=project):
        return func(_args(project, **overrides))


def _orphan(project: Path, tail: str = "py310-0badcafe") -> Path:
    """A venv of this view with no readable metadata: UNPROVEN."""
    return _venv(project / "untracked" / f"venv-{project_path_slug(project)}-{tail}")


class TestListVenvsShowsEvidence:
    def test_unproven_venv_is_listed_with_evidence_and_removal_command(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        orphan = _orphan(project)

        assert _run(cli.cmd_list_venvs, project) == 0

        out = capsys.readouterr().out
        assert "UNPROVEN" in out
        assert str(orphan) in out
        assert "no process found using it" in out
        assert f"interpreter: /usr/bin (python {_CFG_VERSION})" in out
        assert "last modified:" in out
        assert "belongs to: this view" in out
        assert f"prune-venvs --unproven {orphan} --force" in out

    def test_another_views_venv_names_the_view(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _venv(project / "untracked" / "venv-somewhere-else-py310-0badcafe", STALE_HASH)

        assert _run(cli.cmd_list_venvs, project) == 0

        assert "another view (slug 'somewhere-else'" in capsys.readouterr().out

    def test_a_process_using_the_venv_is_shown(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        child = _sleeper(_orphan(project))
        try:
            _run(cli.cmd_list_venvs, project)
        finally:
            child.terminate()
            child.wait(timeout=Timeout.DAEMON_SHUTDOWN)

        assert f"IN USE: pid {child.pid}" in capsys.readouterr().out

    def test_no_section_when_every_venv_is_explained(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _venv(project / "untracked" / f"venv-{python_venv_fingerprint(project)}")
        slug = project_path_slug(project)
        _venv(project / "untracked" / f"venv-{slug}-py310-0badcafe", STALE_HASH)

        assert _run(cli.cmd_list_venvs, project) == 0

        out = capsys.readouterr().out
        assert "UNPROVEN" not in out
        assert "stale" in out

    def test_json_carries_the_evidence(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        orphan = _orphan(project)

        assert _run(cli.cmd_list_venvs, project, json=True) == 0

        (entry,) = json.loads(capsys.readouterr().out)
        assert entry["verdict"] == "unproven"
        assert entry["evidence"]["path"] == str(orphan)
        assert entry["evidence"]["processes"] == []


class TestPruneDryRunShowsEvidence:
    def test_stale_dry_run_reports_unproven_venvs_without_removing_them(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        slug = project_path_slug(project)
        stale = _venv(project / "untracked" / f"venv-{slug}-py310-aaaaaaaa", STALE_HASH)
        orphan = _orphan(project, "py310-bbbbbbbb")

        assert _run(cli.cmd_prune_venvs, project, stale=True, dry_run=True) == 0

        out = capsys.readouterr().out
        assert str(stale) in out
        assert "UNPROVEN venv(s)" in out
        assert str(orphan) in out
        assert stale.exists()
        assert orphan.exists()


class TestPruneUnproven:
    def test_force_removes_the_named_unproven_venv_only(self, project: Path) -> None:
        orphan = _orphan(project)
        other = _venv(project / "untracked" / "venv-somewhere-else-py310-0badcafe")

        assert _run(cli.cmd_prune_venvs, project, unproven=str(orphan), force=True) == 0

        assert not orphan.exists()
        assert other.exists()

    def test_dry_run_shows_evidence_and_removes_nothing(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        orphan = _orphan(project)

        assert _run(cli.cmd_prune_venvs, project, unproven=str(orphan), dry_run=True) == 0

        assert orphan.exists()
        out = capsys.readouterr().out
        assert "no process found using it" in out
        assert "(dry-run) No changes made." in out

    def test_refuses_without_force_or_dry_run(self, project: Path) -> None:
        orphan = _orphan(project)

        assert _run(cli.cmd_prune_venvs, project, unproven=str(orphan)) == 1

        assert orphan.exists()

    def test_refuses_when_a_process_uses_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        orphan = _orphan(project)
        child = _sleeper(orphan)
        try:
            rc = _run(cli.cmd_prune_venvs, project, unproven=str(orphan), force=True)
        finally:
            child.terminate()
            child.wait(timeout=Timeout.DAEMON_SHUTDOWN)

        assert rc == 1
        assert orphan.exists()
        assert str(child.pid) in capsys.readouterr().err

    def test_refuses_the_live_venv(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        live = _orphan(project)

        with patch(_RESOLVER, return_value=live / "bin" / "python"):
            rc = _run(cli.cmd_prune_venvs, project, unproven=str(live), force=True)

        assert rc == 1
        assert live.exists()
        assert "current or live" in capsys.readouterr().err

    def test_refuses_the_current_fingerprints_venv(self, project: Path) -> None:
        current = _venv(project / "untracked" / f"venv-{python_venv_fingerprint(project)}")

        assert _run(cli.cmd_prune_venvs, project, unproven=str(current), force=True) == 1

        assert current.exists()

    def test_refuses_a_proven_stale_venv_and_points_at_stale(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        slug = project_path_slug(project)
        stale = _venv(project / "untracked" / f"venv-{slug}-py310-aaaaaaaa", STALE_HASH)

        assert _run(cli.cmd_prune_venvs, project, unproven=str(stale), force=True) == 1

        assert stale.exists()
        assert "--stale" in capsys.readouterr().err

    def test_refuses_a_path_that_is_no_venv_here(
        self, project: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        (elsewhere / "keep.txt").write_text("x")

        assert _run(cli.cmd_prune_venvs, project, unproven=str(elsewhere), force=True) == 1

        assert (elsewhere / "keep.txt").exists()

    def test_refuses_a_symlink_name(self, project: Path) -> None:
        orphan = _orphan(project)
        link = project / "untracked" / f"venv-{project_path_slug(project)}-py311-linked"
        link.symlink_to(orphan, target_is_directory=True)

        assert _run(cli.cmd_prune_venvs, project, unproven=str(link), force=True) == 1

        assert orphan.exists()

    def test_cannot_be_combined_with_a_bulk_selection(self, project: Path) -> None:
        orphan = _orphan(project)

        rc = _run(cli.cmd_prune_venvs, project, unproven=str(orphan), stale=True, force=True)

        assert rc == 1
        assert orphan.exists()
