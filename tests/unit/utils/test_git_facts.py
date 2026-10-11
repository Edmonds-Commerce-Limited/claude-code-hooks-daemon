"""Tests for the shared read-only git facts.

Plan 00444, from ledger 00422 N14. The class began in ``plan_qa`` and grew a
``docs_qa`` caller, which made docs QA depend on plan QA for git plumbing that
has nothing to do with plans. The generic core lives here; ``plan_qa`` keeps a
subclass for the one plan-specific accessor.

These tests exercise the base directly against a real repository, because the
whole value of the class is that it reports what git reports. ``plan_qa``'s own
``test_gitfacts.py`` still covers the subclass and is deliberately left
untouched — if the public surface moved, it would say so.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_commit_parsing import read_commit_form
from claude_code_hooks_daemon.utils.git_facts import (
    GitFactsBase,
    StagedChange,
    commit_facts,
    project_relative_head_text,
)
from tests.support.git_fixtures import run_git as _git


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one committed file and one staged addition."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "committed.md").write_text("original\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    (root / "added.md").write_text("new\n", encoding="utf-8")
    _git(root, "add", "-A")
    return root


class TestStagedChanges:
    def test_a_staged_addition_is_reported(self, repo: Path) -> None:
        changes = GitFactsBase(repo).staged_changes()

        assert changes == (StagedChange(status="A", path="added.md", old_path=None),)

    def test_a_rename_carries_both_paths(self, repo: Path) -> None:
        _git(repo, "mv", "committed.md", "renamed.md")

        statuses = {
            change.status[0]: (change.old_path, change.path)
            for change in GitFactsBase(repo).staged_changes()
        }

        assert statuses["R"] == ("committed.md", "renamed.md")

    def test_it_is_read_from_git_once_per_instance(self, repo: Path) -> None:
        """Memoised: the commit gate asks once per plan folder."""
        facts = GitFactsBase(repo)
        first = facts.staged_changes()

        (repo / "later.md").write_text("later\n", encoding="utf-8")
        _git(repo, "add", "-A")

        assert facts.staged_changes() is first

    def test_a_fresh_instance_sees_the_newer_state(self, repo: Path) -> None:
        """The control for memoisation: it is per-instance, not global."""
        GitFactsBase(repo).staged_changes()
        (repo / "later.md").write_text("later\n", encoding="utf-8")
        _git(repo, "add", "-A")

        paths = {change.path for change in GitFactsBase(repo).staged_changes()}

        assert "later.md" in paths


class TestPathspecScoping:
    """``git commit <pathspec>`` commits those paths' WORKING TREE content."""

    def test_an_unstaged_named_path_is_still_seen(self, repo: Path) -> None:
        (repo / "committed.md").write_text("modified but not staged\n", encoding="utf-8")

        facts = GitFactsBase(repo, pathspecs=["committed.md"])

        assert [change.path for change in facts.staged_changes()] == ["committed.md"]

    def test_a_staged_but_unnamed_path_is_excluded(self, repo: Path) -> None:
        (repo / "committed.md").write_text("modified but not staged\n", encoding="utf-8")

        facts = GitFactsBase(repo, pathspecs=["committed.md"])

        assert "added.md" not in {change.path for change in facts.staged_changes()}


class TestFileText:
    def test_staged_text_comes_from_the_index(self, repo: Path) -> None:
        assert GitFactsBase(repo).staged_file_text("added.md") == "new\n"

    def test_head_text_comes_from_the_commit(self, repo: Path) -> None:
        (repo / "committed.md").write_text("changed\n", encoding="utf-8")
        _git(repo, "add", "-A")

        assert GitFactsBase(repo).head_file_text("committed.md") == "original\n"

    def test_an_unknown_path_is_none_rather_than_an_error(self, repo: Path) -> None:
        """A non-zero git exit is "fact not available", not a failure."""
        assert GitFactsBase(repo).staged_file_text("nope.md") is None


