"""Tests for the archived-status-coherence check (Plan 00286; sins C1, C2).

Reproduces the field bug: `git mv` stages a plan folder's rename using the
INDEX's existing blob content. If a status flip to terminal was made in the
worktree but never re-`git add`ed, the STAGED content at the new (archived)
path can still read a non-terminal status even though the worktree file (and
`location-status-coherence`'s COMMIT-stage check, which reads the worktree
tree) already shows the fix.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.archived_status_coherence import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"

_IN_PROGRESS = "# Plan 00001: first\n\n**Status**: In Progress\n"
_COMPLETE = "# Plan 00001: first\n\n**Status**: Complete\n"
_CANCELLED = "# Plan 00001: first\n\n**Status**: Cancelled\n"
_NO_STATUS = "# Plan 00001: first\n\nNo status header here.\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    plan_dir = root / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "README.md").write_text("# Plans Index\n\n## Active Plans\n")
    (plan_dir / "00001-first").mkdir()
    (plan_dir / "00001-first" / "PLAN.md").write_text(_IN_PROGRESS)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _mkdir_completed(repo: Path) -> None:
    (repo / "CLAUDE/Plan/Completed").mkdir(parents=True, exist_ok=True)


def _context(root: Path, legacy: frozenset[int] = frozenset()) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        gitfacts=GitFacts(root),
    )


class TestSpec:
    def test_registered_for_commit_stage(self) -> None:
        assert CHECK.check_id == "archived-status-coherence"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.BLOCK
        assert set(CHECK.sins) == {"C1", "C2"}


class TestScope:
    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []

    def test_no_staged_changes_is_clean(self, repo: Path) -> None:
        assert CHECK.run(_context(repo)) == []

    def test_staged_change_outside_archive_dir_is_ignored(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(
            "# Plan 00001: first\n\n**Status**: In Progress\n\n- [x] did a thing\n"
        )
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []

    def test_staged_non_plan_md_change_is_ignored(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/README.md").write_text("# Plans Index (updated)\n")
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []

    def test_staged_deletion_under_archive_dir_is_ignored(self, repo: Path) -> None:
        """A rename immediately followed by a delete of the new path collapses to a
        plain ``D`` of the OLD path in ``git diff --cached``, which is neither an
        add/modify nor a rename — so it never reaches the archive-dir match at all.
        """
        _mkdir_completed(repo)
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        (repo / "CLAUDE/Plan/Completed/00001-first/PLAN.md").unlink()
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []

    def test_no_cancelled_dir_configured_still_matches_completed(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        _git(repo, "add", "-A")
        _mkdir_completed(repo)
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        context = CheckContext(
            project_root=repo,
            plan_dir_rel=_PLAN_DIR_REL,
            gitfacts=GitFacts(repo),
            cancelled_dir=None,
        )
        assert CHECK.run(context) == []


class TestFieldSequence:
    def test_git_mv_without_restaging_flip_blocks(self, repo: Path) -> None:
        """The exact field sequence: flip in worktree, `git mv`, no re-add."""
        plan_md = repo / "CLAUDE/Plan/00001-first/PLAN.md"
        # Status flip made in the worktree, but the file is git-mv'd BEFORE
        # this edit is ever staged — mirrors a `git mv` picking up the
        # current worktree bytes and staging a rename using them (which is
        # what `git mv` on a modified-but-unadded file actually does: it
        # stages the CURRENT worktree content under the new path). To
        # reproduce the narrower bug (stale INDEX blob riding a rename), we
        # commit the pre-flip content, THEN mv without adding the flip.
        _mkdir_completed(repo)
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        # `git mv` already staged the rename using the pre-flip ("In
        # Progress") blob. Now simulate the flip having been intended but
        # never re-added: overwrite the worktree file (post-move path) with
        # terminal content, but do NOT `git add` it.
        moved = repo / "CLAUDE/Plan/Completed/00001-first/PLAN.md"
        moved.write_text(_COMPLETE)
        # Worktree now shows Complete; STAGED content still reads In Progress.
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "archived-status-coherence"
        assert finding.level == Level.BLOCK
        assert "Completed" in finding.message
        assert "In Progress" in finding.message
        assert plan_md.exists() is False  # sanity: original path is gone


class TestCorrectAtomicArchive:
    def test_terminal_status_staged_with_move_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        _git(repo, "add", "-A")
        _mkdir_completed(repo)
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        assert CHECK.run(_context(repo)) == []

    def test_cancelled_status_staged_with_move_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_CANCELLED)
        _git(repo, "add", "-A")
        _mkdir_completed(repo)
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        assert CHECK.run(_context(repo)) == []


class TestFreshlyStagedIntoArchive:
    def test_new_file_staged_directly_into_archive_with_non_terminal_status_blocks(
        self, repo: Path
    ) -> None:
        completed = repo / "CLAUDE/Plan/Completed/00002-second"
        completed.mkdir(parents=True)
        (completed / "PLAN.md").write_text(_IN_PROGRESS.replace("00001", "00002"))
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK

    def test_new_file_staged_directly_into_archive_with_no_status_header_blocks(
        self, repo: Path
    ) -> None:
        completed = repo / "CLAUDE/Plan/Completed/00002-second"
        completed.mkdir(parents=True)
        (completed / "PLAN.md").write_text(_NO_STATUS.replace("00001", "00002"))
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        assert (
            "unknown" in findings[0].message.lower() or "unparseable" in findings[0].message.lower()
        )


class TestLegacyAllowlist:
    def test_legacy_allowlisted_downgrades_to_advise(self, repo: Path) -> None:
        _mkdir_completed(repo)
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        moved = repo / "CLAUDE/Plan/Completed/00001-first/PLAN.md"
        moved.write_text(_COMPLETE)
        findings = CHECK.run(_context(repo, legacy=frozenset({1})))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
