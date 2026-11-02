"""Runtime guidance names the daemon wrapper for the install mode in use (issue #147, part 2).

A client install keeps the wrapper at ``.claude/hooks-daemon/bin/hooks-daemon`` and has
no root ``bin/``; each renderer below must not emit the bare self-install spelling.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import project_context as pc
from claude_code_hooks_daemon.core.session_mode_registry import goal_loop_self_clear_instruction
from claude_code_hooks_daemon.daemon.issue_validity_cli import _claim_command
from claude_code_hooks_daemon.daemon.source_fingerprint import _restart_advice
from claude_code_hooks_daemon.docs_qa.checks.unlisted_fake_value import _remedy_vendored
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_commit_gate import (
    _rule_staged_provenance,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_provenance import (
    _rule_remote_docs_provenance,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_routing import (
    _rule_vendored_copy,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.usage_pause_tool_gate import (
    _rule as _usage_pause_tool_rule,
)

_CLIENT_WRAPPER = ".claude/hooks-daemon/bin/hooks-daemon"
_BARE = re.compile(r"(?<!\.claude/hooks-daemon/)bin/hooks-daemon")


def _set_mode(monkeypatch: pytest.MonkeyPatch, *, self_install: bool) -> None:
    """Pin ProjectContext to a known root and install mode."""
    monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
    monkeypatch.setattr(
        pc.ProjectContext, "project_root", classmethod(lambda cls: Path("/proj")), raising=False
    )
    monkeypatch.setattr(
        pc.ProjectContext,
        "self_install_mode",
        classmethod(lambda cls: self_install),
        raising=False,
    )


_RENDERERS: list[Callable[[], str]] = [
    lambda: _claim_command(7),
    goal_loop_self_clear_instruction,
    _restart_advice,
    _remedy_vendored,
    lambda: _rule_vendored_copy().verbose or "",
    lambda: _rule_remote_docs_provenance().verbose or "",
    lambda: _rule_staged_provenance().verbose or "",
    lambda: _usage_pause_tool_rule().verbose or "",
]


@pytest.mark.parametrize("render", _RENDERERS)
def test_client_install_names_client_wrapper(
    monkeypatch: pytest.MonkeyPatch, render: Callable[[], str]
) -> None:
    """A client install never sees the bare self-install wrapper path."""
    _set_mode(monkeypatch, self_install=False)
    text = render()
    assert _CLIENT_WRAPPER in text
    assert _BARE.search(text) is None


@pytest.mark.parametrize("render", _RENDERERS)
def test_self_install_names_root_wrapper(
    monkeypatch: pytest.MonkeyPatch, render: Callable[[], str]
) -> None:
    """A self-install keeps the root ``bin/hooks-daemon`` spelling."""
    _set_mode(monkeypatch, self_install=True)
    text = render()
    assert "bin/hooks-daemon" in text
    assert _CLIENT_WRAPPER not in text
