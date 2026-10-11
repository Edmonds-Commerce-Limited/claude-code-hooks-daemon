"""Ledger N407 residuals (batch W).

* `sudo bash -c 'cd d; pip install x'`: the splitter cut the quoted program at
  `;`/`&&`, so the `pip install` segment lost the `sudo` that runs it.
* `git grep -n 'pip install --break-system-packages'` and `git log -S 'sudo pip
  install'`: a read-only git command's quoted search literal is data.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.pip_break_system import PipBreakSystemHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.sudo_pip import SudoPipHandler
from claude_code_hooks_daemon.utils.command_position import command_position_view


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestSudoShellProgramSegments:
    """Every segment of a `sudo ... -c '<program>'` body runs as root."""

    @pytest.mark.parametrize(
        "command",
        [
            "sudo bash -c 'cd /srv; pip install nonexistent-pkg-zz'",
            "sudo sh -c 'echo hi && pip install nonexistent-pkg-zz'",
            'sudo bash -c "cd /srv; pip install nonexistent-pkg-zz"',
            "sudo -u root bash -c 'cd /srv; pip3 install nonexistent-pkg-zz'",
            "doas sh -c 'cd /srv || pip install nonexistent-pkg-zz'",
            "sudo bash -c 'cd /srv; python3 -m pip install nonexistent-pkg-zz'",
            "sudo bash -c 'cd /srv; bash -c \"cd /x; pip install nonexistent-pkg-zz\"'",
            "if true; then sudo bash -c 'cd /srv; pip install nonexistent-pkg-zz'; fi",
            "echo $(sudo bash -c 'cd /srv; pip install nonexistent-pkg-zz')",
            "sudo bash -c 'cd /srv; pip install nonexistent-pkg-zz' # note",
        ],
    )
    def test_denied(self, command: str) -> None:
        assert SudoPipHandler().matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "sudo bash -c 'cd /srv; echo hi'",
            "sudo bash -c 'cd /srv; echo \"pip install x\"'",
            "sudo bash -c 'cd /srv; pip list'",
            "bash -c 'cd /srv; pip install nonexistent-pkg-zz'",
            "echo \"sudo bash -c 'cd x; pip install y'\"",
            "git commit -m \"sudo bash -c 'cd x; pip install y'\"",
            "grep 'sudo bash -c x; pip install y' notes.md",
            "git grep -n \"sudo bash -c 'cd x; pip install y'\"",
        ],
    )
    def test_allowed(self, command: str) -> None:
        assert SudoPipHandler().matches(_bash(command)) is False

    def test_view_heads_later_segments_with_sudo(self) -> None:
        assert (
            command_position_view("sudo bash -c 'cd /srv; pip install x'")
            == "sudo bash -c cd /srv; sudo pip install x"
        )

    def test_view_leaves_unelevated_body_alone(self) -> None:
        assert (
            command_position_view("bash -c 'cd /srv; pip install x'")
            == "bash -c cd /srv; pip install x"
        )


class TestSearchPatternIsData:
    """A search tool's quoted multi-word pattern is data, never a command."""

    @pytest.mark.parametrize(
        "command",
        [
            "git grep -n 'pip install --break-system-packages'",
            "git grep -e 'pip install --break-system-packages' -- docs",
            "git log -S 'pip install --break-system-packages' --oneline",
            "git log -S 'sudo pip install' --oneline",
            "git log --grep='sudo pip install'",
            "git grep -n 'sudo pip install'",
            "rg 'pip install --break-system-packages' docs/",
            "rg 'sudo pip install' docs/",
            "bash -c \"git grep -n 'pip install --break-system-packages'\"",
        ],
    )
    def test_allowed_by_both_guards(self, command: str) -> None:
        assert PipBreakSystemHandler().matches(_bash(command)) is False
        assert SudoPipHandler().matches(_bash(command)) is False

    def test_search_then_real_install_still_denies(self) -> None:
        command = "git grep 'pip install' && pip install --break-system-packages x"
        assert PipBreakSystemHandler().matches(_bash(command)) is True

    def test_search_then_real_sudo_install_still_denies(self) -> None:
        command = "git log -S 'x y' && sudo pip install x"
        assert SudoPipHandler().matches(_bash(command)) is True

    def test_git_output_piped_to_shell_is_still_judged(self) -> None:
        command = "git log --format='sudo pip install x' | sh"
        assert SudoPipHandler().matches(_bash(command)) is True
