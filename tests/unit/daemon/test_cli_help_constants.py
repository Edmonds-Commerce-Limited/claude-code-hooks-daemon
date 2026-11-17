"""T-12: help text quotes the constants it describes instead of repeating their values."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core import branch_cleanup, branch_creation
from claude_code_hooks_daemon.daemon import cli


def _help_of(command: str, capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([command, "--help"])
    return " ".join(capsys.readouterr().out.split())


def test_branch_sweep_help_names_the_bulk_batch_size(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(branch_cleanup, "BULK_BATCH_SIZE", 7)

    assert "in batches of 7," in _help_of("branch-sweep", capsys)


def test_branch_preflight_help_names_the_refused_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(branch_creation, "EXIT_CREATION_REFUSED", 9)

    assert "Exit 0 when a branch may be created, 9 when" in _help_of("branch-preflight", capsys)
