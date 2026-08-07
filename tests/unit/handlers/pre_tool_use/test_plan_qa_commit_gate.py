"""Tests for PlanQaCommitGateHandler (Plan 00144, Task 4.1/4.2).

Stage 2 commit gate: on ``git commit`` Bash commands, the staged tree is
evaluated against the cross-file plan QA checks. Ships warn-first
(``commit_gate_mode: warn`` renders advisory context); ``block`` denies with
the diffable TODO list. Guard rails: no-op outside the project's own repo,
graceful no-op without injected policy.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import PlanWorkflowQaConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_commit_gate import (
    PlanQaCommitGateHandler,
)

_PLAN_DIR_REL = "CLAUDE/Plan"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Git repo with one committed, indexed, in-progress plan."""
    root = tmp_path / "repo"
    plan_dir = root / _PLAN_DIR_REL
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "Cancelled").mkdir()
    folder = plan_dir / "00001-first"
    folder.mkdir()
    (folder / "PLAN.md").write_text(
        "# Plan 00001: first\n\n**Status**: In Progress\n\n- [ ] ⬜ **Task 1.1**: x\n"
    )
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n"
        "- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _handler(
    mode: str = "warn",
    policy: PlanWorkflowQaConfig | None = None,
) -> PlanQaCommitGateHandler:
    handler = PlanQaCommitGateHandler()
    handler._track_plans_in_project = _PLAN_DIR_REL
    handler._plan_qa = policy if policy is not None else PlanWorkflowQaConfig(commit_gate_mode=mode)
    return handler


def _bash_input(command: str, cwd: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if cwd is not None:
        hook_input["cwd"] = cwd
    return hook_input


def _patched_root(root: Path) -> Any:
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_commit_gate."
        "ProjectContext.project_root"
    )
    return patch(target, return_value=root)


class TestInit:
    def test_identity(self) -> None:
        handler = PlanQaCommitGateHandler()
        assert handler.name == "plan-qa-commit-gate"
        assert handler.terminal is False
        assert "planning" in handler.tags


class TestMatches:
    def test_matches_git_commit(self) -> None:
        assert _handler().matches(_bash_input('git commit -m "x"')) is True

    def test_matches_git_commit_with_flags(self) -> None:
        assert _handler().matches(_bash_input("git -C /workspace commit --amend-free -a")) is True

    def test_ignores_other_git_commands(self) -> None:
        assert _handler().matches(_bash_input("git status")) is False

    def test_ignores_non_bash_tools(self) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "/x", "content": "y"}}
        assert _handler().matches(hook_input) is False

    def test_ignores_commit_mentioned_in_other_commands(self) -> None:
        assert _handler().matches(_bash_input("echo 'git commit is fun'")) is False

    def test_skips_without_policy(self) -> None:
        handler = PlanQaCommitGateHandler()
        handler._track_plans_in_project = _PLAN_DIR_REL
        handler._plan_qa = None
        assert handler.matches(_bash_input('git commit -m "x"')) is False

    def test_skips_when_mode_off(self) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(commit_gate_mode="off"))
        assert handler.matches(_bash_input('git commit -m "x"')) is False

    def test_skips_when_qa_disabled(self) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(enabled=False))
        assert handler.matches(_bash_input('git commit -m "x"')) is False


