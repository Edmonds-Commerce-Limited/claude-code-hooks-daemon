"""Tests for PlanQaCommitGateHandler (Plan 00144, Task 4.1/4.2).

Stage 2 commit gate: on ``git commit`` Bash commands, the staged tree is
evaluated against the cross-file plan QA checks. Ships warn-first
(``commit_gate_mode: warn`` renders advisory context); ``block`` denies with
the diffable TODO list. Guard rails: no-op outside the project's own repo,
graceful no-op without injected policy.
"""

import subprocess
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import PlanWorkflowQaConfig
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_commit_gate import (
    PlanQaCommitGateHandler,
)

_PLAN_DIR_REL = "CLAUDE/Plan"


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
        "# Plans Index\n\n## Active Plans\n\n- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _handler(
    mode: Literal["block", "warn", "off"] = "warn",
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
            "# Plan 00001: first\n\n**Status**: In Progress\n\n- [x] ✅ **Task 1.1**: x\n"
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

    def test_the_capture_idiom_reads_the_index_not_a_redirect(self, repo: Path) -> None:
        """Ledger 00466 N226: `2>&1` was a pathspec, so an index commit was
        judged as a working-tree commit of a path that matches nothing."""
        (repo / "src").mkdir()
        (repo / "src" / "thing.py").write_text("VALUE = 1\n")
        _git(repo, "add", "-A")
        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: In Progress\n")

        with _patched_root(repo):
            result = _handler("warn").handle(
                _bash_input('git commit -m "Plan 00001: thing" 2>&1 | bin/echd-capture 20')
            )

        assert result.decision == Decision.ALLOW
        assert "same-commit-plan-doc" in "\n".join(result.context)

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
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.PLAN_QA_COMMIT}]")
        assert "terminal-state-atomic" in result.reason
        assert "git mv" in result.reason

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


def _index_with_stats(*, distinct: int, allocated: int, closing: str) -> str:
    """The fixture index plus a reconciliation bullet; the closing sum is line 11."""
    return (
        "# Plans Index\n\n## Active Plans\n\n"
        "- [00001: first](00001-first/PLAN.md) - In Progress\n\n"
        "## Plan Statistics\n\n"
        f"- **Reconciliation**: **{distinct} distinct plan numbers**. That leaves\n"
        f"  **1** of the {allocated} allocated numbers with no folder: 00002 — dropped.\n"
        f"  {closing}\n"
    )


class TestPlanStatsArithmetic:
    """Plan 00466 N13: the index's self-check line is judged at commit time.

    The check ran only in full QA, so a README whose closing self-check
    disagreed with the statistics above it was committed and pushed.
    """

    _CLOSING_LINE = 11

    def _commit_index(self, repo: Path, text: str) -> Any:
        (repo / _PLAN_DIR_REL / "README.md").write_text(text)
        _git(repo, "add", "-A")
        with _patched_root(repo):
            return _handler("block").handle(_bash_input('git commit -m "Plan 00001: index"'))

    def test_staging_a_disagreeing_index_is_denied_naming_the_line(self, repo: Path) -> None:
        result = self._commit_index(
            repo, _index_with_stats(distinct=2, allocated=4, closing="1 + 1 = 2. ✅")
        )

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "plan-stats-arithmetic" in result.reason
        assert f"line {self._CLOSING_LINE}" in result.reason

    def test_staging_a_consistent_index_is_allowed(self, repo: Path) -> None:
        result = self._commit_index(
            repo, _index_with_stats(distinct=2, allocated=3, closing="2 + 1 = 3. ✅")
        )

        assert result.decision == Decision.ALLOW
        assert "plan-stats-arithmetic" not in "\n".join(result.context)

    def test_an_inherited_disagreement_does_not_deny_an_unrelated_commit(self, repo: Path) -> None:
        """A commit that does not stage the index cannot be why it disagrees."""
        (repo / _PLAN_DIR_REL / "README.md").write_text(
            _index_with_stats(distinct=2, allocated=4, closing="1 + 1 = 2. ✅")
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "broken index, committed before the gate existed")
        (repo / "src").mkdir()
        (repo / "src" / "thing.py").write_text("VALUE = 1\n")
        _git(repo, "add", "-A")

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -m "Plan 00001: code"'))

        assert result.decision == Decision.ALLOW
        assert "plan-stats-arithmetic" in "\n".join(result.context)


