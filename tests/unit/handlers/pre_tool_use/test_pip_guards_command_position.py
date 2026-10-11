"""Ledger N407: the pip guards judge what a command RUNS, not what it mentions.

`pip_break_system` and `sudo_pip` matched their patterns over the raw string,
so an `echo`, a commit message, a grep pattern, a comment or a quoted heredoc
body that merely named the dangerous text was denied. Every real invocation
shape must still deny.
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


# (handler class, the dangerous text, the benign form of the same text)
_BREAK = "pip install --break-system-packages nonexistent-pkg-zz"
_SUDO = "sudo pip install nonexistent-pkg-zz"


def _real_invocations(dangerous: str, binary_forms: list[tuple[str, str]]) -> list[str]:
    shapes = [
        dangerous,
        f"if true; then {dangerous}; fi",
        f'bash -c "{dangerous}"',
        f"bash -c '{dangerous}'",
        f'eval "{dangerous}"',
        f"env FOO=1 {dangerous}",
        f"nohup {dangerous}",
        f"timeout 5 {dangerous}",
        f"true && {dangerous}",
        f"true || {dangerous}",
        f"true; {dangerous}",
        f"echo hi | {dangerous}",
        f"({dangerous})",
        f"echo $({dangerous})",
        f"echo `{dangerous}`",
        f"sleep 1 & {dangerous}",
        f"! {dangerous}",
        f"{dangerous} # trailing note",
        f"cat <<'EOF' | bash\n{dangerous}\nEOF",
        f"bash <<'EOF'\n{dangerous}\nEOF",
        f"bash <<EOF\n{dangerous}\nEOF",
        f"echo ok\n{dangerous}",
    ]
    return shapes


_BREAK_FORMS = [
    "pip3 install --break-system-packages nonexistent-pkg-zz",
    "/usr/bin/pip install --break-system-packages nonexistent-pkg-zz",
    "python -m pip install --break-system-packages nonexistent-pkg-zz",
    "python3 -m pip install --break-system-packages nonexistent-pkg-zz",
    "uv pip install --break-system-packages nonexistent-pkg-zz",
    "pip install nonexistent-pkg-zz --break-system-packages",
]
_SUDO_FORMS = [
    "sudo -H pip install nonexistent-pkg-zz",
    "sudo /usr/bin/pip install nonexistent-pkg-zz",
    "sudo pip3 install nonexistent-pkg-zz",
    "sudo python -m pip install nonexistent-pkg-zz",
    "sudo python3 -m pip install nonexistent-pkg-zz",
]


def _mentions(dangerous: str) -> list[str]:
    return [
        f'echo "{dangerous}"',
        f"echo '{dangerous}'",
        f"printf '%s\\n' '{dangerous}'",
        f'git commit -m "docs: never run {dangerous}"',
        f"git commit -m 'docs: never run {dangerous}'",
        f"git tag -m 'do not {dangerous}' v1",
        f'gh issue comment 5 --body "{dangerous} is wrong"',
        f'gh pr create --title "t" --body "{dangerous}"',
        f"grep -rn '{dangerous}' docs/",
        f'rg "{dangerous}" src/',
        f"true # {dangerous}",
        f"ls && echo 'avoid: {dangerous}'",
        f"cat > notes.md <<'EOF'\nNever run {dangerous}\nEOF",
        f"cat <<'EOF'\n{dangerous}\nEOF",
        f"git commit -F - <<'EOF'\nfix: {dangerous}\nEOF",
    ]


class TestPipBreakSystemCommandPosition:
    @pytest.fixture
    def handler(self) -> PipBreakSystemHandler:
        return PipBreakSystemHandler()

    @pytest.mark.parametrize("command", _mentions(_BREAK))
    def test_mention_is_allowed(self, handler: PipBreakSystemHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is False

    @pytest.mark.parametrize("command", _real_invocations(_BREAK, []) + _BREAK_FORMS)
    def test_real_invocation_is_denied(self, handler: PipBreakSystemHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize("form", _BREAK_FORMS)
    def test_binary_forms_deny_inside_control_flow(
        self, handler: PipBreakSystemHandler, form: str
    ) -> None:
        assert handler.matches(_bash(f"if true; then {form}; fi")) is True

    def test_mention_then_real_invocation_denies(self, handler: PipBreakSystemHandler) -> None:
        command = f'echo "{_BREAK}"; {_BREAK}'
        assert handler.matches(_bash(command)) is True


class TestSudoPipCommandPosition:
    @pytest.fixture
    def handler(self) -> SudoPipHandler:
        return SudoPipHandler()

    @pytest.mark.parametrize("command", _mentions(_SUDO))
    def test_mention_is_allowed(self, handler: SudoPipHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is False

    @pytest.mark.parametrize("command", _real_invocations(_SUDO, []) + _SUDO_FORMS)
    def test_real_invocation_is_denied(self, handler: SudoPipHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize("form", _SUDO_FORMS)
    def test_binary_forms_deny_inside_control_flow(
        self, handler: SudoPipHandler, form: str
    ) -> None:
        assert handler.matches(_bash(f"if true; then {form}; fi")) is True

    def test_mention_then_real_invocation_denies(self, handler: SudoPipHandler) -> None:
        assert handler.matches(_bash(f'echo "{_SUDO}"; {_SUDO}')) is True


class TestAcceptanceTestsNeverRun:
    @pytest.mark.parametrize("handler_cls", [PipBreakSystemHandler, SudoPipHandler])
    def test_deny_commands_are_parse_only(self, handler_cls: Any) -> None:
        for test in handler_cls().get_acceptance_tests():
            assert test.command.startswith("bash -n -c '")
            assert handler_cls().matches(_bash(test.command)) is True
