"""Tests for ConflictMarkerCommitGateHandler (Plan 00466 N211).

Two merge-conflict closers reached ledger 00466's NIGGLES.md as seven-deep
blockquotes: an Edit on the conflicted file ran the markdown formatter, which
disguised the markers, and nothing recognised them afterwards. This gate
reads what a commit would record and denies it when an ADDED line carries a
marker in either spelling.

Every marker below is BUILT, never typed at the start of a source line, so
this file carries no marker the gate would report against itself.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.conflict_marker_commit_gate import (
    ConflictMarkerCommitGateHandler,
    _parse_grep_stream,
)
from claude_code_hooks_daemon.utils.git_repo import run_git

OPEN = "<" * 7
SEP = "=" * 7
CLOSE = ">" * 7
QUOTED_OPEN = " ".join("<" * 7)
QUOTED_CLOSE = " ".join(">" * 7)

_MODULE = "claude_code_hooks_daemon.handlers.pre_tool_use.conflict_marker_commit_gate"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
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


def _init(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for key, value in (
        ("user.email", "t@example.com"),
        ("user.name", "T"),
        ("commit.gpgsign", "false"),
    ):
        _git(root, "config", "--local", key, value)
    return root


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repo with one committed markdown file."""
    root = _init(tmp_path / "repo")
    (root / "doc.md").write_text("# Doc\n\nfirst\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return root


@pytest.fixture()
def handler() -> ConflictMarkerCommitGateHandler:
    return ConflictMarkerCommitGateHandler()


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _stage(repo: Path, relpath: str, content: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", "--", relpath)


def _verdict(handler: ConflictMarkerCommitGateHandler, command: str, cwd: Path) -> Any:
    hook_input = _bash(command, cwd)
    assert handler.matches(hook_input) is True
    return handler.handle(hook_input)


class TestIdentity:
    def test_identity_priority_and_rule(self, handler: ConflictMarkerCommitGateHandler) -> None:
        assert handler.handler_id == HandlerID.CONFLICT_MARKER_COMMIT_GATE
        assert handler.priority == Priority.CONFLICT_MARKER_COMMIT_GATE
        assert [rule.rule_id for rule in handler.get_rules()] == [RuleID.CONFLICT_MARKER_COMMIT]

    def test_guidance_names_both_spellings(self, handler: ConflictMarkerCommitGateHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "blockquote" in guidance


class TestMatches:
    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x",
            "git -C /srv/project commit -m x",
            "env git commit -m x",
            "GIT_EDITOR=true git commit",
            "git \\\n  commit -m x",
            "make build && git commit -am x",
            "for f in a; do git commit -m x; done",
            "/usr/bin/git commit -m x",
            "git merge --continue",
            "git cherry-pick --continue",
            "git revert --continue",
            "git rebase --continue",
            "git am --continue",
            "git am patch.mbox",
            # Review 1 M1: each was not recognised as a commit at all.
            "sudo git commit -m x",
            "command git commit -m x",
            "exec git commit -m x",
            "nice -n 5 git commit -m x",
            "xargs git commit -m x",
            "eval 'git commit -m x'",
            "env -i git commit -m x",
            "env -u X git commit -m x",
            "sh -c 'git commit -m x'",
            "(git commit -m x)",
            "(cd sub && git commit -m x)",
            # Main's shared detector calls these commits; so does this gate.
            "bash <<EOF\ngit commit -m x\nEOF",
            "echo git commit",
        ],
    )
    def test_matches_a_command_that_records_a_commit(
        self, handler: ConflictMarkerCommitGateHandler, command: str
    ) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": command}}) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git merge main",
            "git merge --abort",
            "git commit --dry-run",
            "git diff --cached",
            "echo 'git commit -m x'",
            "",
        ],
    )
    def test_ignores_a_command_that_records_nothing(
        self, handler: ConflictMarkerCommitGateHandler, command: str
    ) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": command}}) is False

    def test_ignores_other_tools(self, handler: ConflictMarkerCommitGateHandler) -> None:
        assert (
            handler.matches({"tool_name": "Write", "tool_input": {"file_path": "/x.md"}}) is False
        )


