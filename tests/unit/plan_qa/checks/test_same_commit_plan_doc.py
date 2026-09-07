"""Tests for the same-commit-plan-doc check (Plan 00144; sins G1, E1)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.same_commit_plan_doc import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

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
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    (root / "src").mkdir()
    plan_dir = root / "CLAUDE" / "Plan" / "00042-widget"
    plan_dir.mkdir(parents=True)
    (plan_dir / "PLAN.md").write_text("# Plan 00042: Widget\n\n**Status**: In Progress\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _context(root: Path, message: str | None) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        gitfacts=GitFacts(root),
        commit_message=message,
    )


class TestSpec:
    def test_registered_for_commit_stage(self) -> None:
        assert CHECK.check_id == "same-commit-plan-doc"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.ADVISE
        assert set(CHECK.sins) == {"G1", "E1"}


class TestScope:
    def test_no_commit_message_returns_empty(self, repo: Path) -> None:
        context = CheckContext(
            project_root=repo, plan_dir_rel=_PLAN_DIR_REL, gitfacts=GitFacts(repo)
        )
        assert CHECK.run(context) == []

    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel=_PLAN_DIR_REL,
            commit_message="Plan 00042: did stuff",
        )
        assert CHECK.run(context) == []

    def test_message_with_no_plan_reference_is_clean(self, repo: Path) -> None:
        (root_src := repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        context = _context(repo, "Fix: unrelated bug")
        assert CHECK.run(context) == []
        assert root_src.exists()


class TestFindings:
    def test_src_change_without_plan_doc_update_advises(self, repo: Path) -> None:
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        context = _context(repo, "Plan 00042: implement thing")
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "same-commit-plan-doc"
        assert finding.level == Level.ADVISE
        assert "00042" in finding.message

    def test_src_change_with_plan_doc_update_is_clean(self, repo: Path) -> None:
        (repo / "src" / "thing.py").write_text("x = 1\n")
        (repo / "CLAUDE/Plan/00042-widget/PLAN.md").write_text(
            "# Plan 00042: Widget\n\n**Status**: Complete\n"
        )
        _git(repo, "add", "-A")
        context = _context(repo, "Plan 00042: implement thing")
        assert CHECK.run(context) == []

    def test_plan_doc_update_in_archive_location_counts(self, repo: Path) -> None:
        (repo / "src" / "thing.py").write_text("x = 1\n")
        completed = repo / "CLAUDE/Plan/Completed"
        completed.mkdir()
        _git(repo, "mv", "CLAUDE/Plan/00042-widget", "CLAUDE/Plan/Completed/00042-widget")
        _git(repo, "add", "-A")
        context = _context(repo, "Plan 00042: implement thing")
        assert CHECK.run(context) == []

    def test_no_src_tests_or_config_change_is_clean(self, repo: Path) -> None:
        (repo / "README.md").write_text("docs only\n")
        _git(repo, "add", "-A")
        context = _context(repo, "Plan 00042: docs only")
        assert CHECK.run(context) == []

    def test_tests_directory_change_counts(self, repo: Path) -> None:
        tests_dir = repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_thing.py").write_text("def test_x(): pass\n")
        _git(repo, "add", "-A")
        context = _context(repo, "Plan 00042: add test")
        findings = CHECK.run(context)
        assert len(findings) == 1

    def test_declared_source_dir_from_facade_counts(self, repo: Path) -> None:
        """A project-declared layout.source_dirs entry is honoured (Plan
        00288 Task 4.3): "main repo code dirs" is read from the
        ProjectLayout facade instead of the hardcoded src/tests/config
        triple."""
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        backend_dir = repo / "backend"
        backend_dir.mkdir()
        (backend_dir / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        layout = ProjectLayout(
            source_dirs=("backend",),
            test_dirs=("tests",),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed",),
        )
        context = CheckContext(
            project_root=repo,
            plan_dir_rel=_PLAN_DIR_REL,
            gitfacts=GitFacts(repo),
            commit_message="Plan 00042: implement thing",
            layout=layout,
        )
        findings = CHECK.run(context)
        assert len(findings) == 1


def _set_status(repo: Path, status: str) -> None:
    plan_md = repo / "CLAUDE" / "Plan" / "00042-widget" / "PLAN.md"
    plan_md.write_text(f"# Plan 00042: Widget\n\n**Status**: {status}\n", encoding="utf-8")


class TestStatusStillNotStarted:
    """Plan 00341 Phase 2: assert on CONTENT, not on the file being touched.

    Touching `PLAN.md` satisfies the original check, so a commit that adds a
    paragraph and leaves the header at `Not Started` passed it. The stronger
    property -- a plan cannot be `Not Started` once code ships for it -- costs
    nothing extra, because the staged blob is already in hand.
    """

    def test_shipping_code_for_a_not_started_plan_blocks(self, repo: Path) -> None:
        _set_status(repo, "Not Started")
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo, "Plan 00042: implement thing"))

        blocking = [f for f in findings if f.level == Level.BLOCK]
        assert len(blocking) == 1
        assert "Not Started" in blocking[0].message
        assert "In Progress" in blocking[0].remediation

    def test_touching_the_plan_doc_is_not_enough_to_satisfy_it(self, repo: Path) -> None:
        """The exact hole this task exists to close: an edit that leaves the
        header alone used to be indistinguishable from one that fixed it."""
        plan_md = repo / "CLAUDE" / "Plan" / "00042-widget" / "PLAN.md"
        plan_md.write_text(
            "# Plan 00042: Widget\n\n**Status**: Not Started\n\nA new paragraph.\n",
            encoding="utf-8",
        )
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo, "Plan 00042: implement thing"))

        assert [f for f in findings if f.level == Level.BLOCK]

    def test_an_in_progress_plan_does_not_block(self, repo: Path) -> None:
        _set_status(repo, "In Progress")
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo, "Plan 00042: implement thing"))

        assert not [f for f in findings if f.level == Level.BLOCK]

    def test_a_staged_status_flip_satisfies_it_in_the_same_commit(self, repo: Path) -> None:
        """The staged blob is what counts, not what is on HEAD -- otherwise
        the remediation ("flip the status in this same commit") could not be
        satisfied by doing exactly that."""
        _set_status(repo, "Not Started")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "park it")
        _set_status(repo, "In Progress")
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo, "Plan 00042: implement thing"))

        assert not [f for f in findings if f.level == Level.BLOCK]

    def test_a_plan_named_only_in_the_body_is_spared(self, repo: Path) -> None:
        """Measured, not assumed. Over this repository's last 250 commits an
        unscoped content rule fired 4 times and one was a commit that merely
        REFERENCED another plan ("filed the gap as Plan 00342") while
        delivering a different one -- a 25% false-positive rate, fatal for a
        BLOCK. Scoping to the SUBJECT line removed it: 2 fires, both genuine,
        none spurious. This test is that decision, pinned.
        """
        _set_status(repo, "Not Started")
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        message = "Some other work: fix a thing\n\nFiled the follow-up as Plan 00042.\n"
        findings = CHECK.run(_context(repo, message))

        assert not [f for f in findings if f.level == Level.BLOCK]

    def test_a_missing_plan_doc_does_not_block(self, repo: Path) -> None:
        """A plan number with no PLAN.md anywhere cannot have a status, and
        inventing one would turn a typo in a commit message into a blocked
        commit."""
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo, "Plan 00099: implement thing"))

        assert not [f for f in findings if f.level == Level.BLOCK]
