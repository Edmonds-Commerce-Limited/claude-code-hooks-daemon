"""The ``housekeeping`` CLI verb (Plan 00330 Phase 3).

The verb prints the procedure the routed ``housekeeping`` skill subcommand
follows; it runs no step itself. Its exit contract: 0 procedure printed,
2 when ``--apply`` names an unknown step or the project root is not a
directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_housekeeping
from claude_code_hooks_daemon.daemon.housekeeping import step_names


def _args(root: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "project_root": str(root),
        "apply": [],
        "list_steps": False,
        "reports_dir": "untracked/reports",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def client_root(tmp_path: Path) -> Path:
    """A client-shaped install: the wrapper lives under .claude/hooks-daemon/."""
    wrapper = tmp_path / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o755)
    return tmp_path


class TestProcedure:
    def test_prints_the_procedure_naming_every_step(
        self, client_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_housekeeping(_args(client_root)) == 0
        out = capsys.readouterr().out
        for name in step_names():
            assert f"`{name}`" in out

    def test_uses_the_client_wrapper_path(
        self, client_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_housekeeping(_args(client_root))
        out = capsys.readouterr().out
        assert str(client_root / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon") in out

    def test_self_install_falls_back_to_the_repo_wrapper(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        wrapper = tmp_path / "bin" / "hooks-daemon"
        wrapper.parent.mkdir()
        wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
        cmd_housekeeping(_args(tmp_path))
        assert str(wrapper) in capsys.readouterr().out

    def test_apply_releases_the_named_step(
        self, client_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_housekeeping(_args(client_root, apply=["prune-venvs"]))
        out = capsys.readouterr().out
        assert "--apply prune-venvs" not in out
        assert "--apply optimise" in out

    def test_unknown_apply_step_exits_2_and_lists_the_valid_names(
        self, client_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_housekeeping(_args(client_root, apply=["everything"])) == 2
        err = capsys.readouterr().err
        assert "everything" in err
        assert "prune-venvs" in err

    def test_list_prints_one_line_per_step_and_no_procedure(
        self, client_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_housekeeping(_args(client_root, list_steps=True)) == 0
        out = capsys.readouterr().out
        assert "Housekeeping Pass" not in out
        assert len([line for line in out.splitlines() if line.strip()]) == len(step_names())

    def test_missing_project_root_exits_2(self, tmp_path: Path) -> None:
        assert cmd_housekeeping(_args(tmp_path / "absent")) == 2
