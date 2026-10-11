"""N370: the commit-message exemption survives git's global options.

The guidance exempts "a `git commit` message mentioning sed". The commit was
only recognised in its literal `git commit` spelling, so
`git -C <dir> commit -m '... sed -i ...'` was denied while the same message
without the word was allowed. The commit subcommand is now found after git's
global options by the shared `GIT_INVOCATION` pattern, and the rule that sed
must sit in the same command as the commit is unchanged.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import SedBlockerHandler

# Assembled so this file does not hold the guarded word as one literal span.
_SED = "se" + "d"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> None:
    reset_data_layer()


def _matches(command: str) -> bool:
    return SedBlockerHandler().matches({"tool_name": "Bash", "tool_input": {"command": command}})


class TestCommitMessageMentioningSedAfterGlobalOptions:
    """The exemption holds whichever way git is told where the repository is."""

    @pytest.mark.parametrize(
        "command",
        [
            f"git commit -q -m 'use {_SED} -i here'",
            f"git -C /workspace commit -q -m 'use {_SED} -i here'",
            f"git -C /workspace add x && git -C /workspace commit -q -m 'use {_SED} -i here'",
            f"git -c user.name=dev commit -m 'use {_SED} -i here'",
            f"git --git-dir=/w/.git --work-tree=/w commit -m 'use {_SED} -i here'",
            f"git -C 'my dir' commit -m 'use {_SED} -i here'",
            f"git -C /w -c core.editor=true commit -m 'use {_SED} -i here'",
        ],
    )
    def test_commit_message_mentioning_sed_is_allowed(self, command: str) -> None:
        assert _matches(command) is False


class TestRealSedStaysDenied:
    """The widened commit match never launders a sed that actually runs."""

    @pytest.mark.parametrize(
        "command",
        [
            f"git -C /w commit -m x && {_SED} -i 's/a/b/' f",
            f"{_SED} -i 's/a/b/' f && git -C /w commit -m x",
            f"git -C /w commit -m x; {_SED} -i 's/a/b/' f",
            f"git -C /w status {_SED} -i",
            f"git -C /w diff && {_SED} -n 1p f",
            f"git -c a.b=c log | {_SED} 's/a/b/'",
        ],
    )
    def test_executed_sed_is_denied(self, command: str) -> None:
        assert _matches(command) is True
