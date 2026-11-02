"""secret_file_guard names the daemon wrapper for the install mode in use (issue #147).

A client install keeps the wrapper at ``.claude/hooks-daemon/bin/hooks-daemon`` and
has no root ``bin/``; a self-install has ``bin/hooks-daemon``.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core import project_context as pc
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import RuleFormatter
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)

_CLIENT_WRAPPER = ".claude/hooks-daemon/bin/hooks-daemon"
# Built from parts so this file does not itself mention a protected glob.
_PROTECTED = "/proj/" + ".vault" + "-pass"


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


@pytest.fixture(autouse=True)
def _fresh_data_layer() -> None:
    reset_data_layer()


def _deny_reason() -> str:
    result = SecretFileGuardHandler().handle(
        {"tool_name": "Read", "tool_input": {"file_path": _PROTECTED}}
    )
    assert result.decision == Decision.DENY
    return result.reason or ""


class TestWrapperNameFollowsInstallMode:
    """Every operator-facing wrapper mention matches the install mode."""

    def test_client_install_deny_names_client_wrapper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, self_install=False)
        reason = _deny_reason()
        assert f"`{_CLIENT_WRAPPER} secret-meta <path>`" in reason
        assert f"`{_CLIENT_WRAPPER} explain-handler secret_file_guard`" in reason

    def test_self_install_deny_names_root_wrapper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_mode(monkeypatch, self_install=True)
        reason = _deny_reason()
        assert "`bin/hooks-daemon secret-meta <path>`" in reason
        assert _CLIENT_WRAPPER not in reason

    def test_client_rules_table_fix_names_client_wrapper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, self_install=False)
        for rule in SecretFileGuardHandler().get_rules():
            assert _CLIENT_WRAPPER in RuleFormatter().table_row(rule)

    def test_client_claude_md_names_client_wrapper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_mode(monkeypatch, self_install=False)
        guidance = SecretFileGuardHandler().get_claude_md() or ""
        assert f"`{_CLIENT_WRAPPER} secret-meta <path>`" in guidance
        assert "`bin/hooks-daemon secret-meta" not in guidance

    def test_acceptance_test_command_matches_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_mode(monkeypatch, self_install=False)
        commands = [t.command for t in SecretFileGuardHandler().get_acceptance_tests()]
        meta = [c for c in commands if " secret-meta " in c]
        assert len(meta) == 1
        assert meta[0].startswith(f"{_CLIENT_WRAPPER} secret-meta ")
