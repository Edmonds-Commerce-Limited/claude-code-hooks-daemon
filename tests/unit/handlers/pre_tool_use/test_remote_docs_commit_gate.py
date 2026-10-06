"""The remote-docs commit gate (Plan 00326 Success Criteria).

The write-time gate keys on `Write`/`Edit`, so a Bash heredoc or redirect
into the tree reaches disk unexamined. That is a real hole, recorded as
BLIND in the bash-write-blindness register, and this is the backstop that
closes it: whatever route a file took to disk, it cannot be COMMITTED
without provenance.

The staleness sweep already reports such a file at the next session start.
This is stronger — it stops the unattributed document entering history at
all, which matters because removing one afterwards needs a rewrite.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_commit_gate import (
    RemoteDocsCommitGateHandler,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import CommitReading

_VALID = """---
source_url: https://example.com/p
fetched_at: 2026-09-03T10:00:00+00:00
fidelity: verbatim
source_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
licence: CC-BY-4.0
stale_after: 2026-12-01
---

# Upstream
"""


def _commit() -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'add docs'"}}


@pytest.fixture
def handler(tmp_path: Path) -> RemoteDocsCommitGateHandler:
    instance = RemoteDocsCommitGateHandler()
    instance.project_root_reader = lambda: tmp_path
    instance.staged_reader = lambda _reading, _cwd: []
    return instance


def _write(tmp_path: Path, rel: str, content: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return rel


class TestScope:
    def test_it_matches_a_git_commit(self, handler: RemoteDocsCommitGateHandler) -> None:
        assert handler.matches(_commit()) is True

    def test_it_ignores_other_bash_commands(self, handler: RemoteDocsCommitGateHandler) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is False

    def test_it_ignores_other_tools(self, handler: RemoteDocsCommitGateHandler) -> None:
        assert handler.matches({"tool_name": "Write", "tool_input": {}}) is False


class TestGate:
    def test_a_commit_with_no_remote_docs_is_allowed(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda _reading, _cwd: [_write(tmp_path, "src/thing.py", "x = 1\n")]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_valid_vendored_document_is_allowed(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda _reading, _cwd: [
            _write(tmp_path, "remote-docs/example.com/p.md", _VALID)
        ]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_document_with_no_provenance_is_denied(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        """This is the heredoc hole: it never passed the Write/Edit gate."""
        handler.staged_reader = lambda _reading, _cwd: [
            _write(tmp_path, "remote-docs/example.com/p.md", "# just prose\n")
        ]

        assert handler.handle(_commit()).decision is Decision.DENY

    def test_the_denial_names_the_offending_file(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda _reading, _cwd: [
            _write(tmp_path, "remote-docs/example.com/p.md", "# just prose\n")
        ]

        reason = handler.handle(_commit()).reason or ""

        assert "remote-docs/example.com/p.md" in reason

    def test_the_denial_names_the_capture_route(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda _reading, _cwd: [
            _write(tmp_path, "remote-docs/example.com/p.md", "# just prose\n")
        ]

        assert "remote-docs add" in (handler.handle(_commit()).reason or "")

    def test_every_bad_document_is_reported_at_once(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        """One file per retry would make a bulk import a slog."""
        handler.staged_reader = lambda _reading, _cwd: [
            _write(tmp_path, "remote-docs/example.com/a.md", "# prose\n"),
            _write(tmp_path, "remote-docs/example.com/b.md", "# prose\n"),
        ]

        reason = handler.handle(_commit()).reason or ""

        assert "a.md" in reason
        assert "b.md" in reason

    def test_a_non_markdown_file_in_the_tree_is_ignored(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda _reading, _cwd: [
            _write(tmp_path, "remote-docs/x/data.json", "{}")
        ]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_deleted_file_does_not_block_the_commit(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        """Removing a bad document must never be harder than adding one."""
        handler.staged_reader = lambda _reading, _cwd: ["remote-docs/example.com/gone.md"]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_markdown_file_outside_the_tree_is_ignored(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda _reading, _cwd: [
            _write(tmp_path, "docs/guide.md", "# ours\n")
        ]

        assert handler.handle(_commit()).decision is Decision.ALLOW


class TestEachCommitFormJudgesWhatItRecords:
    """Ledger 00474 N245, read from a real index.

    ``git commit <pathspec>`` records the named paths only, so a bad document
    that is merely staged is not in it; ``--include`` records the index too.
    """

    @staticmethod
    def _git(repo: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            timeout=Timeout.GIT_CONTEXT,
        )

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        self._git(root, "init")
        self._git(root, "config", "user.email", "t@example.com")
        self._git(root, "config", "user.name", "T")
        _write(root, "src/thing.py", "x = 1\n")
        self._git(root, "add", "-A")
        self._git(root, "commit", "-m", "initial")
        _write(root, "remote-docs/example.com/bad.md", "# prose, no provenance\n")
        self._git(root, "add", "remote-docs/example.com/bad.md")
        _write(root, "src/thing.py", "x = 2\n")
        return root

    @staticmethod
    def _real(root: Path) -> RemoteDocsCommitGateHandler:
        instance = RemoteDocsCommitGateHandler()
        instance.project_root_reader = lambda: root
        return instance

    @staticmethod
    def _bash(command: str) -> dict[str, Any]:
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def test_a_bare_commit_records_the_staged_document(self, repo: Path) -> None:
        result = self._real(repo).handle(self._bash("git commit -m x"))

        assert result.decision is Decision.DENY

    def test_a_pathspec_commit_does_not_record_an_unnamed_staged_document(self, repo: Path) -> None:
        result = self._real(repo).handle(self._bash("git commit -m x src/thing.py"))

        assert result.decision is Decision.ALLOW

    def test_a_pathspec_commit_records_a_named_document(self, repo: Path) -> None:
        result = self._real(repo).handle(
            self._bash("git commit -m x remote-docs/example.com/bad.md")
        )

        assert result.decision is Decision.DENY
        assert "remote-docs/example.com/bad.md" in (result.reason or "")

    def test_include_records_the_staged_document_as_well(self, repo: Path) -> None:
        result = self._real(repo).handle(self._bash("git commit -m x --include src/thing.py"))

        assert result.decision is Decision.DENY

    def test_a_named_document_made_valid_on_disk_is_allowed_though_staged_bad(
        self, repo: Path
    ) -> None:
        _write(repo, "remote-docs/example.com/bad.md", _VALID)

        result = self._real(repo).handle(
            self._bash("git commit -m x remote-docs/example.com/bad.md")
        )

        assert result.decision is Decision.ALLOW


class TestPathspecViewIsUsedOnlyWhenTheReadingIsCertain:
    """Ledger 00474 N245 round 2: never judge LESS of the recorded tree than the index.

    The bad document is staged. Each command records it by a route the pathspec
    view cannot follow, so the gate must keep reading the index.
    """

    _git = staticmethod(TestEachCommitFormJudgesWhatItRecords._git)
    _real = staticmethod(TestEachCommitFormJudgesWhatItRecords._real)

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        self._git(root, "init")
        self._git(root, "config", "user.email", "t@example.com")
        self._git(root, "config", "user.name", "T")
        _write(root, "src/thing.py", "x = 1\n")
        self._git(root, "add", "-A")
        self._git(root, "commit", "-m", "initial")
        _write(root, "remote-docs/example.com/bad.md", "# prose, no provenance\n")
        self._git(root, "add", "remote-docs/example.com/bad.md")
        _write(root, "src/thing.py", "x = 2\n")
        return root

    @staticmethod
    def _hook(command: str, cwd: Path | None = None) -> dict[str, Any]:
        hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
        if cwd is not None:
            hook_input["cwd"] = str(cwd)
        return hook_input

    @pytest.mark.parametrize(
        "command",
        [
            "cd remote-docs/example.com && git commit -m x bad.md",
            "git -C remote-docs/example.com commit -m x bad.md",
            "(cd remote-docs/example.com; git commit -m x bad.md)",
            "git commit -m x src/thing.py && git commit -m y",
            "F=remote-docs/example.com/bad.md; git commit -m x src/thing.py $F",
            "git commit -m x src/thing.py nosuch.md",
            "git commit -m x nosuch.md",
        ],
    )
    def test_an_uncertain_reading_keeps_the_index(self, repo: Path, command: str) -> None:
        result = self._real(repo).handle(self._hook(command, repo))

        assert result.decision is Decision.DENY

    def test_diff_relative_does_not_misplace_a_named_document(self, repo: Path) -> None:
        self._git(repo, "config", "diff.relative", "true")
        directory = repo / "remote-docs" / "example.com"

        result = self._real(repo).handle(self._hook("git commit -m x bad.md", directory))

        assert result.decision is Decision.DENY
        assert "remote-docs/example.com/bad.md" in (result.reason or "")

    def test_a_document_removed_from_the_index_then_edited_is_recorded_from_disk(
        self, repo: Path
    ) -> None:
        _write(repo, "remote-docs/example.com/p.md", _VALID)
        self._git(repo, "add", "remote-docs/example.com/p.md")
        self._git(repo, "commit", "-m", "valid")
        self._git(repo, "rm", "--cached", "remote-docs/example.com/p.md")
        _write(repo, "remote-docs/example.com/p.md", "# prose now\n")

        result = self._real(repo).handle(
            self._hook("git commit -m x remote-docs/example.com/p.md", repo)
        )

        assert result.decision is Decision.DENY
        assert "remote-docs/example.com/p.md" in (result.reason or "")


class TestACommandThatStagesOrCommitsMoreThanOnce:
    """Ledger 00474 N246 and N307: the document judged is one the whole command records."""

    _git = staticmethod(TestEachCommitFormJudgesWhatItRecords._git)
    _real = staticmethod(TestEachCommitFormJudgesWhatItRecords._real)

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        self._git(root, "init")
        self._git(root, "config", "user.email", "t@example.com")
        self._git(root, "config", "user.name", "T")
        _write(root, "src/thing.py", "x = 1\n")
        _write(root, "src/other.py", "y = 1\n")
        self._git(root, "add", "-A")
        self._git(root, "commit", "-m", "initial")
        _write(root, "remote-docs/example.com/bad.md", "# prose, no provenance\n")
        return root

    def _decision(self, root: Path, command: str) -> Decision:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(root),
        }
        return self._real(root).handle(hook_input).decision

    @pytest.mark.parametrize(
        "command",
        [
            "git add remote-docs/example.com/bad.md && git commit -m x",
            "git add -A && git commit -m x",
            "git add remote-docs && git commit -m x",
            "git add remote-docs/example.com/bad.md; git commit -m x",
        ],
    )
    def test_a_document_the_same_command_adds_is_judged(self, repo: Path, command: str) -> None:
        assert self._decision(repo, command) is Decision.DENY

    def test_a_document_the_add_does_not_name_is_not_judged(self, repo: Path) -> None:
        assert self._decision(repo, "git add src/thing.py && git commit -m x") is Decision.ALLOW

    def test_the_second_commits_pathspec_is_judged(self, repo: Path) -> None:
        self._git(repo, "add", "remote-docs/example.com/bad.md")
        _write(repo, "src/other.py", "y = 2\n")

        command = "git commit -m x src/other.py; git commit -m y remote-docs/example.com/bad.md"

        assert self._decision(repo, command) is Decision.DENY

    def test_a_clean_pair_of_commits_is_allowed(self, repo: Path) -> None:
        _write(repo, "src/thing.py", "x = 2\n")
        _write(repo, "src/other.py", "y = 2\n")

        command = "git commit -m x src/thing.py; git commit -m y src/other.py"

        assert self._decision(repo, command) is Decision.ALLOW


class TestACommitInAnotherRepositoryIsNotJudgedAgainstThisOne:
    """Ledger 00474 N300: a nested worktree or other checkout owns its own index."""

    _git = staticmethod(TestEachCommitFormJudgesWhatItRecords._git)

    @pytest.fixture
    def repos(self, tmp_path: Path) -> tuple[Path, Path]:
        """The project (with a bad staged document) and another repository."""
        project = tmp_path / "project"
        other = tmp_path / "other"
        for root in (project, other):
            root.mkdir()
            self._git(root, "init")
            self._git(root, "config", "user.email", "t@example.com")
            self._git(root, "config", "user.name", "T")
            _write(root, "README.txt", "x\n")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-m", "initial")
        _write(project, "remote-docs/example.com/bad.md", "# prose, no provenance\n")
        self._git(project, "add", "-A")
        return project, other

    @staticmethod
    def _gate(project: Path) -> RemoteDocsCommitGateHandler:
        instance = RemoteDocsCommitGateHandler()
        instance.project_root_reader = lambda: project

        def refuse(_reading: CommitReading, _cwd: str | None) -> list[str]:
            raise AssertionError("the project's index was read for another repository's commit")

        instance.staged_reader = refuse
        return instance

    @staticmethod
    def _hook(command: str, cwd: Path) -> dict[str, Any]:
        return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}

    def test_a_hook_directory_in_another_repository_stands_down(
        self, repos: tuple[Path, Path]
    ) -> None:
        project, other = repos

        result = self._gate(project).handle(self._hook("git commit -m x", other))

        assert result.decision is Decision.ALLOW

    def test_a_nested_worktree_inside_the_project_stands_down(
        self, repos: tuple[Path, Path]
    ) -> None:
        project, _other = repos
        nested = project / "untracked" / "worktrees" / "wt"
        self._git(project, "worktree", "add", "-q", str(nested), "-b", "wt")

        result = self._gate(project).handle(self._hook("git commit -m x", nested))

        assert result.decision is Decision.ALLOW

    @pytest.mark.parametrize(
        "form", ["cd {other} && git commit -m x", "git -C {other} commit -m x"]
    )
    def test_a_command_that_moves_into_another_repository_stands_down(
        self, repos: tuple[Path, Path], form: str
    ) -> None:
        project, other = repos

        result = self._gate(project).handle(self._hook(form.format(other=other), project))

        assert result.decision is Decision.ALLOW

    @pytest.mark.parametrize(
        "form",
        [
            "cd {other} & git commit -m x",
            "cd {other}; git commit -m x",
            "cd {other} || true; git commit -m x",
        ],
    )
    def test_a_move_that_may_not_take_effect_is_still_judged(
        self, repos: tuple[Path, Path], form: str
    ) -> None:
        """The commit may run in the project, so the project's index is read."""
        project, other = repos
        instance = RemoteDocsCommitGateHandler()
        instance.project_root_reader = lambda: project

        result = instance.handle(self._hook(form.format(other=other), project))

        assert result.decision is Decision.DENY

    def test_a_hook_directory_in_another_repository_stands_down_despite_an_uncertain_move(
        self, repos: tuple[Path, Path]
    ) -> None:
        """Both places the commit could run are another repository."""
        project, other = repos

        result = self._gate(project).handle(self._hook("cd . & git commit -m x", other))

        assert result.decision is Decision.ALLOW

    def test_a_commit_in_the_project_is_still_judged(self, repos: tuple[Path, Path]) -> None:
        project, _other = repos
        instance = RemoteDocsCommitGateHandler()
        instance.project_root_reader = lambda: project

        result = instance.handle(self._hook("git commit -m x", project))

        assert result.decision is Decision.DENY

    def test_a_move_into_a_subdirectory_of_the_project_is_still_judged(
        self, repos: tuple[Path, Path]
    ) -> None:
        project, _other = repos
        instance = RemoteDocsCommitGateHandler()
        instance.project_root_reader = lambda: project

        result = instance.handle(self._hook("cd remote-docs && git commit -m x", project))

        assert result.decision is Decision.DENY

    def test_a_move_this_reading_cannot_state_is_still_judged(
        self, repos: tuple[Path, Path]
    ) -> None:
        project, _other = repos
        instance = RemoteDocsCommitGateHandler()
        instance.project_root_reader = lambda: project

        result = instance.handle(self._hook("cd $WHERE && git commit -m x", project))

        assert result.decision is Decision.DENY


class TestResilience:
    def test_an_unreadable_git_index_allows_the_commit(
        self, handler: RemoteDocsCommitGateHandler
    ) -> None:
        """A gate that cannot read the index must not block every commit."""

        def boom(_reading: CommitReading, _cwd: str | None) -> list[str]:
            raise OSError("no git here")

        handler.staged_reader = boom

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_the_real_staged_reader_survives_a_missing_repository(self, tmp_path: Path) -> None:
        """`git diff --cached` outside a repository must not block the commit.

        Patched BEFORE construction: the readers are bound in `__init__`, so
        a patch applied afterwards would not be seen — and the test would
        pass for the wrong reason.
        """
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            instance = RemoteDocsCommitGateHandler()

            assert instance.handle(_commit()).decision is Decision.ALLOW
