"""Bash-route glob operands, double-quoted one-liners and grep pattern text.

Ledger 00474 N220 (a bare ``*`` last component is expanded), N249 (a
double-quoted ``python3 -c`` body with escaped inner quotes is decoded the way
bash would) and N124 (the positional grep/rg pattern is text, not a path).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Assembled so this file never spells a protected name itself.
_NAME = "." + "vault" + "-" + "pass"
_SUFFIX = "sec" + "ret"
_PROTECTED = f"dir/key.{_SUFFIX}"


def _reindex(root: Path) -> None:
    """Serve the guard the protected-file index of ``root`` as it is now."""
    index_project(root, SecretFileGuardHandler()._patterns())


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project root holding a protected file under ``dir`` and plain files elsewhere."""
    root = tmp_path / "project"
    (root / "dir").mkdir(parents=True)
    (root / _PROTECTED).write_bytes(b"not-a-real-secret\n")
    (root / "dir" / "plain.txt").write_bytes(b"hello\n")
    (root / "safe").mkdir()
    (root / "safe" / "plain.txt").write_bytes(b"hello\n")
    (root / "f").write_bytes(b"text\n")
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        _reindex(root)
        yield root
    protected_file_index.reset_index_cache()


def _verdict(root: Path, command: str) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestBareStarLastComponent:
    """N220."""

    @pytest.mark.parametrize(
        "command",
        ["cat dir/*", "grep x dir/*", "ls dir/*", "cat dir/k*"],
    )
    def test_glob_over_a_directory_holding_a_protected_file_is_denied(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) == Decision.DENY

    def test_glob_over_a_directory_without_a_protected_file_is_allowed(self, project: Path) -> None:
        assert _verdict(project, "cat safe/*") == Decision.ALLOW

    def test_a_quoted_star_is_a_literal_and_is_allowed(self, project: Path) -> None:
        assert _verdict(project, "cat 'dir/*'") == Decision.ALLOW

    @pytest.mark.parametrize("command", ["ls */*", "cat */*", "ls */*/*", "ls **/*"])
    def test_wildcards_alone_name_no_place_and_are_allowed(
        self, project: Path, command: str
    ) -> None:
        """An ordinary listing is not a read of a protected file it happens to reach."""
        assert _verdict(project, command) == Decision.ALLOW

    def test_a_real_finding_names_the_bash_rule(self, project: Path) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat dir/*"},
            "cwd": str(project),
        }
        result = SecretFileGuardHandler().handle(hook_input)
        assert result.reason is not None
        assert RuleID.SECRET_BASH_MENTION in result.reason


def _deny_reason(root: Path, command: str) -> str:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }
    handler = SecretFileGuardHandler()
    assert handler.matches(hook_input), command
    result = handler.handle(hook_input)
    assert result.decision == Decision.DENY, command
    return result.reason or ""


class TestBareStarFollowsBashRules:
    """N220 review round 1: the expansion and its cap read the way bash reads the glob."""

    def test_star_does_not_reach_a_protected_dot_entry(self, project: Path) -> None:
        (project / "safe" / _NAME).write_bytes(b"x\n")
        _reindex(project)
        assert _verdict(project, "cat safe/*") == Decision.ALLOW

    def test_dot_led_component_reaches_dot_entries(self, project: Path) -> None:
        (project / "safe" / _NAME).write_bytes(b"x\n")
        _reindex(project)
        assert _verdict(project, "cat safe/.*") == Decision.DENY


class TestDoubleQuotedOneLiner:
    """N249."""

    def test_escaped_inner_quotes_deny(self, project: Path) -> None:
        command = f'python3 -c "print(open(\\"{_PROTECTED}\\").read())"'
        assert _verdict(project, command) == Decision.DENY

    def test_single_quoted_spelling_denies(self, project: Path) -> None:
        command = f"python3 -c 'print(open(\"{_PROTECTED}\").read())'"
        assert _verdict(project, command) == Decision.DENY

    def test_env_prefixed_escaped_inner_quotes_deny(self, project: Path) -> None:
        command = f'env python3 -c "print(open(\\"{_PROTECTED}\\").read())"'
        assert _verdict(project, command) == Decision.DENY

    def test_innocent_escaped_one_liner_is_allowed(self, project: Path) -> None:
        command = 'python3 -c "print(open(\\"f\\").read())"'
        assert _verdict(project, command) == Decision.ALLOW


class TestPositionalGrepPatternIsText:
    """N124 residual."""

    @pytest.mark.parametrize(
        "command",
        [
            f"grep -n 'foo\\.{_SUFFIX}' f",
            f"grep -n 'a\\|{_NAME}' f",
            f"rg 'a|\\{_NAME}' f",
        ],
    )
    def test_pattern_operand_is_not_a_path(self, project: Path, command: str) -> None:
        assert _verdict(project, command) == Decision.ALLOW

    def test_ansi_c_pattern_is_not_relaxed(self, project: Path) -> None:
        assert _verdict(project, f"grep $'\\x6bey.{_SUFFIX}' f") == Decision.DENY

    def test_unknown_rg_option_voids_the_relaxation(self, project: Path) -> None:
        assert _verdict(project, f"rg --hidden 'a\\|{_NAME}' f") == Decision.DENY

    def test_single_quote_blanking_leaves_ansi_c_and_double_quotes_alone(self) -> None:
        assert sfm._without_single_quoted_content("grep 'a|b' f") == "grep '   ' f"
        assert sfm._without_single_quoted_content("grep $'a|b' f") == "grep $'a|b' f"
        assert sfm._without_single_quoted_content('grep "\'a|b" f') == 'grep "\'a|b" f'

    def test_file_operand_after_the_pattern_stays_a_path(self, project: Path) -> None:
        assert _verdict(project, f"grep -n 'x' {_PROTECTED}") == Decision.DENY

    def test_file_operand_is_a_path_when_pattern_comes_from_dash_e(self, project: Path) -> None:
        assert _verdict(project, f"grep -e x {_PROTECTED}") == Decision.DENY
