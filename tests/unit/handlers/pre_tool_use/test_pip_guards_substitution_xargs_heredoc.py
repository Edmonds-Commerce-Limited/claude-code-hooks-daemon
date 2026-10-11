"""Ledger N407 residuals (batch Y).

* An exported PIP_BREAK_SYSTEM_PACKAGES governs a pip install inside `$( )` or
  backticks (a subshell inherits the environment).
* `xargs -a FILE`, `-I X`, `-d D`, `-E S`, `-s N`, `-L N` before `pip install`.
* A heredoc fed to an elevated shell (`sudo -i`, `sudo -s`, `sudo bash`) runs
  its body as root.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.pip_break_system import PipBreakSystemHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.sudo_pip import SudoPipHandler

_EXPORT = "export PIP_BREAK_SYSTEM_PACKAGES=1"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestExportGovernsSubstitution:
    @pytest.mark.parametrize(
        "command",
        [
            f"{_EXPORT}; x=$(pip install nonexistent-pkg-zz)",
            f"{_EXPORT}; echo $(pip install nonexistent-pkg-zz)",
            f"{_EXPORT}; echo `pip install nonexistent-pkg-zz`",
            f'{_EXPORT}; echo "done: $(pip install nonexistent-pkg-zz)"',
            f'{_EXPORT}; x=$(echo ")"; pip install nonexistent-pkg-zz)',
            f"{_EXPORT}; x=$(echo ')' && pip3 install nonexistent-pkg-zz)",
            f"{_EXPORT}; x=$(echo $(pip install nonexistent-pkg-zz))",
            f"{_EXPORT} && (y=$(pip install nonexistent-pkg-zz))",
        ],
    )
    def test_denied(self, command: str) -> None:
        assert PipBreakSystemHandler().matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            f"{_EXPORT}; x=$(pip --version)",
            f"{_EXPORT}; echo $(pip list)",
            f"{_EXPORT}; echo '$(pip install nonexistent-pkg-zz)'",
            "x=$(pip install nonexistent-pkg-zz)",
            "echo $(pip install nonexistent-pkg-zz)",
            "export PIP_BREAK_SYSTEM_PACKAGES=0; x=$(pip install nonexistent-pkg-zz)",
            f"{_EXPORT}; unset PIP_BREAK_SYSTEM_PACKAGES; x=$(pip install nonexistent-pkg-zz)",
            f"{_EXPORT}; echo $(date)",
        ],
    )
    def test_allowed(self, command: str) -> None:
        assert PipBreakSystemHandler().matches(_bash(command)) is False


class TestXargsValueOptions:
    @pytest.mark.parametrize(
        "command",
        [
            f"{_EXPORT}; xargs -a r.txt pip install",
            f"{_EXPORT}; xargs -I X pip install X",
            f"{_EXPORT}; xargs -I PKG pip install PKG",
            f"{_EXPORT}; xargs -d , pip install",
            f"{_EXPORT}; xargs -E END pip install",
            f"{_EXPORT}; xargs -r -a r.txt -n 1 pip install",
        ],
    )
    def test_denied(self, command: str) -> None:
        assert PipBreakSystemHandler().matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            f"{_EXPORT}; xargs --arg-file=r.txt pip install",
            f"{_EXPORT}; xargs -s 100 pip install",
            f"{_EXPORT}; xargs -L 2 pip install",
        ],
    )
    def test_denied_regression_guard(self, command: str) -> None:
        """These already denied before batch Y; kept so the new option regex cannot lose them."""
        assert PipBreakSystemHandler().matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            f"{_EXPORT}; xargs -a r.txt echo",
            f"{_EXPORT}; xargs -a r.txt pip list",
            "xargs -a r.txt pip install",
        ],
    )
    def test_allowed(self, command: str) -> None:
        assert PipBreakSystemHandler().matches(_bash(command)) is False


class TestElevatedShellHeredoc:
    @pytest.mark.parametrize(
        "command",
        [
            "sudo -i <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo -s <<EOF\npip install nonexistent-pkg-zz\nEOF",
            "sudo bash <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo sh -s <<EOF\ncd /srv\npip3 install nonexistent-pkg-zz\nEOF",
            "doas sh <<'EOF'\npython3 -m pip install nonexistent-pkg-zz\nEOF",
            "sudo -iu root <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo --login <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo --shell <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo --user root --login <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo -s 2>/dev/null <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo bash -s arg <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo bash -e -o pipefail <<'EOF'\npip install nonexistent-pkg-zz\nEOF",
            "sudo -u root /bin/bash <<'EOF'\nif true; then\n  pip install nonexistent-pkg-zz\nfi\nEOF",
            "cd /srv && sudo -i <<-'EOF'\n\tpip install nonexistent-pkg-zz\n\tEOF",
        ],
    )
    def test_denied(self, command: str) -> None:
        assert SudoPipHandler().matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "sudo -i",
            "sudo -s ls",
            # B1: a `<<` inside a quoted string is text, not a heredoc.
            'git commit -m "fix: judge elevated heredocs\n\nsudo -s <<EOF\npip install x\nEOF"',
            "git commit -m 'fix\n\nsudo bash <<EOF\npip install x\nEOF'",
            'git commit -m "docs; sudo -s <<EOF\npip install x\nEOF"',
            "python3 -c \"print('''\nsudo -s <<EOF\npip install x\nEOF\n''')\"",
            'echo "run: sudo -s <<EOF\npip install x\nEOF"',
            # B2: a script operand is what the shell runs; the heredoc is its stdin.
            "sudo bash script.sh <<EOF\npip install x\nEOF",
            "sudo bash ./setup.sh <<'EOF'\npip install x\nEOF",
            "sudo bash -e script.sh <<EOF\npip install x\nEOF",
            "sudo -i <<'EOF'\necho pip install x\nEOF",
            "sudo -i <<'EOF'\nsystemctl restart foo\nEOF",
            "sudo bash <<'EOF'\npip list\nEOF",
            "sudo -s ls <<'EOF'\npip install x\nEOF",
            "cat <<'EOF' > notes.md\nsudo pip install x\npip install x\nEOF",
            "cat <<'EOF'\npip install x\nEOF",
            "bash <<'EOF'\npip install x\nEOF",
            "sudo -i <<'EOF'\nls\nEOF\npip install x",
            "echo hi <<'EOF'\npip install x\nEOF",
            "git commit -F - <<'EOF'\nuse pip install x\nEOF",
        ],
    )
    def test_allowed(self, command: str) -> None:
        assert SudoPipHandler().matches(_bash(command)) is False
