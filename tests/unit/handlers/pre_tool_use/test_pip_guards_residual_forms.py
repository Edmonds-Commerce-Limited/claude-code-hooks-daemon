"""Ledger N407 residuals (batch S): respellings the pip guards used to miss.

`sudo_pip` missed sudo options that take a value, `sudo env`, `sudo bash -c`
and `doas`; `pip_break_system` missed the flag before the subcommand, the
`PIP_BREAK_SYSTEM_PACKAGES` env var and a versioned `pip3.11`. Mentions of any
of these must still be allowed.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.pip_break_system import PipBreakSystemHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.sudo_pip import SudoPipHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


_SUDO_DENY = [
    "sudo -u root pip install nonexistent-pkg-zz",
    "sudo -iu root pip install nonexistent-pkg-zz",
    "sudo -u root -H pip3 install nonexistent-pkg-zz",
    "sudo --user=root pip install nonexistent-pkg-zz",
    "sudo env pip install nonexistent-pkg-zz",
    "sudo env FOO=1 pip install nonexistent-pkg-zz",
    "sudo FOO=1 pip install nonexistent-pkg-zz",
    "sudo bash -c 'pip install nonexistent-pkg-zz'",
    'sudo sh -c "python3 -m pip install nonexistent-pkg-zz"',
    "sudo -E bash -lc 'pip3 install nonexistent-pkg-zz'",
    "doas pip install nonexistent-pkg-zz",
    "doas -u root pip install nonexistent-pkg-zz",
    "sudo --user root pip install nonexistent-pkg-zz",
    "sudo -p 'pw: ' pip install nonexistent-pkg-zz",
    "sudo pip -q install nonexistent-pkg-zz",
    "sudo pip3.11 install nonexistent-pkg-zz",
    "sudo python3.11 -m pip install nonexistent-pkg-zz",
]

_SUDO_ALLOW = [
    "sudo -u root ls",
    "sudo apt install pip",
    "sudo bash -c 'ls'",
    "sudo env ls",
    "doas ls",
    "sudo -n ls pip install",
    "pip install nonexistent-pkg-zz",
    "doas apt install python3-pip",
]

_BREAK_DENY = [
    "pip --break-system-packages install nonexistent-pkg-zz",
    "pip3 --break-system-packages install nonexistent-pkg-zz",
    "pip -q --break-system-packages install nonexistent-pkg-zz",
    "python3 -m pip --break-system-packages install nonexistent-pkg-zz",
    "PIP_BREAK_SYSTEM_PACKAGES=1 pip install nonexistent-pkg-zz",
    "PIP_BREAK_SYSTEM_PACKAGES=true pip3 install nonexistent-pkg-zz",
    "FOO=1 PIP_BREAK_SYSTEM_PACKAGES=1 pip install nonexistent-pkg-zz",
    "env PIP_BREAK_SYSTEM_PACKAGES=1 pip install nonexistent-pkg-zz",
    "export PIP_BREAK_SYSTEM_PACKAGES=1 && pip install nonexistent-pkg-zz",
    "export PIP_BREAK_SYSTEM_PACKAGES=1; pip3 install nonexistent-pkg-zz",
    "declare -x PIP_BREAK_SYSTEM_PACKAGES=1; python3 -m pip install nonexistent-pkg-zz",
    "export PIP_BREAK_SYSTEM_PACKAGES='yes'; pip install nonexistent-pkg-zz",
    "export PIP_BREAK_SYSTEM_PACKAGES=0 && PIP_BREAK_SYSTEM_PACKAGES=1 pip install x",
    "PIP_BREAK_SYSTEM_PACKAGES='1' pip install nonexistent-pkg-zz",
    "PIP_BREAK_SYSTEM_PACKAGES=1 sudo pip install nonexistent-pkg-zz",
    "bash -c 'PIP_BREAK_SYSTEM_PACKAGES=1 pip install nonexistent-pkg-zz'",
    "pip3.11 install --break-system-packages nonexistent-pkg-zz",
    "python3.11 -m pip install --break-system-packages nonexistent-pkg-zz",
    "/usr/bin/pip3.12 install --break-system-packages nonexistent-pkg-zz",
]

_BREAK_ALLOW = [
    "PIP_BREAK_SYSTEM_PACKAGES=0 pip install nonexistent-pkg-zz",
    "export PIP_BREAK_SYSTEM_PACKAGES=false",
    "PIP_BREAK_SYSTEM_PACKAGES='0' pip install nonexistent-pkg-zz",
    'PIP_BREAK_SYSTEM_PACKAGES="false" pip install nonexistent-pkg-zz',
    "PIP_BREAK_SYSTEM_PACKAGES='' pip install nonexistent-pkg-zz",
    "export PIP_BREAK_SYSTEM_PACKAGES=1",
    "export PIP_BREAK_SYSTEM_PACKAGES=1; ls",
    "export PIP_BREAK_SYSTEM_PACKAGES=1; echo pip install x",
    "export PIP_BREAK_SYSTEM_PACKAGES=1; export PIP_BREAK_SYSTEM_PACKAGES=0; pip install x",
    "PIP_BREAK_SYSTEM_PACKAGES=1 make",
    "git grep -n PIP_BREAK_SYSTEM_PACKAGES=1",
    "find . -name PIP_BREAK_SYSTEM_PACKAGES=1",
    "ls PIP_BREAK_SYSTEM_PACKAGES=1",
    "docker run -e PIP_BREAK_SYSTEM_PACKAGES=1 img",
    "pip3.11 install --user nonexistent-pkg-zz",
    "python3.11 -m pip install nonexistent-pkg-zz",
    "pip --version",
    "pip install nonexistent-pkg-zz",
]


def _mentions(dangerous: str) -> list[str]:
    # A `;`/`&&` inside a trailing comment still splits the line (splitter
    # limitation, recorded as an N407 residual), so a compound dangerous text
    # is not offered as a comment.
    comment = [] if (";" in dangerous or "&&" in dangerous) else [f"true # {dangerous}"]
    return [
        *comment,
        f'echo "{dangerous}"',
        f"echo '{dangerous}'",
        f'git commit -m "docs: never run {dangerous}"',
        f"git commit -m 'docs: never run {dangerous}'",
        f"grep -rn '{dangerous}' docs/",
        f"cat > notes.md <<'EOF'\nNever run {dangerous}\nEOF",
    ]


class TestSudoPipResiduals:
    @pytest.fixture
    def handler(self) -> SudoPipHandler:
        return SudoPipHandler()

    @pytest.mark.parametrize("command", _SUDO_DENY)
    def test_denies(self, handler: SudoPipHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize("command", _SUDO_DENY)
    def test_denies_inside_control_flow(self, handler: SudoPipHandler, command: str) -> None:
        assert handler.matches(_bash(f"if true; then {command}; fi")) is True

    @pytest.mark.parametrize("command", _SUDO_ALLOW)
    def test_allows_other_commands(self, handler: SudoPipHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is False

    @pytest.mark.parametrize("dangerous", _SUDO_DENY)
    def test_mentions_allowed(self, handler: SudoPipHandler, dangerous: str) -> None:
        for command in _mentions(dangerous):
            assert handler.matches(_bash(command)) is False, command


class TestPipBreakSystemResiduals:
    @pytest.fixture
    def handler(self) -> PipBreakSystemHandler:
        return PipBreakSystemHandler()

    @pytest.mark.parametrize("command", _BREAK_DENY)
    def test_denies(self, handler: PipBreakSystemHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize("command", _BREAK_DENY)
    def test_denies_inside_control_flow(self, handler: PipBreakSystemHandler, command: str) -> None:
        assert handler.matches(_bash(f"if true; then {command}; fi")) is True

    @pytest.mark.parametrize("command", _BREAK_ALLOW)
    def test_allows_safe_forms(self, handler: PipBreakSystemHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is False

    @pytest.mark.parametrize("dangerous", _BREAK_DENY)
    def test_mentions_allowed(self, handler: PipBreakSystemHandler, dangerous: str) -> None:
        for command in _mentions(dangerous):
            assert handler.matches(_bash(command)) is False, command