class TestHandleWarnMode:
    def test_clean_stage_is_silent(self, repo: Path) -> None:
        with _patched_root(repo):
            result = _handler("warn").handle(_bash_input('git commit -m "docs"'))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_terminal_flip_without_move_warns(self, repo: Path) -> None:
        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        _git(repo, "add", "-A")

        with _patched_root(repo):
            result = _handler("warn").handle(_bash_input('git commit -m "Plan 00001: done"'))

        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "terminal-state-atomic" in text

    def test_commit_message_ref_check_uses_message(self, repo: Path) -> None:
        # Stage a src change; message claims Plan 00001 but no PLAN.md staged.
        (repo / "src").mkdir()
        (repo / "src" / "thing.py").write_text("VALUE = 1\n")
        _git(repo, "add", "-A")

        with _patched_root(repo):
            result = _handler("warn").handle(
                _bash_input('git commit -m "Plan 00001: implement the thing"')
            )

        assert result.decision == Decision.ALLOW
        assert "same-commit-plan-doc" in "\n".join(result.context)

    def test_pathspec_commit_sees_unstaged_plan_doc_update(self, repo: Path) -> None:
        """Plan 00200 (Task 3.5): `git commit <pathspec>` false positive.

        A `git commit <pathspec>...` form commits the WORKING TREE content
        of exactly the named paths, whether staged or not. A commit that
        names BOTH the src change AND the (unstaged) PLAN.md update must NOT
        get a same-commit-plan-doc advisory — the PLAN.md update
        demonstrably IS part of this commit.
        """
        (repo / "src").mkdir()
        (repo / "src" / "thing.py").write_text("VALUE = 1\n")
        _git(repo, "add", "src/thing.py")

        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text(
            "# Plan 00001: first\n\n**Status**: In Progress\n\n" "- [x] ✅ **Task 1.1**: x\n"
        )
        # Deliberately NOT staged — only named on the commit line.

        with _patched_root(repo):
            result = _handler("warn").handle(
                _bash_input(
                    'git commit -m "Plan 00001: implement the thing" '
                    "src/thing.py CLAUDE/Plan/00001-first/PLAN.md"
                )
            )

        assert result.decision == Decision.ALLOW
        assert "same-commit-plan-doc" not in "\n".join(result.context)

    def test_pathspec_commit_excluding_plan_doc_still_advises(self, repo: Path) -> None:
        """Guardrail: a pathspec commit that genuinely omits PLAN.md still warns."""
        (repo / "src").mkdir()
        (repo / "src" / "thing.py").write_text("VALUE = 1\n")
        _git(repo, "add", "-A")

        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: In Progress\n")
        # PLAN.md is modified but NOT named on the commit line below.

        with _patched_root(repo):
            result = _handler("warn").handle(
                _bash_input('git commit -m "Plan 00001: implement the thing" src/thing.py')
            )

        assert result.decision == Decision.ALLOW
        assert "same-commit-plan-doc" in "\n".join(result.context)


class TestHandleBlockMode:
    def test_terminal_flip_without_move_denies_with_todo(self, repo: Path) -> None:
        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        _git(repo, "add", "-A")

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -m "Plan 00001: done"'))

        assert result.decision == Decision.DENY
        assert "terminal-state-atomic" in (result.reason or "")
        assert "git mv" in (result.reason or "")

    def test_block_mode_advisories_do_not_deny(self, repo: Path) -> None:
        # Only an advisory-level finding staged (plan-ref-format: message
        # lacks the canonical Plan NNNNN form while touching the plan dir).
        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text(
            "# Plan 00001: first\n\n**Status**: In Progress\n\n- [x] ✅ **Task 1.1**: x\n"
            "\n- [ ] ⬜ **Task 1.2**: y\n"
        )
        _git(repo, "add", "-A")

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -m "tick a box"'))

        assert result.decision == Decision.ALLOW
        assert "plan-ref-format" in "\n".join(result.context)


class TestGuardRails:
    def test_noop_when_cwd_in_foreign_repo(self, repo: Path, tmp_path: Path) -> None:
        other = tmp_path / "other-repo"
        other.mkdir()
        _git(other, "init")

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -m "x"', cwd=str(other)))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_missing_plan_dir_warns_instead_of_crashing(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare-repo"
        bare.mkdir()
        _git(bare, "init")

        with _patched_root(bare):
            result = _handler("block").handle(_bash_input('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert _PLAN_DIR_REL in "\n".join(result.context)


class TestGuidance:
    def test_get_claude_md_documents_gate(self) -> None:
        text = PlanQaCommitGateHandler().get_claude_md()
        assert text is not None
        assert "commit" in text.lower()

    def test_acceptance_tests_defined(self) -> None:
        assert len(PlanQaCommitGateHandler().get_acceptance_tests()) >= 1

    def test_default_enabled(self) -> None:
        assert PlanQaCommitGateHandler().get_default_enabled() is True
