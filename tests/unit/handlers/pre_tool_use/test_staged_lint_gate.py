"""Tests for StagedLintGateHandler (Plan 00268 Task 3.2).

The backstop half of the verifier/mutator work: `lint_on_edit` only ever sees
a file at the moment `Write`/`Edit` touches it, so a file that reached the
index by any OTHER route (`git add` of something written earlier in the
session, a `git commit` of pre-existing changes, a merge) is never linted
before it lands. This handler runs a CHEAP syntax check over every staged
Added/Copied/Modified file at `git commit` time, so the outcome is caught
however the commit was invoked -- the same "however it happened" framing as
`plan_qa_commit_gate`, applied to lint rather than plan hygiene.

Cost bounds are part of the contract, not an afterthought: only the
default/syntax tier ever runs (never the extended linter), and `max_files`
stands the whole check down rather than linting an unbounded set.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision, TestType
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import (
    StagedLintGateHandler,
)
from claude_code_hooks_daemon.utils.git_repo import run_git


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


_SAFE_PATH = "/srv/project"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
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
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate."
        "ProjectContext.project_root"
    )
    return patch(target, return_value=root)


def _stage_file(repo: Path, relpath: str, content: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", relpath)


@pytest.fixture()
def handler() -> StagedLintGateHandler:
    return StagedLintGateHandler()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal git repo with an initial commit, ready to stage files into."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# repo\n")
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class TestInitialisation:
    def test_identity_and_priority(self, handler: StagedLintGateHandler) -> None:
        assert handler.handler_id == HandlerID.STAGED_LINT_GATE
        assert handler.priority == Priority.STAGED_LINT_GATE

    def test_is_not_terminal(self, handler: StagedLintGateHandler) -> None:
        assert handler.terminal is False


class TestMatches:
    def test_ignores_non_bash_tools(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches({"tool_name": "Write", "tool_input": {"file_path": "/x"}}) is False

    def test_matches_git_commit(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches(_bash('git commit -m "x"')) is True

    def test_matches_git_commit_with_global_options(self, handler: StagedLintGateHandler) -> None:
        """`git -C /path commit` read "/path" as the subcommand and walked past
        an earlier guard in this codebase -- GIT_INVOCATION exists for it."""
        assert handler.matches(_bash(f"git -C {_SAFE_PATH} commit -m x")) is True

    def test_matches_env_prefixed_git_commit(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches(_bash("env git commit -m x")) is True

    def test_matches_line_continued_git_commit(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches(_bash("git \\\n  commit -m x")) is True

    def test_matches_git_commit_after_a_chained_command(
        self, handler: StagedLintGateHandler
    ) -> None:
        assert handler.matches(_bash("npm run build && git commit -m x")) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git diff --cached",
            'gh pr create --title "x" --body "y"',
            "",
        ],
    )
    def test_does_not_match_non_commit_commands(
        self, handler: StagedLintGateHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False


class TestNoStagedLintableFiles:
    def test_allows_silently_when_nothing_is_staged(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_allows_silently_when_staged_files_have_no_strategy(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "notes.txt", "just some prose\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestSyntaxFailureIsSurfaced:
    def test_a_failing_staged_python_file_is_named_with_its_diagnosis(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW  # warn mode: the default
        assert result.context
        rendered = " ".join(result.context)
        assert "broken.py" in rendered

    def test_a_clean_staged_python_file_produces_no_finding(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_a_check_that_timed_out_is_said_at_warning(
        self, handler: StagedLintGateHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        """00466 N29: a timed-out check never looked at the file, so there is no
        diagnosis to block on, and the log says the file went unchecked."""
        strategy = MagicMock(default_lint_command="lint-tool {file}")
        target = "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate.subprocess.run"

        with (
            patch.object(handler, "_resolve_executable", return_value="/usr/bin/lint-tool"),
            patch(
                target,
                side_effect=subprocess.TimeoutExpired(cmd="lint", timeout=Timeout.LINT_CHECK),
            ),
            caplog.at_level(logging.WARNING),
        ):
            assert handler._syntax_check("slow.py", strategy) is None

        assert "slow.py was NOT checked" in caplog.text


class TestProtectedPathExclusion:
    def test_a_broken_protected_file_is_never_named(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        """Plan 00272 Task 4-5: a protected file is skipped, whatever its syntax."""
        _stage_file(repo, "broken.protectedmarker.py", "def broken(\n")

        target = (
            "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate."
            "sfm.resolve_configured_patterns"
        )
        with _patched_root(repo), patch(target, return_value=("*.protectedmarker*",)):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestModes:
    def test_warn_mode_allows_with_context(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert result.context

    def test_block_mode_denies(self, handler: StagedLintGateHandler, repo: Path) -> None:
        handler._mode = "block"
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.DENY
        assert result.reason
        assert "broken.py" in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.STAGED_LINT_FAILURE}]")

    def test_a_clean_commit_allows_silently_in_block_mode(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        handler._mode = "block"
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestEachCommitFormLintsWhatItRecords:
    """Ledger 00474 N245: the files linted are the files the commit records.

    ``git commit <pathspec>`` records the named paths only, so a broken file
    that is merely staged is not in it, and a broken named file that is not
    staged at all is. ``--include`` records the index as well.
    """

    @pytest.fixture
    def tracked(self, repo: Path) -> Path:
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")
        _stage_file(repo, "later.py", "def later() -> None:\n    return None\n")
        _git(repo, "commit", "-m", "tracked")
        return repo

    def _handle(self, handler: StagedLintGateHandler, repo: Path, command: str) -> str:
        with _patched_root(repo):
            return " ".join(handler.handle(_bash(command)).context)

    def test_a_staged_broken_file_the_pathspec_commit_does_not_name_is_not_linted(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        _stage_file(tracked, "broken.py", "def broken(\n")
        (tracked / "clean.py").write_text("def clean() -> int:\n    return 1\n")

        rendered = self._handle(handler, tracked, 'git commit -m "x" clean.py')

        assert "broken.py" not in rendered

    def test_an_unstaged_broken_file_a_pathspec_commit_names_is_linted(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        (tracked / "later.py").write_text("def later(\n")

        rendered = self._handle(handler, tracked, 'git commit -m "x" later.py')

        assert "later.py" in rendered

    def test_include_lints_the_index_and_the_named_paths(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        _stage_file(tracked, "broken.py", "def broken(\n")
        (tracked / "later.py").write_text("def later(\n")

        rendered = self._handle(handler, tracked, 'git commit -m "x" --include later.py')

        assert "broken.py" in rendered
        assert "later.py" in rendered

    def test_a_bare_commit_still_lints_the_index(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        _stage_file(tracked, "broken.py", "def broken(\n")
        (tracked / "later.py").write_text("def later(\n")

        rendered = self._handle(handler, tracked, 'git commit -m "x"')

        assert "broken.py" in rendered
        assert "later.py" not in rendered


class TestPathspecViewIsUsedOnlyWhenTheReadingIsCertain:
    """Ledger 00474 N245 round 2: never lint LESS of the recorded tree than the index.

    ``sub/broken.py`` is staged and broken. Each command records it by a route
    the pathspec view cannot follow, so the gate keeps linting the index.
    """

    @pytest.fixture
    def tracked(self, repo: Path) -> Path:
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")
        _stage_file(repo, "sub/clean.py", "def clean() -> None:\n    return None\n")
        _git(repo, "commit", "-m", "tracked")
        _stage_file(repo, "sub/broken.py", "def broken(\n")
        (repo / "clean.py").write_text("def clean() -> int:\n    return 1\n")
        return repo

    def _handle(
        self, handler: StagedLintGateHandler, repo: Path, command: str, cwd: Path | None = None
    ) -> str:
        with _patched_root(repo):
            return " ".join(handler.handle(_bash(command, str(cwd or repo))).context)

    @pytest.mark.parametrize(
        "command",
        [
            "cd sub && git commit -m x clean.py",
            "git -C sub commit -m x clean.py",
            "(cd sub; git commit -m x clean.py)",
            "git commit -m x clean.py && git commit -m y",
            "F=sub/broken.py; git commit -m x clean.py $F",
            "git commit -m x clean.py nosuch.py",
            "git commit -m x nosuch.py",
        ],
    )
    def test_an_uncertain_reading_keeps_the_index(
        self, handler: StagedLintGateHandler, tracked: Path, command: str
    ) -> None:
        assert "broken.py" in self._handle(handler, tracked, command)

    def test_diff_relative_does_not_misplace_a_named_file(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        _git(tracked, "config", "diff.relative", "true")
        (tracked / "sub" / "clean.py").write_text("def clean(\n")

        rendered = self._handle(handler, tracked, "git commit -m x clean.py", tracked / "sub")

        assert "clean.py" in rendered

    def test_a_file_removed_from_the_index_then_broken_on_disk_is_linted(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        _git(tracked, "rm", "-q", "--cached", "clean.py")
        (tracked / "clean.py").write_text("def clean(\n")

        rendered = self._handle(handler, tracked, "git commit -m x clean.py")

        assert "clean.py" in rendered

    def test_a_certain_reading_still_narrows(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        assert "broken.py" not in self._handle(handler, tracked, "git commit -m x clean.py")


class TestMaxFiles:
    def test_standing_down_names_how_many_files_were_skipped(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        handler._max_files = 1
        _stage_file(repo, "a.py", "def a() -> None:\n    return None\n")
        _stage_file(repo, "b.py", "def b() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert result.context
        rendered = " ".join(result.context)
        assert "2" in rendered

    def test_a_non_int_option_is_ignored_rather_than_crashing(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        """Options arrive by blind setattr from YAML, so the handler must not
        trust the type it is handed."""
        handler._max_files = "not-a-number"
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW


class TestForeignRepoExempt:
    def test_a_commit_inside_a_nested_or_foreign_repo_is_ignored(
        self, handler: StagedLintGateHandler, repo: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other-repo"
        other.mkdir()
        _git(other, "init")
        _git(other, "config", "user.email", "t@example.com")
        _git(other, "config", "user.name", "T")
        (other / "broken.py").write_text("def broken(\n")
        _git(other, "add", "-A")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"', cwd=str(other)))

        assert result.decision == Decision.ALLOW
        assert not result.context

    @pytest.mark.parametrize(
        "form", ["cd {other} && git commit -m x", "git -C {other} commit -m x"]
    )
    def test_a_command_that_moves_into_another_repo_is_ignored(
        self, handler: StagedLintGateHandler, repo: Path, tmp_path: Path, form: str
    ) -> None:
        """Ledger 00474 N305: where the commit runs is the cwd after the move."""
        other = tmp_path / "other-repo"
        other.mkdir()
        _git(other, "init")
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash(form.format(other=other), cwd=str(repo)))

        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_a_move_that_stays_in_this_repo_is_still_judged(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        (repo / "sub").mkdir()
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash("cd sub && git commit -m x", cwd=str(repo)))

        assert result.context


class TestGuidance:
    def test_publishes_resident_guidance(self, handler: StagedLintGateHandler) -> None:
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert "staged" in guidance.lower()

    def test_publishes_acceptance_tests(self, handler: StagedLintGateHandler) -> None:
        tests = handler.get_acceptance_tests()

        assert tests
        for test in tests:
            assert test.test_type == TestType.ADVISORY
            assert test.requires_main_thread is False


class TestGetRules:
    def test_returns_one_rule(self, handler: StagedLintGateHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self, handler: StagedLintGateHandler) -> None:
        assert handler.get_rules()[0].rule_id == RuleID.STAGED_LINT_FAILURE

    def test_rule_has_non_empty_verbose(self, handler: StagedLintGateHandler) -> None:
        assert handler.get_rules()[0].verbose


class TestBlockModeDisclosureLadder:
    """Verbose-first/terse-after teaching prose; findings stay fully present always."""

    def test_first_fire_for_agent_is_verbose(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        handler._mode = "block"
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(
                _bash('git commit -m "x"') | {"transcript_path": "/tmp/agent-a/transcript.jsonl"}
            )

        assert result.reason is not None
        assert "CHEAP syntax tier only" in result.reason

    def test_second_fire_is_terse_but_findings_stay_full(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        handler._mode = "block"
        transcript_path = "/tmp/agent-a/transcript.jsonl"

        _stage_file(repo, "broken.py", "def broken(\n")
        with _patched_root(repo):
            handler.handle(_bash('git commit -m "x"') | {"transcript_path": transcript_path})

        _stage_file(repo, "broken2.py", "def broken2(\n")
        with _patched_root(repo):
            result = handler.handle(
                _bash('git commit -m "x"') | {"transcript_path": transcript_path}
            )

        assert result.reason is not None
        assert "CHEAP syntax tier only" not in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.STAGED_LINT_FAILURE}]")
        assert "Fix:" in result.reason
        # Findings are dynamic content: always fully present, terse or not.
        assert "broken.py" in result.reason
        assert "broken2.py" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        handler._mode = "block"
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            first = handler.handle(_bash('git commit -m "x"'))
            second = handler.handle(_bash('git commit -m "x"'))

        assert first.reason is not None
        assert "CHEAP syntax tier only" in first.reason
        assert second.reason is not None
        assert "CHEAP syntax tier only" in second.reason


class TestACommandThatStagesOrCommitsMoreThanOnce:
    """Ledger 00474 N246 and N307: the files linted are those the whole command records."""

    @pytest.fixture
    def tracked(self, repo: Path) -> Path:
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")
        _stage_file(repo, "sub/clean.py", "def clean() -> None:\n    return None\n")
        _git(repo, "commit", "-m", "tracked")
        return repo

    def _handle(self, handler: StagedLintGateHandler, repo: Path, command: str) -> str:
        with _patched_root(repo):
            return " ".join(handler.handle(_bash(command, str(repo))).context)

    @pytest.mark.parametrize(
        "command",
        [
            "git add broken.py && git commit -m x",
            "git add -A && git commit -m x",
            "git add . && git commit -m x",
            "git add broken.py && git commit -m x broken.py",
        ],
    )
    def test_a_file_the_same_command_adds_is_linted(
        self, handler: StagedLintGateHandler, tracked: Path, command: str
    ) -> None:
        (tracked / "broken.py").write_text("def broken(\n")

        assert "broken.py" in self._handle(handler, tracked, command)

    def test_a_file_the_add_does_not_name_is_not_linted(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        (tracked / "broken.py").write_text("def broken(\n")

        assert "broken.py" not in self._handle(
            handler, tracked, "git add clean.py && git commit -m x"
        )

    def test_the_second_commits_pathspec_is_linted(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        _stage_file(tracked, "later.py", "def later() -> None:\n    return None\n")
        _git(tracked, "commit", "-m", "later")
        (tracked / "clean.py").write_text("def clean() -> int:\n    return 1\n")
        (tracked / "later.py").write_text("def later(\n")

        rendered = self._handle(
            handler, tracked, "git commit -m a clean.py; git commit -m b later.py"
        )

        assert "later.py" in rendered

    @pytest.mark.parametrize(("mode", "decision"), [("block", Decision.DENY), ("warn", None)])
    def test_an_add_that_cannot_be_simulated_is_not_read_as_clean(
        self, handler: StagedLintGateHandler, tracked: Path, mode: str, decision: Decision | None
    ) -> None:
        handler._mode = mode
        (tracked / "broken.py").write_text("def broken(\n")
        timed_out = subprocess.CompletedProcess(["git"], 127, "", "timed out after 5s")
        real = run_git

        def run(directory: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "add" in args[:3]:
                return timed_out
            return real(directory, *args, **kwargs)

        with (
            _patched_root(tracked),
            patch("claude_code_hooks_daemon.utils.staging_simulation.run_git", side_effect=run),
        ):
            result = handler.handle(_bash("git add broken.py && git commit -m x", str(tracked)))

        if decision is Decision.DENY:
            assert result.decision == Decision.DENY
            assert "separate command" in (result.reason or "")
        else:
            assert result.decision == Decision.ALLOW
            assert "separate command" in " ".join(result.context)

    def test_the_real_index_is_untouched(
        self, handler: StagedLintGateHandler, tracked: Path
    ) -> None:
        (tracked / "broken.py").write_text("def broken(\n")

        self._handle(handler, tracked, "git add broken.py && git commit -m x")

        staged = subprocess.run(
            ["git", "-C", str(tracked), "diff", "--cached", "--name-only"],
            capture_output=True,
            check=True,
            text=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        assert staged.stdout == ""