class TestStagedPathsUnder:
    def test_it_filters_by_prefix_and_sorts(self, repo: Path) -> None:
        (repo / "docs").mkdir()
        (repo / "docs" / "b.md").write_text("b\n", encoding="utf-8")
        (repo / "docs" / "a.md").write_text("a\n", encoding="utf-8")
        _git(repo, "add", "-A")

        assert GitFactsBase(repo).staged_paths_under("docs") == ("docs/a.md", "docs/b.md")

    def test_a_prefix_matching_nothing_is_empty(self, repo: Path) -> None:
        assert GitFactsBase(repo).staged_paths_under("absent") == ()


class TestLastCommitDate:
    def test_a_committed_path_has_a_date(self, repo: Path) -> None:
        assert GitFactsBase(repo).last_commit_date("committed.md") is not None

    def test_a_never_committed_path_is_none(self, repo: Path) -> None:
        assert GitFactsBase(repo).last_commit_date("added.md") is None


class TestItIsStrictlyReadOnly:
    def test_reading_facts_leaves_the_index_unchanged(self, repo: Path) -> None:
        """The whole class is read-only; nothing here may stage or commit."""
        facts = GitFactsBase(repo)
        before = {change.path for change in facts.staged_changes()}

        facts.staged_file_text("added.md")
        facts.head_file_text("committed.md")
        facts.last_commit_date("committed.md")

        assert {change.path for change in GitFactsBase(repo).staged_changes()} == before


