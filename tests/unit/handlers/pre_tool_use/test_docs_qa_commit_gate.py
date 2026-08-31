"""Tests for DocsQaCommitGateHandler (Plan 00284, Task 3.1e).

STAGED commit gate: on ``git commit`` Bash commands, the staged tree is
evaluated against the STAGED-stage docs QA checks. Ships warn-first
(``commit_gate_mode: warn`` renders advisory context); ``block`` denies with
the diffable TODO list. Guard rails: no-op outside the project's own repo,
graceful no-op without injected policy.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.handlers.pre_tool_use.docs_qa_commit_gate import (
    DocsQaCommitGateHandler,
    _extract_commit_message,
    _extract_commit_pathspecs,
    _tokenise,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")


def _handler(policy: DocumentationPolicy | None = None) -> DocsQaCommitGateHandler:
    handler = DocsQaCommitGateHandler()
    handler._documentation = (
        policy
        if policy is not None
        else DocumentationPolicy(enabled=True, qa=DocumentationQaPolicy(commit_gate_mode="warn"))
    )
    return handler


def _bash_input(command: str, cwd: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        hook_input["cwd"] = cwd
    return hook_input


def _patched_root(root: Path) -> Any:
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.docs_qa_commit_gate."
        "ProjectContext.project_root"
    )
    return patch(target, return_value=root)


class TestTokeniserHelpers:
    def test_tokenise_unparseable_command_returns_empty_list(self) -> None:
        assert _tokenise("git commit -m 'unterminated") == []

    def test_extract_commit_message_dash_m(self) -> None:
        assert _extract_commit_message(["git", "commit", "-m", "hello"]) == "hello"

    def test_extract_commit_message_equals_form(self) -> None:
        assert _extract_commit_message(["git", "commit", "--message=hello"]) == "hello"

    def test_extract_commit_message_multiple_dash_m_joined(self) -> None:
        tokens = ["git", "commit", "-m", "title", "-m", "body"]
        assert _extract_commit_message(tokens) == "title\n\nbody"

    def test_extract_commit_message_absent_returns_none(self) -> None:
        assert _extract_commit_message(["git", "commit"]) is None

    def test_extract_commit_pathspecs_no_commit_token_returns_empty(self) -> None:
        assert _extract_commit_pathspecs(["git", "status"]) == []

    def test_extract_commit_pathspecs_skips_value_flags(self) -> None:
        tokens = ["git", "commit", "-m", "msg", "CLAUDE/A.md"]
        assert _extract_commit_pathspecs(tokens) == ["CLAUDE/A.md"]

    def test_extract_commit_pathspecs_after_separator(self) -> None:
        tokens = ["git", "commit", "--", "CLAUDE/A.md"]
        assert _extract_commit_pathspecs(tokens) == ["CLAUDE/A.md"]

    def test_extract_commit_pathspecs_boolean_flag_skipped(self) -> None:
        tokens = ["git", "commit", "--amend", "CLAUDE/A.md"]
        assert _extract_commit_pathspecs(tokens) == ["CLAUDE/A.md"]


class TestInit:
    def test_identity(self) -> None:
        handler = DocsQaCommitGateHandler()
        assert handler.name == "docs-qa-commit-gate"
        assert handler.terminal is False
        assert "documentation" in handler.tags


class TestMatches:
    def test_matches_git_commit(self, tmp_path: Path) -> None:
        assert _handler().matches(_bash_input("git commit -m 'x'")) is True

    def test_ignores_other_commands(self, tmp_path: Path) -> None:
        assert _handler().matches(_bash_input("git status")) is False

    def test_ignores_non_bash_tools(self, tmp_path: Path) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {}}
        assert _handler().matches(hook_input) is False

    def test_skips_without_policy(self) -> None:
        handler = DocsQaCommitGateHandler()
        assert handler.matches(_bash_input("git commit -m 'x'")) is False

    def test_skips_when_documentation_disabled(self) -> None:
        handler = _handler(DocumentationPolicy(enabled=False))
        assert handler.matches(_bash_input("git commit -m 'x'")) is False

    def test_skips_when_commit_gate_mode_off(self) -> None:
        policy = DocumentationPolicy(
            enabled=True, qa=DocumentationQaPolicy(commit_gate_mode="warn")
        )
        # commit_gate_mode has no "off" tier in DocumentationQaPolicy; the
        # handler is gated on documentation.enabled only, matching the
        # config model's Literal["warn", "block"].
        assert _handler(policy).matches(_bash_input("git commit -m 'x'")) is True


class TestHandle:
    def test_clean_commit_produces_no_context(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Foo.md").write_text("# clean\n")
        _git(root, "add", "-A")

        with _patched_root(root):
            result = _handler().handle(_bash_input("git commit -m 'x'", cwd=str(root)))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_new_broken_link_advises_in_warn_mode(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Foo.md").write_text("See [missing](Nope.md).\n")
        _git(root, "add", "-A")

        with _patched_root(root):
            result = _handler().handle(_bash_input("git commit -m 'x'", cwd=str(root)))
        assert result.decision == Decision.ALLOW
        assert any("pointer-resolves" in item for item in result.context)

    def test_new_broken_link_denies_in_block_mode(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Foo.md").write_text("See [missing](Nope.md).\n")
        _git(root, "add", "-A")
        policy = DocumentationPolicy(
            enabled=True, qa=DocumentationQaPolicy(commit_gate_mode="block")
        )

        with _patched_root(root):
            result = _handler(policy).handle(_bash_input("git commit -m 'x'", cwd=str(root)))
        assert result.decision == Decision.DENY
        assert result.reason.startswith(f"BLOCKED [{RuleID.DOCS_QA_COMMIT}]")
        assert "pointer-resolves" in (result.reason or "")

    def test_missing_cwd_is_treated_as_same_repo(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir()
        (root / "CLAUDE" / "Foo.md").write_text("# clean\n")
        _git(root, "add", "-A")

        with _patched_root(root):
            result = _handler().handle(_bash_input("git commit -m 'x'"))  # no cwd
        assert result.decision == Decision.ALLOW

    def test_foreign_repo_is_a_no_op(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        other_repo = tmp_path / "other"
        _init_repo(other_repo)

        with _patched_root(project_root):
            result = _handler().handle(_bash_input("git commit -m 'x'", cwd=str(other_repo)))
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestClaudeMdAndAcceptanceTests:
    def test_get_claude_md_returns_content(self) -> None:
        content = DocsQaCommitGateHandler().get_claude_md()
        assert content is not None
        assert "docs_qa_commit_gate" in content

    def test_get_acceptance_tests_returns_list(self) -> None:
        tests = DocsQaCommitGateHandler().get_acceptance_tests()
        assert len(tests) >= 1


class TestGetRules:
    def test_returns_one_rule(self) -> None:
        rules = DocsQaCommitGateHandler().get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self) -> None:
        assert DocsQaCommitGateHandler().get_rules()[0].rule_id == RuleID.DOCS_QA_COMMIT

    def test_rule_has_non_empty_verbose(self) -> None:
        assert DocsQaCommitGateHandler().get_rules()[0].verbose


class TestBlockModeDisclosureLadder:
    """Verbose-first/terse-after teaching prose; findings stay fully present always."""

    def _repo_with_broken_link(self, tmp_path: Path, name: str) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        (root / "CLAUDE").mkdir(exist_ok=True)
        (root / "CLAUDE" / name).write_text("See [missing](Nope.md).\n")
        _git(root, "add", "-A")
        return root

    def _deny(self, root: Path, transcript_path: str) -> Any:
        policy = DocumentationPolicy(
            enabled=True, qa=DocumentationQaPolicy(commit_gate_mode="block")
        )
        hook_input = _bash_input("git commit -m 'x'", cwd=str(root))
        hook_input["transcript_path"] = transcript_path
        with _patched_root(root):
            return _handler(policy).handle(hook_input)

    def test_first_fire_for_agent_is_verbose(self, tmp_path: Path) -> None:
        root = self._repo_with_broken_link(tmp_path, "Foo.md")
        result = self._deny(root, "/tmp/agent-a/transcript.jsonl")
        assert "STAGED tree" in result.reason

    def test_second_fire_is_terse_but_findings_stay_full(self, tmp_path: Path) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        root1 = self._repo_with_broken_link(tmp_path / "one", "Foo.md")
        self._deny(root1, transcript_path)

        root2 = self._repo_with_broken_link(tmp_path / "two", "Bar.md")
        result = self._deny(root2, transcript_path)

        assert "STAGED tree" not in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.DOCS_QA_COMMIT}]")
        assert "Fix:" in result.reason
        assert "pointer-resolves" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(self, tmp_path: Path) -> None:
        root = self._repo_with_broken_link(tmp_path, "Foo.md")
        policy = DocumentationPolicy(
            enabled=True, qa=DocumentationQaPolicy(commit_gate_mode="block")
        )
        hook_input = _bash_input("git commit -m 'x'", cwd=str(root))
        with _patched_root(root):
            first = _handler(policy).handle(hook_input)
            second = _handler(policy).handle(hook_input)

        assert "STAGED tree" in first.reason
        assert "STAGED tree" in second.reason
