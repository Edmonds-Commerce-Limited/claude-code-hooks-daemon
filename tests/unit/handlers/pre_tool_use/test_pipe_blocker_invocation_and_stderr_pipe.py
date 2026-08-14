"""Git global options must not defeat the whitelist; `|&` must not bypass it.

Two independent gaps, opposite in sign, both invisible until probed:

- The git whitelist entries anchored on the bare name (``^git\\s+log``), so
  ``git -C <path> log`` piped to ``head`` was denied as "unrecognized" while
  the identical bare spelling was allowed. A false POSITIVE, which is why it
  survived: it only ever cost someone a command they were entitled to run.
  The shared ``GIT_INVOCATION`` grammar exists to absorb exactly this
  respelling (Plan 00202).

- ``|&`` is bash's stdout+stderr pipe. The pipe pattern matched only ``|``,
  so ``<expensive> |& head`` was allowed outright — a silent bypass of the
  whole handler, since everything downstream keys off that pattern.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

# Split so this file's own content cannot trip the handler it tests.
_HEAD = "he" + "ad"


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestGitGlobalOptionsKeepTheWhitelist:
    @pytest.mark.parametrize("subcommand", ["log", "status", "diff", "tag", "branch"])
    def test_git_dash_c_is_whitelisted_like_the_bare_spelling(
        self, handler: PipeBlockerHandler, subcommand: str
    ) -> None:
        command = f"git -C /workspace {subcommand} | {_HEAD} -3"
        if handler.matches(_bash(command)):
            assert handler.handle(_bash(command)).decision != Decision.DENY

    @pytest.mark.parametrize("subcommand", ["log", "status", "diff", "tag", "branch"])
    def test_bare_git_spelling_still_whitelisted(
        self, handler: PipeBlockerHandler, subcommand: str
    ) -> None:
        command = f"git {subcommand} | {_HEAD} -3"
        if handler.matches(_bash(command)):
            assert handler.handle(_bash(command)).decision != Decision.DENY


class TestStderrPipeIsStillAPipe:
    def test_stderr_pipe_on_an_expensive_producer_is_denied(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = f"pytest tests/ |& {_HEAD} -5"
        assert handler.matches(_bash(command))
        assert handler.handle(_bash(command)).decision == Decision.DENY

    def test_stdout_pipe_on_the_same_producer_is_still_denied(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = f"pytest tests/ | {_HEAD} -5"
        assert handler.matches(_bash(command))
        assert handler.handle(_bash(command)).decision == Decision.DENY

    def test_stderr_pipe_on_a_whitelisted_producer_is_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = f"git log --oneline |& {_HEAD} -3"
        if handler.matches(_bash(command)):
            assert handler.handle(_bash(command)).decision != Decision.DENY