class TestPathspecsAreJudgedFromEveryDirectoryTheCommitMayRunIn:
    """Ledger 00474 N299 round 2: a cd that may not take effect fails closed."""

    _PLAN_MD = f"{_PLAN_DIR_REL}/00001-first/PLAN.md"

    @pytest.fixture
    def flipped(self, repo: Path) -> Path:
        """A terminal flip left unstaged, which a pathspec commit records."""
        (repo / self._PLAN_MD).write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        return repo

    @pytest.mark.parametrize(
        "command",
        [
            'cd nosuch; git commit -m "Plan 00001: done" {plan}',
            'cd CLAUDE & git commit -m "Plan 00001: done" {plan}',
            'test -d nosuch && cd nosuch; git commit -m "Plan 00001: done" {plan}',
        ],
    )
    def test_a_cd_that_may_not_take_effect_still_judges_the_hooks_directory(
        self, flipped: Path, command: str
    ) -> None:
        with _patched_root(flipped):
            result = _handler("block").handle(
                _bash_input(command.format(plan=self._PLAN_MD), cwd=str(flipped))
            )

        assert result.decision == Decision.DENY
        assert (result.reason or "").startswith(f"BLOCKED [{RuleID.PLAN_QA_COMMIT}]")

    def test_a_cd_that_may_not_take_effect_still_judges_where_it_moves_to(
        self, flipped: Path
    ) -> None:
        plan = "Plan/00001-first/PLAN.md"
        with _patched_root(flipped):
            result = _handler("block").handle(
                _bash_input(
                    f'cd CLAUDE & git commit -m "Plan 00001: done" {plan}', cwd=str(flipped)
                )
            )

        assert result.decision == Decision.DENY

    def test_a_certain_cd_reads_only_where_it_moves_to(self, flipped: Path) -> None:
        with _patched_root(flipped):
            result = _handler("block").handle(
                _bash_input(
                    f'cd nosuch && git commit -m "Plan 00001: done" {self._PLAN_MD}',
                    cwd=str(flipped),
                )
            )

        assert result.decision == Decision.ALLOW


class TestACommandThatStagesOrCommitsMoreThanOnce:
    """Ledger 00474 N246 and N307: the plan tree judged is the one the whole command records."""

    _PLAN_MD = f"{_PLAN_DIR_REL}/00001-first/PLAN.md"

    @pytest.fixture
    def flipped(self, repo: Path) -> Path:
        """A terminal flip left unstaged: nothing records it unless the command does."""
        (repo / self._PLAN_MD).write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        return repo

    def _decision(self, root: Path, command: str) -> Decision:
        with _patched_root(root):
            return _handler("block").handle(_bash_input(command, cwd=str(root))).decision

    @pytest.mark.parametrize(
        "command",
        [
            'git add {plan} && git commit -m "Plan 00001: done"',
            'git add -A && git commit -m "Plan 00001: done"',
            'git add -u && git commit -m "Plan 00001: done"',
            'git add {plan}; git commit -m "Plan 00001: done"',
        ],
    )
    def test_a_plan_change_the_same_command_adds_is_judged(
        self, flipped: Path, command: str
    ) -> None:
        assert self._decision(flipped, command.format(plan=self._PLAN_MD)) == Decision.DENY

    def test_a_plan_change_the_add_does_not_name_is_not_judged(self, flipped: Path) -> None:
        (flipped / "notes.txt").write_text("x\n")

        command = 'git add notes.txt && git commit -m "notes"'

        assert self._decision(flipped, command) == Decision.ALLOW

    def test_the_second_commits_pathspec_is_judged(self, flipped: Path) -> None:
        (flipped / "notes.txt").write_text("x\n")
        _git(flipped, "add", "notes.txt")

        command = (
            f'git commit -m "notes" notes.txt; git commit -m "Plan 00001: done" {self._PLAN_MD}'
        )

        assert self._decision(flipped, command) == Decision.DENY

    def test_a_clean_pair_of_commits_is_allowed(self, flipped: Path) -> None:
        (flipped / "notes.txt").write_text("x\n")
        (flipped / "more.txt").write_text("y\n")
        _git(flipped, "add", "-A", "--", "notes.txt", "more.txt")

        command = 'git commit -m "notes" notes.txt; git commit -m "more" more.txt'

        assert self._decision(flipped, command) == Decision.ALLOW


