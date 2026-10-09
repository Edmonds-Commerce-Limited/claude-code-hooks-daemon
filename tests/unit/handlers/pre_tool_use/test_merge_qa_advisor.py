"""MergeQaAdvisorHandler: a merge of a work branch with no recorded green ``changed`` run.

Plan 00475 Task 4.2 (ledger 00474 N278). The handler resolves the merged ref in
a real repository, so these tests build one rather than stubbing git.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.merge_qa_advisor import (
    CHANGED_GREEN_REF_TEMPLATE,
    QA_SCRIPT,
    MergeQaAdvisorHandler,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BRANCH = "worktree-feature"
#: The branch an `isolation: worktree` agent dispatch is given.
_AGENT_BRANCH = "agent-a2c1639ebf327c0d2-c58056dc"


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=Timeout.QA_TEST_TIMEOUT,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _record_green(repo: Path, branch: str, sha: str) -> None:
    _git(repo, "update-ref", CHANGED_GREEN_REF_TEMPLATE.format(branch=branch), sha)


def _bash(command: str, cwd: Path | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


@pytest.fixture(autouse=True)
def _daemon_checkout_is_the_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the project root to this checkout, which carries the QA script."""
    monkeypatch.setattr(
        "claude_code_hooks_daemon.handlers.pre_tool_use.merge_qa_advisor."
        "ProjectContext.project_root",
        classmethod(lambda cls: _PROJECT_ROOT),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """``main`` plus a ``worktree-feature`` branch one commit ahead; ``main`` is checked out."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "base.txt")
    _git(tmp_path, "checkout", "-q", "-b", _BRANCH)
    _commit(tmp_path, "feature.txt")
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


@pytest.fixture
def head(repo: Path) -> str:
    return _git(repo, "rev-parse", f"refs/heads/{_BRANCH}")


@pytest.fixture
def handler() -> MergeQaAdvisorHandler:
    return MergeQaAdvisorHandler()


def _advice(handler: MergeQaAdvisorHandler, command: str, cwd: Path | None) -> str:
    """The advisory text, or an empty string when the handler is silent."""
    hook_input = _bash(command, cwd)
    if not handler.matches(hook_input):
        return ""
    result = handler.handle(hook_input)
    assert result.decision == Decision.ALLOW
    return "\n".join(result.context)


class TestIdentity:
    def test_is_a_non_terminal_advisory(self, handler: MergeQaAdvisorHandler) -> None:
        assert handler.handler_id == HandlerID.MERGE_QA_ADVISOR
        assert handler.priority == Priority.MERGE_QA_ADVISOR
        assert handler.terminal is False
        assert HandlerTag.ADVISORY in handler.tags
        assert HandlerTag.BLOCKING not in handler.tags

    def test_the_ref_template_is_the_one_llm_qa_writes(self) -> None:
        """The script cannot be imported by the daemon, so the two spellings are pinned here."""
        path = _PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"
        spec = importlib.util.spec_from_file_location("llm_qa_for_merge_qa_advisor", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        assert module.changed_green_ref("worktree-x") == CHANGED_GREEN_REF_TEMPLATE.format(
            branch="worktree-x"
        )


class TestAdvises:
    def test_a_work_branch_with_no_record_is_named_with_its_head(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        text = _advice(handler, f"git merge --no-ff {_BRANCH}", repo)
        assert head[:12] in text
        assert _BRANCH in text
        assert "llm_qa.py changed" in text
        for command in ("ruff check", "black --check", "mypy", "audit_error_hiding.py"):
            assert command in text

    def test_the_post_merge_run_names_the_range_from_the_pre_merge_head(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        """Ledger 00474 N380: a bare `changed` on the clean merged head selects nothing."""
        pre_merge = _git(repo, "rev-parse", "HEAD")
        text = _advice(handler, f"git merge --no-ff {_BRANCH}", repo)
        assert f"llm_qa.py changed --range {pre_merge[:12]}..HEAD" in text

    def test_an_agent_dispatch_branch_is_a_work_branch(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        """Ledger 00474 N379: two agent branches were merged with no advice at all."""
        _git(repo, "branch", _AGENT_BRANCH, _BRANCH)
        text = _advice(handler, f"git merge --no-ff {_AGENT_BRANCH}", repo)
        assert head[:12] in text
        assert _AGENT_BRANCH in text

    def test_a_remote_tracking_agent_branch_is_judged(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        _git(repo, "update-ref", f"refs/remotes/origin/{_AGENT_BRANCH}", head)
        assert head[:12] in _advice(handler, f"git merge origin/{_AGENT_BRANCH}", repo)

    def test_a_record_for_an_older_head_is_stale(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        older = _git(repo, "rev-parse", f"{head}~1")
        _record_green(repo, _BRANCH, older)
        assert head[:12] in _advice(handler, f"git merge {_BRANCH}", repo)

    def test_a_record_for_another_branch_does_not_count(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        _record_green(repo, "worktree-other", head)
        assert head[:12] in _advice(handler, f"git merge {_BRANCH}", repo)

    def test_a_remote_tracking_work_branch_is_judged(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        _git(repo, "update-ref", f"refs/remotes/origin/{_BRANCH}", head)
        _git(repo, "branch", "-q", "-D", _BRANCH)
        text = _advice(handler, f"git merge --no-ff origin/{_BRANCH}", repo)
        assert head[:12] in text

    def test_a_remote_tracking_branch_with_a_record_is_silent(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        _git(repo, "update-ref", f"refs/remotes/origin/{_BRANCH}", head)
        _record_green(repo, _BRANCH, head)
        assert _advice(handler, f"git merge origin/{_BRANCH}", repo) == ""

    def test_the_message_value_is_not_taken_for_the_branch(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        text = _advice(handler, f'git merge --no-ff -m "merge worktree-nope" {_BRANCH}', repo)
        assert head[:12] in text
        assert "worktree-nope" not in text

    def test_a_dash_c_directory_places_the_merge(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str, tmp_path_factory: Any
    ) -> None:
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        text = _advice(handler, f"git -C {repo} merge --no-ff {_BRANCH}", elsewhere)
        assert head[:12] in text

    def test_a_leading_cd_places_the_merge(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str, tmp_path_factory: Any
    ) -> None:
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        text = _advice(handler, f"cd {repo} && git merge {_BRANCH}", elsewhere)
        assert head[:12] in text

    def test_each_unrecorded_branch_of_an_octopus_merge_is_named(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        _git(repo, "checkout", "-q", "-b", "worktree-second", "main")
        second = _commit(repo, "second.txt")
        _git(repo, "checkout", "-q", "main")
        text = _advice(handler, f"git merge {_BRANCH} worktree-second", repo)
        assert head[:12] in text
        assert second[:12] in text

    def test_only_the_unrecorded_branch_of_an_octopus_merge_is_named(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        _git(repo, "checkout", "-q", "-b", "worktree-second", "main")
        second = _commit(repo, "second.txt")
        _git(repo, "checkout", "-q", "main")
        _record_green(repo, _BRANCH, head)
        text = _advice(handler, f"git merge {_BRANCH} worktree-second", repo)
        assert second[:12] in text
        assert head[:12] not in text


class TestSilent:
    def test_a_green_record_for_the_head_is_silent(
        self, handler: MergeQaAdvisorHandler, repo: Path, head: str
    ) -> None:
        _record_green(repo, _BRANCH, head)
        assert _advice(handler, f"git merge --no-ff {_BRANCH}", repo) == ""

    def test_a_branch_that_is_not_a_work_branch(
        self, handler: MergeQaAdvisorHandler, repo: Path
    ) -> None:
        _git(repo, "branch", "feature/other", _BRANCH)
        assert _advice(handler, "git merge feature/other", repo) == ""

    def test_a_branch_whose_name_merely_contains_the_prefix(
        self, handler: MergeQaAdvisorHandler, repo: Path
    ) -> None:
        _git(repo, "branch", "not-worktree-x", _BRANCH)
        assert _advice(handler, "git merge not-worktree-x", repo) == ""

    def test_a_ref_git_cannot_resolve(self, handler: MergeQaAdvisorHandler, repo: Path) -> None:
        assert _advice(handler, "git merge worktree-missing", repo) == ""

    def test_a_directory_that_is_not_a_repository(
        self, handler: MergeQaAdvisorHandler, tmp_path_factory: Any
    ) -> None:
        bare = tmp_path_factory.mktemp("not-a-repo")
        assert _advice(handler, f"git merge {_BRANCH}", bare) == ""

    def test_a_missing_directory(self, handler: MergeQaAdvisorHandler, tmp_path: Path) -> None:
        assert _advice(handler, f"git merge {_BRANCH}", tmp_path / "gone") == ""

    def test_a_merge_naming_no_branch(self, handler: MergeQaAdvisorHandler, repo: Path) -> None:
        assert _advice(handler, "git merge", repo) == ""

    def test_a_directory_that_cannot_be_stated(
        self, handler: MergeQaAdvisorHandler, repo: Path
    ) -> None:
        assert _advice(handler, f"git -C $WHERE merge {_BRANCH}", repo) == ""

    @pytest.mark.parametrize("flag", ["--abort", "--continue", "--quit"])
    def test_a_merge_that_ends_or_resumes_one(
        self, handler: MergeQaAdvisorHandler, repo: Path, flag: str
    ) -> None:
        assert not handler.matches(_bash(f"git merge {flag}", repo))

    def test_a_git_failure_is_silent(
        self,
        handler: MergeQaAdvisorHandler,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def failing(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 127, "", "git is unavailable")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.merge_qa_advisor.run_git", failing
        )
        assert _advice(handler, f"git merge {_BRANCH}", repo) == ""


class TestOnlyInAProjectThatHasTheQaScript:
    """The advice names this repo's scripts, so a client project without them hears nothing."""

    def test_silent_when_the_project_has_no_qa_script(
        self,
        handler: MergeQaAdvisorHandler,
        repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client_root = tmp_path_factory.mktemp("client")
        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.merge_qa_advisor."
            "ProjectContext.project_root",
            classmethod(lambda cls: client_root),
        )
        assert _advice(handler, f"git merge {_BRANCH}", repo) == ""

    def test_advises_when_the_project_has_the_qa_script(
        self,
        handler: MergeQaAdvisorHandler,
        repo: Path,
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = tmp_path_factory.mktemp("daemon_checkout")
        script = root / QA_SCRIPT
        script.parent.mkdir(parents=True)
        script.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.merge_qa_advisor."
            "ProjectContext.project_root",
            classmethod(lambda cls: root),
        )
        assert _BRANCH in _advice(handler, f"git merge {_BRANCH}", repo)

    def test_matching_needs_no_project_context(
        self, handler: MergeQaAdvisorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``matches`` reads only the command; the project is consulted in ``handle``."""

        def _uninitialised(cls: object) -> Path:
            raise RuntimeError("ProjectContext not initialized")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.merge_qa_advisor."
            "ProjectContext.project_root",
            classmethod(_uninitialised),
        )
        assert handler.matches(_bash(f"git merge {_BRANCH}", None))


class TestDoesNotMatch:
    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            f"git merge-base main {_BRANCH}",
            f'echo "git merge {_BRANCH}"',
            f"git log {_BRANCH}",
            f"gh pr merge --merge {_BRANCH}",
        ],
    )
    def test_commands_that_are_not_a_merge(
        self, handler: MergeQaAdvisorHandler, command: str
    ) -> None:
        assert not handler.matches(_bash(command, None))

    def test_a_tool_that_is_not_bash(self, handler: MergeQaAdvisorHandler) -> None:
        assert not handler.matches({"tool_name": "Read", "tool_input": {"file_path": "/x"}})

    def test_an_empty_command(self, handler: MergeQaAdvisorHandler) -> None:
        assert not handler.matches(_bash("", None))
