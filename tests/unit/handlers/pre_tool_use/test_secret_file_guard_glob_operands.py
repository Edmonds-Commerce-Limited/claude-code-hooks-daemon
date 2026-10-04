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

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Assembled so this file never spells a protected name itself.
_NAME = "." + "vault" + "-" + "pass"
_SUFFIX = "sec" + "ret"
_PROTECTED = f"dir/key.{_SUFFIX}"


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
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        yield root


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
        ["cat dir/*", "grep x dir/*", "ls dir/*", "cat */*", "cat dir/k*"],
    )
    def test_glob_over_a_directory_holding_a_protected_file_is_denied(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) == Decision.DENY

    def test_glob_over_a_directory_without_a_protected_file_is_allowed(self, project: Path) -> None:
        assert _verdict(project, "cat safe/*") == Decision.ALLOW

    def test_expansion_past_the_cap_fails_closed(self, project: Path) -> None:
        for number in range(3):
            (project / "safe" / f"more{number}.txt").write_bytes(b"x\n")
        with patch.object(sfm, "_MAX_BARE_GLOB_FS_EXPANSIONS", 2):
            assert _verdict(project, "cat safe/*") == Decision.DENY

    def test_a_quoted_star_is_a_literal_and_is_allowed(self, project: Path) -> None:
        assert _verdict(project, "cat 'dir/*'") == Decision.ALLOW


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


class TestAScanThatRanOutOfBudgetIsNotAFinding:
    """Ledger 00474 N348: failing closed past a cap must not read as 'mentions a protected path'."""

    def test_a_cap_overflow_is_denied_under_its_own_rule(self, project: Path) -> None:
        for number in range(3):
            (project / "safe" / f"more{number}.txt").write_bytes(b"x\n")
        with patch.object(sfm, "_MAX_BARE_GLOB_FS_EXPANSIONS", 2):
            reason = _deny_reason(project, "cat safe/*")
        assert RuleID.SECRET_SCAN_INCOMPLETE in reason
        assert RuleID.SECRET_BASH_MENTION not in reason
        assert RuleID.SECRET_READ not in reason
        assert RuleID.SECRET_EVALUATION_ERROR not in reason

    def test_a_cap_overflow_says_what_ran_out_that_nothing_was_found_and_to_narrow(
        self, project: Path
    ) -> None:
        for number in range(3):
            (project / "safe" / f"more{number}.txt").write_bytes(b"x\n")
        with patch.object(sfm, "_MAX_BARE_GLOB_FS_EXPANSIONS", 2):
            reason = _deny_reason(project, "cat safe/*")
        assert "2 examined paths" in reason
        assert "no protected path was found" in reason
        assert "narrow the glob" in reason

    def test_a_deadline_is_denied_under_its_own_rule_and_says_to_retry(
        self, project: Path
    ) -> None:
        with patch.object(sfm, "find_protected_mention_detail", side_effect=TimeoutError("late")):
            reason = _deny_reason(project, "cat safe/*")
        assert RuleID.SECRET_SCAN_INCOMPLETE in reason
        assert RuleID.SECRET_EVALUATION_ERROR not in reason
        assert f"{sfm.SCAN_DEADLINE_SECONDS:g} s" in reason
        assert "no protected path was found" in reason
        assert "retry" in reason.lower()

    def test_a_cap_with_no_stated_limit_still_names_a_cap(self, project: Path) -> None:
        error = sfm.shell_expansion.TooManyToEnumerateError("too many")
        with patch.object(sfm, "find_protected_mention_detail", side_effect=error):
            reason = _deny_reason(project, "cat safe/*")
        assert RuleID.SECRET_SCAN_INCOMPLETE in reason
        assert "cap" in reason

    def test_the_reason_never_echoes_the_exception_text(self, project: Path) -> None:
        error = sfm.shell_expansion.TooManyToEnumerateError("walked into /hidden/discovered-name")
        with patch.object(sfm, "find_protected_mention_detail", side_effect=error):
            reason = _deny_reason(project, "cat safe/*")
        assert "discovered-name" not in reason

    def test_a_real_finding_keeps_its_own_rule(self, project: Path) -> None:
        reason = _deny_reason(project, "cat dir/*")
        assert RuleID.SECRET_BASH_MENTION in reason
        assert RuleID.SECRET_SCAN_INCOMPLETE not in reason

    def test_the_new_rule_is_declared_by_the_handler(self) -> None:
        rule_ids = [rule.rule_id for rule in SecretFileGuardHandler().get_rules()]
        assert RuleID.SECRET_SCAN_INCOMPLETE in rule_ids


class TestBareStarFollowsBashRules:
    """N220 review round 1: the expansion and its cap read the way bash reads the glob."""

    def test_dot_entries_do_not_count_towards_the_cap(self, project: Path) -> None:
        # `safe/*` yields plain.txt and extra.txt in bash; the five dot-entries are skipped.
        (project / "safe" / "extra.txt").write_bytes(b"x\n")
        for number in range(5):
            (project / "safe" / f".hidden{number}").write_bytes(b"x\n")
        with patch.object(sfm, "_MAX_BARE_GLOB_FS_EXPANSIONS", 3):
            assert _verdict(project, "cat safe/*") == Decision.ALLOW

    def test_star_does_not_reach_a_protected_dot_entry(self, project: Path) -> None:
        (project / "safe" / _NAME).write_bytes(b"x\n")
        assert _verdict(project, "cat safe/*") == Decision.ALLOW

    def test_dot_led_component_reaches_dot_entries(self, project: Path) -> None:
        (project / "safe" / _NAME).write_bytes(b"x\n")
        assert _verdict(project, "cat safe/.*") == Decision.DENY

    def test_dot_directory_is_not_descended_by_a_star_component(self, project: Path) -> None:
        (project / ".hid").mkdir()
        for number in range(5):
            (project / ".hid" / f"n{number}").write_bytes(b"x\n")
        (project / _PROTECTED).unlink()
        # bash yields dir/plain.txt and safe/plain.txt only.
        with patch.object(sfm, "_MAX_BARE_GLOB_FS_EXPANSIONS", 2):
            assert _verdict(project, "ls */*") == Decision.ALLOW

    def test_project_root_is_walked_once_across_working_directories(self, project: Path) -> None:
        walked: list[str] = []
        original = sfm.shell_expansion.bounded_recursive_glob

        def recording(base: Path, pattern: str, **kwargs: Any) -> Any:
            walked.append(str(base))
            return original(base, pattern, **kwargs)

        sub = str(project / "safe")
        with patch.object(sfm.shell_expansion, "bounded_recursive_glob", recording):
            sfm._bare_glob_mention(["*"], (), str(project), (str(project), sub, sub))
        assert sorted(walked) == sorted([str(project), sub])

    def test_a_walk_over_the_cap_but_a_result_count_under_it_is_allowed(
        self, project: Path
    ) -> None:
        # Naive walk: 4 entries listed under `safe`; bash yields 2 of them.
        (project / "safe" / "extra.txt").write_bytes(b"x\n")
        (project / "safe" / ".a").write_bytes(b"x\n")
        (project / "safe" / ".b").write_bytes(b"x\n")
        with patch.object(sfm, "_MAX_BARE_GLOB_FS_EXPANSIONS", 2):
            assert _verdict(project, "cat safe/*") == Decision.ALLOW


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
