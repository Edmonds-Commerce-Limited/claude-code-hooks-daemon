"""A grep pattern inside a single-quoted ``bash -c`` program is text, not a path
(ledger 00474 N356).

N269 made a quoted word received by a pure text consumer (a grep/rg pattern,
echo/printf arguments) a literal, never a glob, but only for commands at the top
level or inside a substitution. The program string of ``bash -c '...'`` is a
command of its own that the scan never segmented, so ``grep -E "^(src|tests)/.*:[0-9]+"``
inside it was read as the glob ``/.*:[0-9]+`` and denied against a protected
dotfile glob.

Every reader of a protected file stays denied inside the program exactly as at
top level. Protected names are assembled here so this file never spells one
whole.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)

_PROTECTED = "." + "vault" + "-pass"
_PREFIX = _PROTECTED[:-2]  # a truncation that globs to the protected name
_REGEX = '"^(src|tests)/.*:[0-9]+|StopIteration"'


@pytest.fixture(autouse=True)
def _daemon_like_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    reset_data_layer()
    monkeypatch.chdir("/")
    yield
    reset_data_layer()


def _decision(command: str, cwd: Path) -> Decision:
    chain = HandlerChain()
    chain.add(SecretFileGuardHandler())
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    decision: Decision = chain.execute(hook_input, strict_mode=False).result.decision
    return decision


class TestGrepPatternInsideBashC:
    @pytest.mark.parametrize(
        "program",
        [
            f"set -o pipefail; cat README.md | grep -a -E {_REGEX} | wc -l",
            f"grep -a -E {_REGEX} README.md",
            'grep -e "/.*:[0-9]+" -e "src/.*\\.py" README.md',
            'cat README.md | grep -E "/.*:[0-9]+"',
            'rg -n "^(src|tests)/.*:[0-9]+" README.md',
        ],
    )
    def test_a_grep_pattern_in_a_single_quoted_program_is_allowed(
        self, program: str, tmp_path: Path
    ) -> None:
        for shell in ("bash", "sh", "/bin/bash"):
            assert _decision(f"{shell} -c '{program}'", tmp_path) is Decision.ALLOW, shell

    def test_a_login_cluster_is_read_like_a_plain_dash_c(self, tmp_path: Path) -> None:
        command = f"bash -lc 'grep -E {_REGEX} README.md'"
        assert _decision(command, tmp_path) is Decision.ALLOW

    @pytest.mark.parametrize(
        "program",
        [
            f"grep x {_PROTECTED}",
            f"cat {_PREFIX}*",
            f"grep -E {_REGEX} {_PREFIX}*",
            f'grep -E "x" {_PROTECTED}',
            f"echo hi; cat {_PROTECTED}",
            f"ls {_PREFIX}*",
        ],
    )
    def test_a_reader_of_a_protected_path_in_the_program_stays_denied(
        self, program: str, tmp_path: Path
    ) -> None:
        assert _decision(f"bash -c '{program}'", tmp_path) is Decision.DENY, program

    def test_a_double_quoted_program_is_not_relaxed(self, tmp_path: Path) -> None:
        # Escapes and expansions make a double-quoted program's text differ from
        # the words it runs, so only a single-quoted program is read.
        assert _decision(f'bash -c "cat {_PREFIX}*"', tmp_path) is Decision.DENY

    def test_a_grep_pattern_in_a_program_that_is_not_a_shell_is_still_judged(
        self, tmp_path: Path
    ) -> None:
        # `python -c` and friends run the text as another language: not relaxed.
        command = f"python3 -c 'grep -E {_REGEX} README.md'"
        assert _decision(command, tmp_path) is Decision.DENY