class TestProjectRelativeHeadText:
    """Ledger 00466 N3: the shared HEAD-comparison helper both
    ``goal_injection`` and ``recovery_cron_advisor`` use for their
    transition checks. Review nit n3: ``project_root`` is a plain
    parameter -- this module stays core-free -- so these tests pass it
    directly rather than monkeypatching ``ProjectContext``."""

    def test_a_committed_path_returns_its_head_content(self, repo: Path) -> None:
        (repo / "committed.md").write_text("changed\n", encoding="utf-8")

        assert project_relative_head_text(repo / "committed.md", repo) == "original\n"

    def test_a_never_committed_path_is_none(self, repo: Path) -> None:
        assert project_relative_head_text(repo / "added.md", repo) is None

    def test_a_path_outside_the_project_root_is_none(self, tmp_path: Path, repo: Path) -> None:
        outside = tmp_path / "outside.md"
        outside.write_text("x\n", encoding="utf-8")

        assert project_relative_head_text(outside, repo) is None

    def test_a_nested_path_resolves_correctly(self, repo: Path) -> None:
        nested_dir = repo / "CLAUDE" / "Plan" / "00042-my-plan"
        nested_dir.mkdir(parents=True)
        nested = nested_dir / "PLAN.md"
        nested.write_text("**Status**: Complete\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "add plan")
        nested.write_text("**Status**: Complete\n\nMore.\n", encoding="utf-8")

        assert project_relative_head_text(nested, repo) == "**Status**: Complete\n"

    def test_a_file_in_a_nested_repository_reads_from_its_OWN_head(self, repo: Path) -> None:
        """Ledger 00466 review m5: a file under the project root can belong
        to a DIFFERENT git repository (a linked worktree, a nested clone).
        HEAD must come from THAT repo, not the project root's -- which never
        tracks the nested path at all, so it always answered "absent" and a
        write there was silently misread as a genuine transition."""
        nested = repo / "untracked" / "worktrees" / "wt"
        nested.mkdir(parents=True)
        _git(nested, "init")
        _git(nested, "config", "user.email", "t@example.com")
        _git(nested, "config", "user.name", "T")
        plan_dir = nested / "CLAUDE" / "Plan" / "00301-fourth"
        plan_dir.mkdir(parents=True)
        plan_md = plan_dir / "PLAN.md"
        plan_md.write_text("**Status**: In Progress\n", encoding="utf-8")
        _git(nested, "add", "-A")
        _git(nested, "commit", "-m", "flip")
        plan_md.write_text("**Status**: In Progress\n\nmore\n", encoding="utf-8")

        assert project_relative_head_text(plan_md, repo) == "**Status**: In Progress\n"


class TestIndexListing:
    """Ledger 00474 N244: the tree a commit WILL record, read from the index."""

    def test_lists_every_indexed_path_under_the_prefix(self, repo: Path) -> None:
        (repo / "sub").mkdir()
        (repo / "sub" / "a.md").write_text("a\n", encoding="utf-8")
        _git(repo, "add", "-A")

        listing = GitFactsBase(repo).index_listing("sub")

        assert listing is not None
        assert set(listing) == {"sub/a.md"}

    def test_an_unstaged_deletion_is_still_listed(self, repo: Path) -> None:
        (repo / "committed.md").unlink()

        listing = GitFactsBase(repo).index_listing(".")

        assert listing is not None
        assert "committed.md" in listing

    def test_a_cached_removal_is_not_listed_though_the_file_remains(self, repo: Path) -> None:
        _git(repo, "rm", "--cached", "-q", "committed.md")

        listing = GitFactsBase(repo).index_listing(".")

        assert listing is not None
        assert "committed.md" not in listing
        assert (repo / "committed.md").is_file()

    def test_is_read_with_a_single_git_call(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.utils.git_repo import run_git as real

        calls: list[tuple[str, ...]] = []

        def recording(
            cwd: Path,
            *args: str,
            timeout: float = Timeout.GIT_CONTEXT,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return real(cwd, *args, timeout=timeout, env=env)

        monkeypatch.setattr("claude_code_hooks_daemon.utils.git_facts.run_git", recording)
        facts = GitFactsBase(repo)
        facts.index_listing(".")
        facts.index_listing(".")

        assert len(calls) == 1

    def test_not_a_repository_is_unavailable(self, tmp_path: Path) -> None:
        assert GitFactsBase(tmp_path).index_listing(".") is None


class TestIndexTexts:
    def test_returns_the_staged_content_not_the_working_tree_content(self, repo: Path) -> None:
        (repo / "added.md").write_text("edited after staging\n", encoding="utf-8")
        facts = GitFactsBase(repo)
        listing = facts.index_listing(".")
        assert listing is not None

        texts = facts.index_texts(listing, ["added.md", "committed.md"])

        assert texts == {"added.md": "new\n", "committed.md": "original\n"}

    def test_a_path_not_in_the_listing_is_omitted(self, repo: Path) -> None:
        facts = GitFactsBase(repo)
        listing = facts.index_listing(".")
        assert listing is not None

        assert facts.index_texts(listing, ["missing.md"]) == {}

    def test_non_utf8_bytes_do_not_shift_later_blobs(self, repo: Path) -> None:
        (repo / "binary.md").write_bytes(b"\xff\xfe broken\n")
        (repo / "after.md").write_text("after\n", encoding="utf-8")
        _git(repo, "add", "-A")
        facts = GitFactsBase(repo)
        listing = facts.index_listing(".")
        assert listing is not None

        texts = facts.index_texts(listing, ["binary.md", "after.md"])

        assert texts is not None
        assert texts["after.md"] == "after\n"
        assert "broken" in texts["binary.md"]

    def test_empty_request_spawns_nothing_and_returns_nothing(self, repo: Path) -> None:
        assert GitFactsBase(repo).index_texts({}, []) == {}


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def messy(tmp_path: Path) -> Path:
    """A repository whose index, working tree and HEAD all disagree.

    a: staged edit, then a different working-tree edit (named by the commits)
    b: staged edit only                                     (never named)
    new: staged addition                                    (never named)
    c: unstaged edit                                        (named)
    e: deleted on disk, unstaged                            (named)
    f: staged edit, working tree put back to HEAD           (named)
    g: staged deletion                                      (never named)
    """
    root = tmp_path / "messy"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    for name in ("d/a.txt", "d/b.txt", "c.txt", "e.txt", "f.txt", "g.txt"):
        _write(root, name, "head\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    _write(root, "d/a.txt", "staged-a\n")
    _write(root, "d/b.txt", "staged-b\n")
    _write(root, "d/new.txt", "staged-new\n")
    _write(root, "f.txt", "staged-f\n")
    _git(root, "add", "-A")
    _git(root, "rm", "-q", "g.txt")
    _write(root, "d/a.txt", "worktree-a\n")
    _write(root, "c.txt", "worktree-c\n")
    (root / "e.txt").unlink()
    _write(root, "f.txt", "head\n")
    return root


def _tree_after_a_real_commit(root: Path, *commit_args: str) -> dict[str, str]:
    """Make the real commit and read what it recorded: path -> text."""
    _git(root, "commit", "-q", "-m", "x", *commit_args)
    names = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", "-z", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    return {
        name: subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{name}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for name in names
        if name
    }


def _predicted_tree(facts: GitFactsBase) -> dict[str, str]:
    listing = facts.index_listing(".")
    assert listing is not None
    texts = facts.index_texts(listing, list(listing))
    assert texts is not None
    return texts


_NAMED = ["d/a.txt", "c.txt", "e.txt", "f.txt"]


class TestTheRecordedTreeOfEachCommitForm:
    """Ledger 00474 N245: a pathspec commit records a tree the index does not hold.

    Every case here makes the REAL commit and compares what git recorded with
    what the facts predicted beforehand, so the semantics are git's own and not
    this module's reading of them.
    """

    def test_bare_commit_is_the_index(self, messy: Path) -> None:
        predicted = _predicted_tree(GitFactsBase(messy))

        assert predicted == _tree_after_a_real_commit(messy)

    @pytest.mark.parametrize("pathspecs", [_NAMED, ["d", "c.txt", "e.txt", "f.txt"]])
    def test_pathspec_commit_is_head_with_the_named_working_tree_content(
        self, messy: Path, pathspecs: list[str]
    ) -> None:
        predicted = _predicted_tree(GitFactsBase(messy, pathspecs=pathspecs))

        recorded = _tree_after_a_real_commit(messy, *pathspecs)
        assert predicted == recorded
        # The cases that tell it from the index, spelled out.
        assert recorded["d/a.txt"] == "worktree-a\n"
        assert recorded["d/b.txt"] == ("staged-b\n" if "d" in pathspecs else "head\n")
        assert recorded["f.txt"] == "head\n"
        assert "e.txt" not in recorded
        assert recorded["g.txt"] == "head\n"

    @pytest.mark.parametrize("pathspecs", [_NAMED, ["d/a.txt", "c.txt", "e.txt", "f.txt", "d"]])
    def test_include_commit_is_the_index_with_the_named_working_tree_content(
        self, messy: Path, pathspecs: list[str]
    ) -> None:
        predicted = _predicted_tree(GitFactsBase(messy, pathspecs=pathspecs, include=True))

        recorded = _tree_after_a_real_commit(messy, "--include", *pathspecs)
        assert predicted == recorded
        assert recorded["d/b.txt"] == "staged-b\n"
        assert recorded["d/new.txt"] == "staged-new\n"
        assert "g.txt" not in recorded

    def test_include_leaves_an_unnamed_staged_change_at_its_index_content(
        self, messy: Path
    ) -> None:
        pathspecs = ["c.txt"]

        predicted = _predicted_tree(GitFactsBase(messy, pathspecs=pathspecs, include=True))

        recorded = _tree_after_a_real_commit(messy, "-i", *pathspecs)
        assert predicted == recorded
        assert recorded["d/a.txt"] == "staged-a\n"
        assert recorded["f.txt"] == "staged-f\n"
        assert recorded["c.txt"] == "worktree-c\n"

    def test_a_working_tree_listing_entry_is_read_from_the_disk(self, messy: Path) -> None:
        facts = GitFactsBase(messy, pathspecs=["d/a.txt"])
        listing = facts.index_listing(".")
        assert listing is not None

        assert facts.index_texts(listing, ["d/a.txt"]) == {"d/a.txt": "worktree-a\n"}

    @pytest.mark.parametrize(
        ("pathspecs", "include"), [(_NAMED, False), (_NAMED, True), (["c.txt"], True)]
    )
    def test_staged_changes_are_the_paths_the_commit_changes(
        self, messy: Path, pathspecs: list[str], include: bool
    ) -> None:
        facts = GitFactsBase(messy, pathspecs=pathspecs, include=include)
        predicted = {change.path for change in facts.staged_changes()}

        _git(messy, "commit", "-q", "-m", "x", *(["-i"] if include else []), *pathspecs)
        changed = subprocess.run(
            ["git", "-C", str(messy), "diff", "--name-only", "-z", "HEAD~1", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split("\0")
        assert predicted == {name for name in changed if name}

    def test_recorded_text_follows_where_the_commit_takes_each_path_from(self, messy: Path) -> None:
        include = GitFactsBase(messy, pathspecs=["d/a.txt"], include=True)
        only = GitFactsBase(messy, pathspecs=["d/a.txt"])
        bare = GitFactsBase(messy)

        assert include.recorded_text("d/a.txt") == "worktree-a\n"
        assert include.recorded_text("d/b.txt") == "staged-b\n"
        assert only.recorded_text("d/a.txt") == "worktree-a\n"
        assert bare.recorded_text("d/a.txt") == "staged-a\n"

    def test_named_paths_are_what_the_pathspecs_select(self, messy: Path) -> None:
        facts = GitFactsBase(messy, pathspecs=["d", "c.txt"], include=True)

        assert facts.named_paths() == frozenset({"d/a.txt", "d/b.txt", "d/new.txt", "c.txt"})

    @pytest.mark.parametrize("include", [False, True])
    def test_a_listing_is_limited_to_its_prefix(self, messy: Path, include: bool) -> None:
        facts = GitFactsBase(messy, pathspecs=["d/a.txt", "c.txt"], include=include)

        listing = facts.index_listing("d")

        assert listing is not None
        assert set(listing) <= {"d/a.txt", "d/b.txt", "d/new.txt"}
        assert listing["d/a.txt"] == "working-tree"
        assert ("d/new.txt" in listing) is include

    def test_the_unnamed_staged_changes_join_the_named_ones_under_include(
        self, messy: Path
    ) -> None:
        facts = GitFactsBase(messy, pathspecs=["c.txt"], include=True)

        assert {change.path: change.status for change in facts.staged_changes()} == {
            "c.txt": "M",
            "d/a.txt": "M",
            "d/b.txt": "M",
            "d/new.txt": "A",
            "f.txt": "M",
            "g.txt": "D",
        }

    def test_an_unreadable_repository_is_unavailable_not_empty(self, tmp_path: Path) -> None:
        facts = GitFactsBase(tmp_path, pathspecs=["x"])

        assert facts.index_listing(".") is None
        assert facts.named_paths() is None

    def test_a_working_tree_file_that_cannot_be_read_makes_the_texts_unavailable(
        self, messy: Path
    ) -> None:
        facts = GitFactsBase(messy, pathspecs=["d/a.txt"])
        listing = facts.index_listing(".")
        assert listing is not None
        (messy / "d" / "a.txt").unlink()

        assert facts.index_texts(listing, ["d/a.txt"]) is None


class TestCommitFactsNarrowsOnlyWhenCertain:
    """Ledger 00474 N245 round 2: the pathspec view is used only on a certain reading."""

    @staticmethod
    def _staged_paths(facts: GitFactsBase) -> set[str]:
        return {change.path for change in facts.staged_changes()}

    def test_a_certain_reading_is_the_named_paths_only(self, messy: Path) -> None:
        facts = commit_facts(read_commit_form("git commit -m x c.txt"), messy)

        assert self._staged_paths(facts) == {"c.txt"}
        assert facts.union is False

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x c.txt nosuch.txt",
            "git commit -m x c.txt && git commit -m y",
        ],
    )
    def test_an_uncertain_reading_is_the_index_plus_the_named_paths(
        self, messy: Path, command: str
    ) -> None:
        facts = commit_facts(read_commit_form(command), messy)

        assert facts.union is True
        assert {"c.txt", "d/b.txt", "d/new.txt"} <= self._staged_paths(facts)

    def test_a_moved_reading_is_the_index_plus_the_paths_named_where_it_moved_to(
        self, messy: Path
    ) -> None:
        """Ledger 00474 N299: after ``cd d`` the pathspec ``a.txt`` is ``d/a.txt``."""
        _write(messy, "d/e2.txt", "head\n")
        _git(messy, "add", "d/e2.txt")
        _git(messy, "commit", "-q", "-m", "e2", "--only", "d/e2.txt")
        _write(messy, "d/e2.txt", "unstaged-edit\n")

        facts = commit_facts(read_commit_form("cd d && git commit -m x e2.txt"), messy, messy)

        assert facts.union is True
        # e2.txt is modified but NOT staged: only a read from d/ names it.
        assert {"d/e2.txt", "d/b.txt", "d/new.txt"} <= self._staged_paths(facts)
        assert "c.txt" not in self._staged_paths(facts)

    def test_a_bare_commit_is_the_index(self, messy: Path) -> None:
        facts = commit_facts(read_commit_form("git commit -m x"), messy)

        assert "c.txt" not in self._staged_paths(facts)
        assert "d/b.txt" in self._staged_paths(facts)

    def test_a_cwd_outside_the_repository_reads_pathspecs_from_the_root(
        self, messy: Path, tmp_path: Path
    ) -> None:
        facts = commit_facts(read_commit_form("git commit -m x c.txt"), messy, tmp_path)

        assert self._staged_paths(facts) == {"c.txt"}

    def test_a_subdirectory_cwd_names_paths_from_the_root_despite_diff_relative(
        self, messy: Path
    ) -> None:
        _git(messy, "config", "diff.relative", "true")

        facts = commit_facts(read_commit_form("git commit -m x a.txt"), messy, messy / "d")

        assert self._staged_paths(facts) == {"d/a.txt"}

    def test_a_fresh_repository_without_head_still_judges_the_index(self, tmp_path: Path) -> None:
        root = tmp_path / "fresh"
        root.mkdir()
        _git(root, "init")
        _write(root, "a.txt", "x\n")
        _git(root, "add", "a.txt")

        facts = commit_facts(read_commit_form("git commit -m x a.txt"), root)

        assert self._staged_paths(facts) == {"a.txt"}


class TestAPathRemovedFromTheIndexButOnDisk:
    """``git rm --cached p`` then an edit: ``git commit p`` records the working tree's ``p``."""

    @pytest.fixture
    def revived(self, tmp_path: Path) -> Path:
        root = tmp_path / "revived"
        root.mkdir()
        _git(root, "init")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "T")
        _write(root, "p.txt", "head\n")
        _write(root, "q.txt", "head\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        _git(root, "rm", "-q", "--cached", "p.txt")
        _write(root, "p.txt", "head\nedited\n")
        return root

    def test_it_is_a_modification_not_a_deletion(self, revived: Path) -> None:
        facts = GitFactsBase(revived, pathspecs=["p.txt"])

        assert [(c.status, c.path) for c in facts.staged_changes()] == [("M", "p.txt")]
        assert facts.resurrected_paths() == frozenset({"p.txt"})

    def test_the_predicted_tree_matches_the_real_commit(self, revived: Path) -> None:
        predicted = _predicted_tree(GitFactsBase(revived, pathspecs=["p.txt"]))

        assert predicted == _tree_after_a_real_commit(revived, "p.txt")

    def test_a_deletion_the_disk_confirms_stays_a_deletion(self, revived: Path) -> None:
        (revived / "p.txt").unlink()

        facts = GitFactsBase(revived, pathspecs=["p.txt"])

        assert facts.resurrected_paths() == frozenset()

    def test_a_bare_commit_has_none(self, revived: Path) -> None:
        assert GitFactsBase(revived).resurrected_paths() == frozenset()
