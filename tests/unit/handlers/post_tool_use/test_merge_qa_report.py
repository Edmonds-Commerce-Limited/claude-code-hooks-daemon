"""Tests for MergeQaReportHandler (Plan 00373 Phase 3).

`plan_qa_commit_gate`, `docs_qa_commit_gate` and `staged_lint_gate` all key on
a `git commit` Bash command. A `git merge`/`git pull`/`git rebase` creates a
commit WITHOUT ever invoking `git commit`, so none of the three commit-stage
gates ever sees it -- the defect that let merge `a85e00e8` resurrect an
archived plan folder with no `PLAN.md` unreported through a full QA run, a
green CI run and a release-slate check. This handler is the post-hoc backstop:
it reads `git diff --name-only ORIG_HEAD HEAD` to see what the operation
actually introduced and reports only the plan-QA/docs-QA findings
attributable to that change set -- silent otherwise, so it does not repeat
every pre-existing finding on every merge.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import PlanWorkflowQaConfig
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.handlers.post_tool_use.merge_qa_report import (
    MergeQaReportHandler,
)

_PLAN_DIR_REL = "CLAUDE/Plan"
_MODULE = "claude_code_hooks_daemon.handlers.post_tool_use.merge_qa_report"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _bash(command: str, cwd: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        hook_input["cwd"] = cwd
    return hook_input


def _patched_root(root: Path) -> Any:
    return patch(f"{_MODULE}.ProjectContext.project_root", return_value=root)


def _patched_untracked(untracked: Path) -> Any:
    return patch(f"{_MODULE}.ProjectContext.daemon_untracked_dir", return_value=untracked)


def _handler(
    plan_dir_rel: str | None = _PLAN_DIR_REL,
    plan_policy: PlanWorkflowQaConfig | None = None,
    docs_policy: DocumentationPolicy | None = None,
) -> MergeQaReportHandler:
    handler = MergeQaReportHandler()
    handler._track_plans_in_project = plan_dir_rel
    handler._plan_qa = plan_policy if plan_policy is not None else PlanWorkflowQaConfig()
    handler._documentation = (
        docs_policy if docs_policy is not None else DocumentationPolicy(enabled=False)
    )
    return handler


def _init_git_identity(root: Path) -> None:
    # `-b main`: the test-session git config isolation fixture (conftest.py)
    # points GIT_CONFIG_GLOBAL at an empty file, so `init.defaultBranch` is
    # unset here and git's built-in default ("master") would apply instead.
    # Every scenario below checks out "main" by name, so it must exist.
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")


def _scaffold_plan_repo(tmp_path: Path) -> Path:
    """A plan tree with one clean, indexed plan folder, committed to `main`."""
    root = tmp_path / "repo"
    plan_dir = root / _PLAN_DIR_REL
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "Cancelled").mkdir()
    folder = plan_dir / "00001-first"
    folder.mkdir()
    (folder / "PLAN.md").write_text(
        "# Plan 00001: first\n\n**Status**: In Progress\n\n- [ ] ⬜ **Task 1.1**: x\n"
    )
    (folder / "JOURNAL").mkdir()
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n"
        "- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    _init_git_identity(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _scaffold_docs_repo(tmp_path: Path) -> Path:
    """A minimal doc corpus with one clean file, committed to `main`."""
    root = tmp_path / "repo"
    (root / "CLAUDE").mkdir(parents=True)
    (root / "CLAUDE" / "X.md").write_text("# clean\n")
    _init_git_identity(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class TestInitialisation:
    def test_identity_and_priority(self) -> None:
        handler = MergeQaReportHandler()
        assert handler.handler_id == HandlerID.MERGE_QA_REPORT
        assert handler.priority == Priority.MERGE_QA_REPORT

    def test_is_not_terminal(self) -> None:
        assert MergeQaReportHandler().terminal is False

    def test_tags_include_planning_and_documentation(self) -> None:
        tags = MergeQaReportHandler().tags
        assert "planning" in tags
        assert "documentation" in tags
        assert "advisory" in tags
        assert "git" in tags


class TestMatches:
    def test_ignores_non_bash_tools(self) -> None:
        handler = _handler()
        assert handler.matches({"tool_name": "Write", "tool_input": {"file_path": "/x"}}) is False

    def test_matches_git_merge(self) -> None:
        assert _handler().matches(_bash("git merge --no-ff feature")) is True

    def test_matches_git_pull(self) -> None:
        assert _handler().matches(_bash("git pull origin main")) is True

    def test_matches_git_rebase(self) -> None:
        assert _handler().matches(_bash("git rebase main")) is True

    def test_matches_with_global_options(self) -> None:
        """`git -C /path merge` read "/path" as the subcommand and walked past
        an earlier guard in this codebase -- GIT_INVOCATION exists for it."""
        assert _handler().matches(_bash("git -C /srv/project merge feature")) is True

    def test_matches_env_prefixed(self) -> None:
        assert _handler().matches(_bash("env git merge feature")) is True

    def test_matches_line_continued(self) -> None:
        assert _handler().matches(_bash("git \\\n  merge feature")) is True

    def test_matches_after_a_chained_command(self) -> None:
        assert _handler().matches(_bash("npm run build && git merge feature")) is True

    def test_does_not_match_git_commit(self) -> None:
        assert _handler().matches(_bash('git commit -m "x"')) is False

    def test_does_not_match_git_status(self) -> None:
        assert _handler().matches(_bash("git status")) is False

    def test_does_not_match_git_push(self) -> None:
        assert _handler().matches(_bash("git push")) is False

    def test_does_not_match_empty_command(self) -> None:
        assert _handler().matches(_bash("")) is False

    def test_skips_when_neither_corpus_is_active(self) -> None:
        handler = _handler(
            plan_dir_rel=None,
            plan_policy=PlanWorkflowQaConfig(enabled=False),
            docs_policy=DocumentationPolicy(enabled=False),
        )
        assert handler.matches(_bash("git merge feature")) is False

    def test_skips_when_plan_sweep_mode_off(self) -> None:
        handler = _handler(plan_policy=PlanWorkflowQaConfig(sweep_mode="off"))
        assert handler.matches(_bash("git merge feature")) is False

    def test_active_when_only_docs_corpus_is_enabled(self) -> None:
        handler = _handler(
            plan_dir_rel=None,
            plan_policy=PlanWorkflowQaConfig(enabled=False),
            docs_policy=DocumentationPolicy(enabled=True),
        )
        assert handler.matches(_bash("git merge feature")) is True


class TestSilentWhenNothingMoved:
    def test_no_orig_head_is_silent(self, tmp_path: Path) -> None:
        root = _scaffold_plan_repo(tmp_path)
        with _patched_root(root):
            result = _handler().handle(_bash("git merge --no-ff feature"))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_orig_head_equal_to_head_is_silent(self, tmp_path: Path) -> None:
        root = _scaffold_plan_repo(tmp_path)
        _git(root, "update-ref", "ORIG_HEAD", "HEAD")
        with _patched_root(root):
            result = _handler().handle(_bash("git pull"))
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestForeignRepoExempt:
    def test_a_merge_inside_a_foreign_repo_is_ignored(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        _init_git_identity(foreign)
        (foreign / "f.txt").write_text("x\n")
        _git(foreign, "add", "-A")
        _git(foreign, "commit", "-m", "seed")

        with _patched_root(project_root):
            result = _handler().handle(_bash("git merge feature", cwd=str(foreign)))

        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestPlanAttribution:
    """Replays the Plan 00373 scenario: a merge resurrects an unindexed folder."""

    def test_merge_introducing_an_unindexed_plan_folder_is_reported(self, tmp_path: Path) -> None:
        root = _scaffold_plan_repo(tmp_path)
        _git(root, "checkout", "-b", "feature")
        rogue = root / _PLAN_DIR_REL / "00372-worktree-reap-two-defects"
        (rogue / "subagent-reports").mkdir(parents=True)
        (rogue / "subagent-reports" / "report.md").write_text("build report\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "feature: resurrect orphaned report")
        _git(root, "checkout", "main")
        _git(root, "merge", "--no-ff", "feature", "-m", "merge feature")

        with _patched_root(root):
            result = _handler().handle(_bash("git merge --no-ff feature"))

        assert result.decision == Decision.ALLOW
        assert result.context
        rendered = "\n".join(result.context)
        assert "MERGE QA REPORT" in rendered
        assert "00372-worktree-reap-two-defects" in rendered
        assert "plan-qa --sweep" in rendered

    def test_unrelated_pre_existing_drift_stays_unreported(self, tmp_path: Path) -> None:
        root = _scaffold_plan_repo(tmp_path)
        stale = root / _PLAN_DIR_REL / "00003-stale"
        stale.mkdir()
        (stale / "PLAN.md").write_text("# Plan 00003: stale\n\n**Status**: In Progress\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "seed pre-existing drift")

        _git(root, "checkout", "-b", "feature")
        (root / "unrelated.txt").write_text("hello\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "unrelated change")
        _git(root, "checkout", "main")
        _git(root, "merge", "--no-ff", "feature", "-m", "merge feature")

        with _patched_root(root):
            result = _handler().handle(_bash("git merge --no-ff feature"))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_missing_plan_dir_does_not_crash(self, tmp_path: Path) -> None:
        root = tmp_path / "bare"
        root.mkdir()
        _init_git_identity(root)
        (root / "f.txt").write_text("x\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "seed")
        _git(root, "checkout", "-b", "feature")
        (root / "f.txt").write_text("y\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "feature")
        _git(root, "checkout", "main")
        _git(root, "merge", "--no-ff", "feature", "-m", "merge feature")

        with _patched_root(root):
            result = _handler().handle(_bash("git merge --no-ff feature"))

        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestDocsAttribution:
    def test_merge_introducing_a_dead_link_is_reported(self, tmp_path: Path) -> None:
        root = _scaffold_docs_repo(tmp_path)
        _git(root, "checkout", "-b", "feature")
        (root / "CLAUDE" / "Y.md").write_text("See [missing](Nope.md).\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "feature: dead link")
        _git(root, "checkout", "main")
        _git(root, "merge", "--no-ff", "feature", "-m", "merge feature")

        untracked = tmp_path / "untracked"
        handler = _handler(
            plan_dir_rel=None,
            plan_policy=PlanWorkflowQaConfig(enabled=False),
            docs_policy=DocumentationPolicy(enabled=True),
        )
        with _patched_root(root), _patched_untracked(untracked):
            result = handler.handle(_bash("git merge --no-ff feature"))

        assert result.decision == Decision.ALLOW
        assert result.context
        rendered = "\n".join(result.context)
        assert "pointer-resolves" in rendered
        assert "CLAUDE/Y.md" in rendered
        assert "docs-qa --sweep" in rendered

    def test_disabled_documentation_policy_produces_no_docs_section(self, tmp_path: Path) -> None:
        root = _scaffold_docs_repo(tmp_path)
        _git(root, "checkout", "-b", "feature")
        (root / "CLAUDE" / "Y.md").write_text("See [missing](Nope.md).\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "feature: dead link")
        _git(root, "checkout", "main")
        _git(root, "merge", "--no-ff", "feature", "-m", "merge feature")

        handler = _handler(
            plan_dir_rel=None,
            plan_policy=PlanWorkflowQaConfig(enabled=False),
            docs_policy=DocumentationPolicy(enabled=False),
        )
        with _patched_root(root):
            result = handler.handle(_bash("git merge --no-ff feature"))

        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestGuidance:
    def test_get_claude_md_documents_the_handler(self) -> None:
        text = MergeQaReportHandler().get_claude_md()
        assert text is not None
        assert "merge_qa_report" in text
        assert "ORIG_HEAD" in text

    def test_acceptance_tests_defined(self) -> None:
        assert len(MergeQaReportHandler().get_acceptance_tests()) >= 1

    def test_default_enabled(self) -> None:
        assert MergeQaReportHandler().get_default_enabled() is True