class TestAJournalEntryTheCommandWritesItself:
    """Ledger 00474 N317: `mkplan.bash --journal` before the commit is the journal entry."""

    _ADVISORY = "journal-entry-with-progress"
    _MKPLAN = f'{_PLAN_DIR_REL}/mkplan.bash --journal 1 finding body.md --title "x"'

    @pytest.fixture
    def ticked(self, repo: Path) -> Path:
        """A task ticked in the working tree, with no journal entry anywhere."""
        plan = repo / _PLAN_DIR_REL / "00001-first" / "PLAN.md"
        plan.write_text(plan.read_text().replace("[ ] ⬜", "[x] ✅"))
        return repo

    def _advised(self, root: Path, command: str) -> bool:
        with _patched_root(root):
            result = _handler("warn").handle(_bash_input(command, cwd=str(root)))
        return any(self._ADVISORY in line for line in result.context)

    def test_the_bare_commit_is_advised(self, ticked: Path) -> None:
        command = f'git add {_PLAN_DIR_REL}/00001-first && git commit -m "Plan 00001: x"'

        assert self._advised(ticked, command)

    def test_mkplan_then_add_then_commit_is_not_advised(self, ticked: Path) -> None:
        command = (
            f"{self._MKPLAN} && git add {_PLAN_DIR_REL}/00001-first "
            '&& git commit -m "Plan 00001: x"'
        )

        assert not self._advised(ticked, command)

    def test_mkplan_for_a_different_plan_is_still_advised(self, ticked: Path) -> None:
        command = (
            f"{self._MKPLAN.replace('--journal 1', '--journal 2')} "
            f'&& git add {_PLAN_DIR_REL}/00001-first && git commit -m "Plan 00001: x"'
        )

        assert self._advised(ticked, command)

    def test_mkplan_without_a_covering_add_is_still_advised(self, ticked: Path) -> None:
        command = (
            f"{self._MKPLAN} && git add {_PLAN_DIR_REL}/00001-first/PLAN.md "
            '&& git commit -m "Plan 00001: x"'
        )

        assert self._advised(ticked, command)

    def test_mkplan_after_the_commit_is_still_advised(self, ticked: Path) -> None:
        command = f'git add {_PLAN_DIR_REL}/00001-first && git commit -m "Plan 00001: x" && {self._MKPLAN}'

        assert self._advised(ticked, command)


class TestGuardRails:
    def test_noop_when_cwd_in_foreign_repo(self, repo: Path, tmp_path: Path) -> None:
        other = tmp_path / "other-repo"
        other.mkdir()
        _git(other, "init")

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -m "x"', cwd=str(other)))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    @pytest.mark.parametrize(
        "form", ["cd {other} && git commit -m x", "git -C {other} commit -m x"]
    )
    def test_a_commit_moved_into_another_repo_stands_down(self, tmp_path: Path, form: str) -> None:
        """Ledger 00474 N305: where the commit runs is the cwd after any move."""
        bare = tmp_path / "bare-repo"
        bare.mkdir()
        _git(bare, "init")
        other = tmp_path / "other-repo"
        other.mkdir()
        _git(other, "init")

        with _patched_root(bare):
            result = _handler("block").handle(_bash_input(form.format(other=other), cwd=str(bare)))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_a_move_within_this_repo_is_still_judged(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare-repo"
        (bare / "sub").mkdir(parents=True)
        _git(bare, "init")

        with _patched_root(bare):
            result = _handler("block").handle(
                _bash_input("cd sub && git commit -m x", cwd=str(bare))
            )

        assert _PLAN_DIR_REL in "\n".join(result.context)

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


class TestGetRules:
    def test_returns_one_rule(self) -> None:
        rules = PlanQaCommitGateHandler().get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self) -> None:
        assert PlanQaCommitGateHandler().get_rules()[0].rule_id == RuleID.PLAN_QA_COMMIT

    def test_rule_has_non_empty_verbose(self) -> None:
        assert PlanQaCommitGateHandler().get_rules()[0].verbose


class TestBlockModeDisclosureLadder:
    """Verbose-first/terse-after teaching prose; findings stay fully present always."""

    def _flip_terminal(self, repo: Path, transcript_path: str) -> Any:
        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        _git(repo, "add", "-A")

        hook_input = _bash_input('git commit -m "Plan 00001: done"')
        hook_input["transcript_path"] = transcript_path
        with _patched_root(repo):
            return _handler("block").handle(hook_input)

    def test_first_fire_for_agent_is_verbose(self, repo: Path) -> None:
        result = self._flip_terminal(repo, "/tmp/agent-a/transcript.jsonl")
        assert "cross-file plan" in result.reason

    def test_second_fire_is_terse_but_findings_stay_full(self, repo: Path) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        self._flip_terminal(repo, transcript_path)
        result = self._flip_terminal(repo, transcript_path)

        assert "cross-file plan" not in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.PLAN_QA_COMMIT}]")
        assert "Fix:" in result.reason
        assert "terminal-state-atomic" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(self, repo: Path) -> None:
        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        _git(repo, "add", "-A")

        hook_input = _bash_input('git commit -m "Plan 00001: done"')
        with _patched_root(repo):
            first = _handler("block").handle(hook_input)
            second = _handler("block").handle(hook_input)

        assert first.reason is not None
        assert "cross-file plan" in first.reason
        assert second.reason is not None
        assert "cross-file plan" in second.reason