class TestDeniesAnAddedMarker:
    def test_a_raw_closer_is_denied_naming_file_and_line(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "doc.md:4" in result.reason
        assert RuleID.CONFLICT_MARKER_COMMIT in result.reason

    def test_the_n211_blockquoted_closer_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n\n{QUOTED_CLOSE} worktree-n466-superlinear\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "doc.md:5" in result.reason
        assert "disguised" in result.reason

    def test_a_blockquoted_opener_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "notes.md", f"{QUOTED_OPEN} HEAD\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "notes.md:1" in result.reason

    def test_a_whole_conflict_names_every_marker_line(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "src.py", f"a = 1\n{OPEN} HEAD\nb = 2\n{SEP}\nb = 3\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        for line in (2, 4, 6):
            assert f"src.py:{line}" in result.reason

    def test_a_path_with_a_space_and_non_ascii_is_named(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "my café.md", f"x\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "my café.md:2" in result.reason

    def test_a_renamed_file_carrying_a_new_marker_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _git(repo, "mv", "doc.md", "moved.md")
        (repo / "moved.md").write_text(f"# Doc\n\nfirst\n{CLOSE} main\n")
        _git(repo, "add", "moved.md")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "moved.md:4" in result.reason

    def test_the_first_commit_of_a_repository_is_checked(
        self, handler: ConflictMarkerCommitGateHandler, tmp_path: Path
    ) -> None:
        root = _init(tmp_path / "fresh")
        _stage(root, "a.md", f"{OPEN} HEAD\n")
        result = _verdict(handler, "git commit -m x", root)
        assert result.decision == Decision.DENY
        assert "a.md:1" in result.reason


class TestAllowsWhatIsNotAnAddedMarker:
    def test_a_setext_heading_underline_is_allowed(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n\nHeading\n{SEP}\n\nprose\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.ALLOW

    def test_a_marker_already_in_history_does_not_block_an_unrelated_edit(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        _git(repo, "commit", "-q", "-m", "legacy marker")
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\nnew line\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.ALLOW

    def test_removing_a_marker_is_allowed(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        _git(repo, "commit", "-q", "-m", "legacy marker")
        _stage(repo, "doc.md", "# Doc\n\nfirst\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.ALLOW

    def test_an_inline_mention_is_allowed(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nThe closer `{QUOTED_CLOSE}` is a disguised marker.\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.ALLOW

    def test_a_binary_file_is_skipped(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        (repo / "blob.bin").write_bytes(b"\x00\x01" + f"\n{CLOSE} main\n".encode())
        _git(repo, "add", "blob.bin")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.ALLOW

    def test_an_unstaged_marker_is_not_what_a_plain_commit_records(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "other.md", "clean\n")
        (repo / "doc.md").write_text(f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.ALLOW

    def test_a_directory_outside_any_repository_is_denied_as_unchecked(
        self, handler: ConflictMarkerCommitGateHandler, tmp_path: Path
    ) -> None:
        """Review 1 M4: resolving no repository was a silent allow."""
        outside = tmp_path / "plain"
        outside.mkdir()
        result = _verdict(handler, "git commit -m x", outside)
        assert result.decision == Decision.DENY
        assert "NOT checked" in result.reason


class TestWhatTheCommitRecords:
    def test_commit_all_checks_the_working_tree(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        (repo / "doc.md").write_text(f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -am x", repo)
        assert result.decision == Decision.DENY
        assert "doc.md:4" in result.reason

    def test_a_pathspec_commit_checks_that_paths_working_tree(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        (repo / "doc.md").write_text(f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x doc.md", repo)
        assert result.decision == Decision.DENY

    def test_a_pathspec_commit_does_not_record_other_staged_paths(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "staged.md", f"{CLOSE} main\n")
        (repo / "doc.md").write_text("# Doc\n\nfirst\nclean\n")
        result = _verdict(handler, "git commit -m x -- doc.md", repo)
        assert result.decision == Decision.ALLOW

    def test_an_include_commit_records_the_index_too(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "staged.md", f"{CLOSE} main\n")
        (repo / "doc.md").write_text("# Doc\n\nfirst\nclean\n")
        result = _verdict(handler, "git commit -i -m x doc.md", repo)
        assert result.decision == Decision.DENY
        assert "staged.md:1" in result.reason

    def test_commit_all_on_an_unborn_branch(
        self, handler: ConflictMarkerCommitGateHandler, tmp_path: Path
    ) -> None:
        root = _init(tmp_path / "fresh")
        _stage(root, "a.md", "clean\n")
        (root / "a.md").write_text(f"clean\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -am x", root)
        assert result.decision == Decision.DENY
        assert "a.md:2" in result.reason

    def test_git_dash_c_names_the_repository_not_the_cwd(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, tmp_path: Path
    ) -> None:
        elsewhere = _init(tmp_path / "elsewhere")
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, f"git -C {repo} commit -m x", elsewhere)
        assert result.decision == Decision.DENY

    def test_a_relative_dash_c_resolves_against_the_cwd(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, f"git -C {repo.name} commit -m x", repo.parent)
        assert result.decision == Decision.DENY

    def test_a_pathspec_is_read_relative_to_the_commands_directory(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "docs/page.md", "clean\n")
        _git(repo, "commit", "-q", "-m", "page")
        (repo / "docs" / "page.md").write_text(f"clean\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x page.md", repo / "docs")
        assert result.decision == Decision.DENY
        assert "docs/page.md:2" in result.reason

    def test_a_cd_earlier_in_the_command_names_the_repository(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, tmp_path: Path
    ) -> None:
        elsewhere = _init(tmp_path / "elsewhere")
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, f"cd {repo} && git commit -m x", elsewhere)
        assert result.decision == Decision.DENY

    def test_a_relative_cd_resolves_against_the_cwd(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, f"cd {repo.name}; git commit -m x", repo.parent)
        assert result.decision == Decision.DENY

    def test_an_unresolvable_cd_is_denied_even_when_the_tree_is_clean(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        """Review 1 M1: the old test passed only because the cwd was the repo."""
        result = _verdict(handler, "cd - && git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "NOT checked" in result.reason

    def test_merge_continue_checks_the_index(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{QUOTED_CLOSE} main\n")
        result = _verdict(handler, "git merge --continue", repo)
        assert result.decision == Decision.DENY


class TestAGitFailureIsReportedNotSilent:
    def test_an_unreadable_index_denies_naming_the_error(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        failed = subprocess.CompletedProcess(args=["git"], returncode=128, stdout="", stderr="boom")
        with patch(f"{_MODULE}.run_git", return_value=failed):
            result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "NOT checked" in result.reason
        assert "boom" in result.reason


class TestCommandShapes:
    @pytest.mark.parametrize(
        "command",
        [
            'git commit -m "unbalanced',
            "git --no-pager commit -m x",
        ],
    )
    def test_still_a_commit(self, handler: ConflictMarkerCommitGateHandler, command: str) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": command}}) is True

    @pytest.mark.parametrize("command", ["FOO=1", "env", "git", "git -C", "git --no-pager"])
    def test_not_a_commit(self, handler: ConflictMarkerCommitGateHandler, command: str) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": command}}) is False

    def test_a_missing_cwd_falls_back_to_the_project_root(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
        with patch(f"{_MODULE}.ProjectContext.project_root", return_value=repo):
            result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_an_empty_commit_records_nothing_to_check(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        result = _verdict(handler, "git commit --allow-empty -m x", repo)
        assert result.decision == Decision.ALLOW
        assert not result.context


class TestGrepStream:
    def test_a_path_holding_a_newline_is_kept_whole(self) -> None:
        stream = "a\nb.md\x003\x00line one\nc.md\x001\x00line two\n"
        assert _parse_grep_stream(stream) == {
            "a\nb.md": [(3, "line one")],
            "c.md": [(1, "line two")],
        }

    def test_a_last_record_without_a_newline_is_read(self) -> None:
        assert _parse_grep_stream("c.md\x002\x00tail") == {"c.md": [(2, "tail")]}

    def test_a_non_numeric_line_number_is_skipped(self) -> None:
        assert _parse_grep_stream("c.md\x00x\x00text\n") == {}

    def test_a_truncated_record_ends_the_parse(self) -> None:
        assert _parse_grep_stream("c.md\x001\x00ok\nd.md") == {"c.md": [(1, "ok")]}


class TestAGrepFailureIsReported:
    def test_a_failing_grep_allows_with_a_visible_advisory(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", "# Doc\n\nfirst\nmore\n")
        real_run_git = run_git

        def _grep_fails(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
            if "grep" in args:
                return subprocess.CompletedProcess(args=["git"], returncode=2, stdout="", stderr="")
            return real_run_git(root, *args)

        with patch(f"{_MODULE}.run_git", side_effect=_grep_fails):
            result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "git grep exited 2" in result.reason


class TestShellSyntaxNeverHidesTheIndex:
    """Review 1 B1 / ledger 00466 N226: each shape below allowed a staged marker."""

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x 2>&1",
            "git commit -m x 2>&1 | bin/echd-capture 20",
            "git commit -m x > /dev/null",
            "git commit -F- <<'EOF'\nsubject\nEOF",
            "git commit -m x &",
            "git commit -t tmpl -m x",
            "git commit --cleanup strip -m x",
            "git commit --author 'A <a@b.c>' -m x",
        ],
    )
    def test_a_staged_marker_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, command: str
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, command, repo)
        assert result.decision == Decision.DENY
        assert "doc.md:4" in result.reason

    def test_pathspecs_that_match_nothing_judge_the_index(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x no-such-path", repo)
        assert result.decision == Decision.DENY


class TestEveryWrapperIsJudged:
    """Review 1 M1: none of these was recognised as a commit."""

    @pytest.mark.parametrize(
        "command",
        [
            "sudo git commit -m x",
            "command git commit -m x",
            "nice -n 5 git commit -m x",
            "eval 'git commit -m x'",
            "env -i git commit -m x",
            "sh -c 'git commit -m x'",
            "(git commit -m x)",
        ],
    )
    def test_a_staged_marker_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, command: str
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        assert handler.matches(_bash(command, repo)) is True
        assert _verdict(handler, command, repo).decision == Decision.DENY

    def test_a_subshell_cd_names_the_repository(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, tmp_path: Path
    ) -> None:
        elsewhere = _init(tmp_path / "elsewhere")
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        result = _verdict(handler, f"(cd {repo} && git commit -m x)", elsewhere)
        assert result.decision == Decision.DENY
        assert "doc.md:4" in result.reason


class TestAnUncheckableCommitIsDenied:
    """Review 1 M4: a commit the gate cannot place is denied, with a rephrase."""

    @pytest.mark.parametrize(
        ("command", "named"),
        [
            ('cd "$WT" && git commit -m x', "$WT"),
            ("git -C $WT commit -m x", "$WT"),
            ("cd - && git commit -m x", "cd -"),
            ("popd && git commit -m x", "popd"),
            ("git --git-dir=/x/.git commit -m x", "--git-dir"),
            ("git --work-tree /x commit -m x", "--work-tree"),
            ("GIT_INDEX_FILE=/tmp/i git commit -m x", "GIT_INDEX_FILE"),
            ("git commit --pathspec-from-file=list.txt -m x", "--pathspec-from-file"),
            ("git am patch.mbox", "git am"),
            ("cd no-such-dir && git commit -m x", "no-such-dir"),
        ],
    )
    def test_names_the_reason_and_the_rephrase(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, command: str, named: str
    ) -> None:
        result = _verdict(handler, command, repo)
        assert result.decision == Decision.DENY
        assert "NOT checked" in result.reason
        assert named in result.reason
        assert "git -C /absolute/path/to/repo commit" in result.reason

    def test_am_continue_checks_the_index(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        assert _verdict(handler, "git am --continue", repo).decision == Decision.DENY


class TestRoutineIdiomsStillCommit:
    """Review 1 M4: fail-closed placement must not refuse the everyday shapes."""

    @pytest.mark.parametrize(
        "template",
        [
            "git commit -m x",
            "git commit -m x 2>&1 | bin/echd-capture 20",
            "git -C {repo} commit -m x",
            "cd {repo} && git commit -m x",
            "cd {repo}; git add doc.md && git commit -m x",
            "git commit -F- <<'EOF'\nsubject\n\nbody\nEOF",
        ],
    )
    def test_a_clean_commit_is_allowed(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, template: str
    ) -> None:
        _stage(repo, "doc.md", "# Doc\n\nfirst\nsecond\n")
        result = _verdict(handler, template.format(repo=repo), repo)
        assert result.decision == Decision.ALLOW


class TestExcludePaths:
    """Review 1 M3: a documented example has a way through."""

    def test_the_handler_option_exempts_a_path(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "fixtures/conflict.md", f"{OPEN} ours\nx\n{SEP}\ny\n{CLOSE} theirs\n")
        handler._exclude_paths = ["fixtures/**"]
        assert _verdict(handler, "git commit -m x", repo).decision == Decision.ALLOW

    def test_the_project_option_exempts_a_path(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "fixtures/conflict.md", f"{OPEN} ours\nx\n{SEP}\ny\n{CLOSE} theirs\n")
        handler._project_exclude_paths = ["fixtures/**"]
        assert _verdict(handler, "git commit -m x", repo).decision == Decision.ALLOW

    def test_a_marker_in_a_fence_is_still_denied_and_the_way_through_is_named(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n```\n{OPEN} ours\n{SEP}\n{CLOSE} theirs\n```\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "conflict_marker_commit_gate.options.exclude_paths" in result.reason
        assert "daemon.exclude_paths" in result.reason
        assert "fenced code block" in result.reason


class TestAcceptanceTests:
    def test_declares_a_deny_and_an_allow(self, handler: ConflictMarkerCommitGateHandler) -> None:
        decisions = {test.expected_decision for test in handler.get_acceptance_tests()}
        assert decisions == {Decision.DENY, Decision.ALLOW}


class TestAProtectedFileIsCheckedWithoutEchoingIt:
    def test_the_line_text_is_withheld(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "vault.md", f"{CLOSE} secret-branch-name\n")
        with patch(f"{_MODULE}.sfm.path_is_protected", return_value=True):
            result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "vault.md:1" in result.reason
        assert "secret-branch-name" not in result.reason
        assert "withheld" in result.reason


class TestTheDenyMessage:
    def test_the_second_denial_is_terse_but_still_names_the_line(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        hook_input = _bash("git commit -m x", repo)
        hook_input["transcript_path"] = str(repo / "transcript.jsonl")
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert first.reason is not None
        assert second.reason is not None
        assert len(second.reason) < len(first.reason)
        assert "doc.md:4" in second.reason

    def test_a_long_list_is_capped_with_a_count(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "many.md", "".join(f"{CLOSE} b{i}\n" for i in range(60)))
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "more" in result.reason
        assert "many.md:60" not in result.reason


class TestEveryFormatterDisguiseIsDenied:
    """Review 1 M2: an opener the formatter folded mid-line reaches the classifier."""

    @pytest.mark.parametrize(
        "line",
        [
            "# Intro text. \\<<\\<<\\<<< HEAD ours",
            "> \\<<\\<<\\<<< HEAD",
            "1. # step \\<<\\<<\\<<< HEAD ours",
            "\\<<\\<<\\<<\\<",
        ],
    )
    def test_a_lone_disguised_opener_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, line: str
    ) -> None:
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n\n{line}\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "doc.md:5" in result.reason

    def test_a_deep_email_quote_is_allowed(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        """Review 1 minor 1."""
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n\n{QUOTED_CLOSE} > > quoted reply text\n")
        assert _verdict(handler, "git commit -m x", repo).decision == Decision.ALLOW


class TestConflictMarkerSizeAttribute:
    """Review 1 minor 2: git writes markers of the `conflict-marker-size` length."""

    @pytest.mark.parametrize("size", [3, 9])
    def test_a_marker_of_the_attributed_size_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, size: int
    ) -> None:
        _stage(repo, ".gitattributes", f"*.txt conflict-marker-size={size}\n")
        _stage(repo, "a.txt", f"x\n{'>' * size} main\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "a.txt:2" in result.reason

    def test_a_default_run_in_a_resized_file_is_not_a_marker(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, ".gitattributes", "*.txt conflict-marker-size=9\n")
        _stage(repo, "a.txt", f"x\n{CLOSE} main\n")
        assert _verdict(handler, "git commit -m x", repo).decision == Decision.ALLOW

    def test_commit_all_reads_the_working_trees_attributes(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, "a.txt", "x\n")
        _git(repo, "commit", "-q", "-m", "a")
        (repo / ".gitattributes").write_text("*.txt conflict-marker-size=9\n")
        _git(repo, "add", ".gitattributes")
        _git(repo, "commit", "-q", "-m", "attrs")
        (repo / "a.txt").write_text(f"x\n{'>' * 9} main\n")
        result = _verdict(handler, "git commit -am x", repo)
        assert result.decision == Decision.DENY
        assert "a.txt:2" in result.reason


class TestAFileGitCallsBinaryByAttributeIsRead:
    """Review 1 minor 4: `-diff` hid the added lines, so markers were dropped."""

    @pytest.mark.parametrize("attribute", ["-diff", "binary", "-text"])
    def test_an_added_marker_is_denied(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path, attribute: str
    ) -> None:
        _stage(repo, ".gitattributes", f"*.lock {attribute}\n")
        _stage(repo, "deps.lock", "a\n")
        _git(repo, "commit", "-q", "-m", "lock")
        _stage(repo, "deps.lock", f"a\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -m x", repo)
        assert result.decision == Decision.DENY
        assert "deps.lock:2" in result.reason

    def test_a_marker_already_there_still_does_not_block(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, ".gitattributes", "*.lock -diff\n")
        _stage(repo, "deps.lock", f"a\n{CLOSE} main\n")
        _git(repo, "commit", "-q", "-m", "lock")
        _stage(repo, "deps.lock", f"a\n{CLOSE} main\nb\n")
        assert _verdict(handler, "git commit -m x", repo).decision == Decision.ALLOW

    def test_a_working_tree_commit_reads_it_too(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        _stage(repo, ".gitattributes", "*.lock -diff\n")
        _stage(repo, "deps.lock", "a\n")
        _git(repo, "commit", "-q", "-m", "lock")
        (repo / "deps.lock").write_text(f"a\n{CLOSE} main\n")
        result = _verdict(handler, "git commit -am x", repo)
        assert result.decision == Decision.DENY
        assert "deps.lock:2" in result.reason


class TestTheAcceptanceTestsCanFail:
    """Review 1 minor 7: each dispatched acceptance test is run here for real."""

    @staticmethod
    def _dispatched(handler: ConflictMarkerCommitGateHandler) -> list[Any]:
        return [
            test
            for test in handler.get_acceptance_tests()
            if test.tool_payload is not None and test.harness_cannot_produce is None
        ]

    def test_there_is_a_dry_run_and_a_cd_dash_test(
        self, handler: ConflictMarkerCommitGateHandler
    ) -> None:
        commands = [test.command for test in self._dispatched(handler)]
        assert any("--dry-run" in command for command in commands)
        assert any(command.startswith("cd - ") for command in commands)

    def test_each_verdict_holds_even_with_a_marker_staged(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        """A staged marker makes an ALLOW mean the gate truly skipped the command."""
        _stage(repo, "doc.md", f"# Doc\n\nfirst\n{CLOSE} main\n")
        for test in self._dispatched(handler):
            hook_input = _bash(test.command, repo)
            if not handler.matches(hook_input):
                assert test.expected_decision == Decision.ALLOW, test.title
                continue
            result = handler.handle(hook_input)
            assert result.decision == test.expected_decision, test.title
            for pattern in test.expected_message_patterns:
                assert re.search(pattern, result.reason or ""), (test.title, pattern)

    def test_the_dry_run_command_would_deny_were_dry_run_misjudged(
        self, handler: ConflictMarkerCommitGateHandler, repo: Path
    ) -> None:
        """Strip `--dry-run` and the same command must deny: the ALLOW can fail."""
        (dry_run,) = [t for t in self._dispatched(handler) if "--dry-run" in t.command]
        judged = dry_run.command.replace(" --dry-run", "")
        result = _verdict(handler, judged, repo)
        assert result.decision == Decision.DENY
        assert "NOT checked" in (result.reason or "")
