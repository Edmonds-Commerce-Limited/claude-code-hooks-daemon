"""Ledger N407 residuals (batch U): how far an exported PIP_BREAK_SYSTEM_PACKAGES reaches.

An export is cancelled by `unset` / `export -n`, does not cross a pipe (each
side is a subshell), does not outlive a `( ... )` group, and does govern a pip
install run inside one or behind `command` / `xargs`.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.pip_break_system import PipBreakSystemHandler

_VAR = "PIP_BREAK_SYSTEM_PACKAGES"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> PipBreakSystemHandler:
    return PipBreakSystemHandler()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


_DENY = [
    # leading ( is a group, not part of the command word
    f"( {_VAR}=1 pip install x )",
    f"({_VAR}=1 pip install x)",
    f"(export {_VAR}=1; pip install x)",
    f"export {_VAR}=1; (pip install x)",
    f"export {_VAR}=1; ( pip install x )",
    f"(export {_VAR}=1; (pip install x))",
    # command / xargs in front of pip
    f"export {_VAR}=1; command pip install x",
    f"export {_VAR}=1; command -p pip install x",
    f"export {_VAR}=1; xargs pip install < r.txt",
    f"export {_VAR}=1; xargs -n 1 pip install < r.txt",
    f"export {_VAR}=1; xargs -r pip install < r.txt",
    f"{_VAR}=1 command pip install x",
    # an export before a pipeline still reaches every stage
    f"export {_VAR}=1; echo x | pip install x",
    # unset / export -n of another name, or re-export after cancel
    f"export {_VAR}=1; unset OTHER; pip install x",
    f"export {_VAR}=1; export -n OTHER; pip install x",
    f"export {_VAR}=1; unset {_VAR}; export {_VAR}=1; pip install x",
    # an unset inside a group does not cancel the outer export
    f"export {_VAR}=1; (unset {_VAR}); pip install x",
    # a pipe stage's unset does not cancel the outer export
    f"export {_VAR}=1; unset {_VAR} | cat; pip install x",
]

_ALLOW = [
    f"export {_VAR}=1; unset {_VAR}; pip install x",
    f"export {_VAR}=1; unset -v {_VAR}; pip install x",
    f"export {_VAR}=1; unset OTHER {_VAR}; pip install x",
    f"export {_VAR}=1; export -n {_VAR}; pip install x",
    f"export {_VAR}=1 && unset {_VAR} && pip install x",
    # each pipe side is a subshell
    f"export {_VAR}=1 | pip install x",
    f"export {_VAR}=1 |& pip install x",
    f"export {_VAR}=1 | cat; pip install x",
    f"echo hi | export {_VAR}=1; pip install x",
    # an export made inside a group does not outlive it
    f"(export {_VAR}=1); pip install x",
    f"( export {_VAR}=1 ); pip install x",
    f"(export {_VAR}=1; true) && pip install x",
    # mentions and look-alikes
    f"export {_VAR}=1; command ls",
    f"export {_VAR}=1; xargs ls < r.txt",
    f"echo '({_VAR}=1 pip install x)'",
    "(pip install x)",
    f"command pip install x # {_VAR}=1",
]


@pytest.mark.parametrize("command", _DENY)
def test_denies(handler: PipBreakSystemHandler, command: str) -> None:
    assert handler.matches(_bash(command)) is True, command


@pytest.mark.parametrize("command", _ALLOW)
def test_allows(handler: PipBreakSystemHandler, command: str) -> None:
    assert handler.matches(_bash(command)) is False, command