class TestProjectExcludePaths:
    """Plan 00362 Task 2.9: a plan under ``daemon.exclude_paths`` is not gated."""

    def test_terminal_flip_in_excluded_plan_is_silent(self, repo: Path) -> None:
        plan_md = repo / _PLAN_DIR_REL / "00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        _git(repo, "add", "-A")
        handler = _handler("block")
        handler._project_exclude_paths = ["CLAUDE/Plan/00001-first/**"]

        with _patched_root(repo):
            result = handler.handle(_bash_input('git commit -m "Plan 00001: done"'))

        assert result.decision == Decision.ALLOW
        assert result.context == []


_ROW = "- [00001: first](00001-first/PLAN.md) - In Progress\n"
_README_WITHOUT_ROW = "# Plans Index\n\n## Active Plans\n"


_README_ROW_IN_COMPLETED = (
    "# Plans Index\n\n## Active Plans\n\n## Completed Plans\n\n"
    "- [00001: first](00001-first/PLAN.md) - In Progress\n"
)


class TestCommitDashAJudgesWhatItRecords:
    """`git commit -a` records the working tree of tracked files, so a finding it
    introduces from an UNSTAGED edit blocks exactly as the same edit staged does."""

    def _edit_unstaged(self, repo: Path) -> None:
        (repo / _PLAN_DIR_REL / "README.md").write_text(_README_ROW_IN_COMPLETED)
        plan = repo / _PLAN_DIR_REL / "00001-first" / "PLAN.md"
        plan.write_text(plan.read_text() + "\nedit\n")

    def test_an_unstaged_edit_that_dash_a_records_blocks(self, repo: Path) -> None:
        self._edit_unstaged(repo)

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -a -m "Plan 00001: x"'))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "row-folder-bijection" in result.reason

    def test_the_same_edit_staged_first_blocks_too(self, repo: Path) -> None:
        self._edit_unstaged(repo)
        _git(repo, "add", "-A")

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -m "Plan 00001: x"'))

        assert result.decision == Decision.DENY

    def test_an_untracked_plan_folder_is_not_part_of_dash_a(self, repo: Path) -> None:
        folder = repo / _PLAN_DIR_REL / "00002-new"
        folder.mkdir()
        (folder / "PLAN.md").write_text("# Plan 00002: new\n\n**Status**: In Progress\n")

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -a -m "docs"'))

        assert result.decision == Decision.ALLOW


class TestJudgesTheCommittedTree:
    """Ledger 00474 N244: the gate judges the tree the commit WILL record.

    ``git rm -r --cached`` leaves the folder on disk but out of the commit, so
    a README row still linking to it dangles in the committed tree. A gate that
    scans the disk sees a folder and a row that resolves, and allows it.
    """

    def test_row_left_pointing_at_an_untracked_folder_is_denied(self, repo: Path) -> None:
        _git(repo, "rm", "-r", "--cached", "-q", f"{_PLAN_DIR_REL}/00001-first")
        assert (repo / _PLAN_DIR_REL / "00001-first" / "PLAN.md").is_file()

        with _patched_root(repo):
            result = _handler("block").handle(
                _bash_input('git commit -m "Plan 00001: untrack the plan"')
            )

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "row-folder-bijection" in result.reason

    def test_a_disk_only_row_edit_does_not_rescue_the_commit(self, repo: Path) -> None:
        _git(repo, "rm", "-r", "--cached", "-q", f"{_PLAN_DIR_REL}/00001-first")
        # The working-tree README loses the row, but that edit is not staged,
        # so the committed README still carries it.
        (repo / _PLAN_DIR_REL / "README.md").write_text(_README_WITHOUT_ROW)

        with _patched_root(repo):
            result = _handler("block").handle(
                _bash_input('git commit -m "Plan 00001: untrack the plan"')
            )

        assert result.decision == Decision.DENY

    def test_removing_the_row_in_the_same_commit_is_allowed(self, repo: Path) -> None:
        readme = repo / _PLAN_DIR_REL / "README.md"
        readme.write_text(_README_WITHOUT_ROW)
        _git(repo, "add", f"{_PLAN_DIR_REL}/README.md")
        _git(repo, "rm", "-r", "--cached", "-q", f"{_PLAN_DIR_REL}/00001-first")
        # The row is back on disk, unstaged: the committed README has none.
        readme.write_text(_README_WITHOUT_ROW + "\n" + _ROW)

        with _patched_root(repo):
            result = _handler("block").handle(
                _bash_input('git commit -m "Plan 00001: untrack the plan"')
            )

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_a_folder_deleted_on_disk_but_still_staged_is_not_missing(self, repo: Path) -> None:
        folder = repo / _PLAN_DIR_REL / "00001-first"
        (folder / "PLAN.md").unlink()
        folder.rmdir()

        with _patched_root(repo):
            result = _handler("block").handle(_bash_input('git commit -m "docs"'))

        assert result.decision == Decision.ALLOW
        assert result.context == []
