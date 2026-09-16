"""Tests for the header-body-coherence check (Plan 00144; sins A3, A1)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.header_body_coherence import CHECKS
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Level, Stage


def _spec(stage: Stage) -> CheckSpec:
    """The one registration for ``stage`` — by stage, never by index.

    Plan 00419 N3 added a third surface between the existing two, so a
    positional lookup would have silently re-pointed every assertion in this
    module at a different stage.
    """
    return next(spec for spec in CHECKS if spec.stage is stage)


# The edit-time surface; the sweep twin is also covered by
# tests/unit/plan_qa/checks/test_document_rule_stage_parity.py.
CHECK = _spec(Stage.EDIT)
COMMIT_CHECK = _spec(Stage.COMMIT)
SWEEP_CHECK = _spec(Stage.SWEEP)

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_COHERENT_IN_PROGRESS = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [ ] task\n"
_NOT_STARTED_ALL_CHECKED = "# Plan 00042: Widget\n\n**Status**: Not Started\n\n- [x] task\n"
_IN_PROGRESS_DONE_MARKER = (
    "# Plan 00042: Widget\n\n**Status**: In Progress\n\nAll tasks complete.\n- [x] task\n"
)
_COMPLETE_ALL_CHECKED = "# Plan 00042: Widget\n\n**Status**: Complete\n\n- [x] task\n"
_NOT_STARTED_PARTIALLY_CHECKED = (
    "# Plan 00042: Widget\n\n**Status**: Not Started\n\n- [x] done\n- [ ] todo\n"
)
_IN_PROGRESS_PARTIALLY_CHECKED = (
    "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [x] done\n- [ ] todo\n"
)


def _context(
    file_rel: str,
    content: str,
    exists_before: bool = False,
    legacy: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=_PROJECT_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        file_path=_PROJECT_ROOT / file_rel,
        file_content=content,
        file_exists_before=exists_before,
    )


class TestSpec:
    def test_registered_for_edit_stage(self) -> None:
        assert CHECK.check_id == "header-body-coherence"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.BLOCK
        assert CHECK.sins == ("A3", "A1")


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/notes.md", _NOT_STARTED_ALL_CHECKED)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_coherent_in_progress_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _COHERENT_IN_PROGRESS)
        assert CHECK.run(context) == []

    def test_complete_status_with_all_checked_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _COMPLETE_ALL_CHECKED)
        assert CHECK.run(context) == []

    def test_not_started_with_all_checked_advises(self) -> None:
        """Plan 00419 N3: the completion branch ADVISES at edit time.

        A block here would deny the only legal close path -- see
        TestTheCompletionBranchAdvisesAtEditTime below for the argument. The
        finding is still raised; it just does not stop the write.
        """
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _NOT_STARTED_ALL_CHECKED)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "header-body-coherence"
        assert finding.level == Level.ADVISE
        assert "Complete" in finding.remediation

    def test_in_progress_with_done_marker_advises(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _IN_PROGRESS_DONE_MARKER)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_not_started_with_some_boxes_ticked_blocks(self) -> None:
        """Plan 00341 Task 1.1: a single tick falsifies "not started".

        No history is needed to see this -- the document contradicts itself on
        its own. The plan that motivated the check sat at `Not Started` for
        five days with work already shipped against it, which is invisible to
        the all-checked branch below.
        """
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _NOT_STARTED_PARTIALLY_CHECKED)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "header-body-coherence"
        assert finding.level == Level.BLOCK
        assert "In Progress" in finding.remediation
        assert "started" in finding.message

    def test_in_progress_with_some_boxes_ticked_passes(self) -> None:
        """The matched pair for the test above, and the one that stops the new
        branch firing on every healthy in-flight plan -- which is how this
        change would go wrong."""
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _IN_PROGRESS_PARTIALLY_CHECKED)
        assert CHECK.run(context) == []

    def test_not_started_with_all_checked_still_reports_completion(self) -> None:
        """Both branches match a `Not Started` plan with every box ticked.

        "You finished this" is the more useful correction than "you started
        this", so the completion branch wins. Pinned rather than left
        incidental, because the ordering is the whole difference between a
        remediation that helps and one that tells the author to mark a
        half-done plan Complete.
        """
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _NOT_STARTED_ALL_CHECKED)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert "Complete" in findings[0].remediation

    def test_legacy_allowlisted_plan_advises_instead(self) -> None:
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            _NOT_STARTED_ALL_CHECKED,
            exists_before=True,
            legacy=frozenset({42}),
        )
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestTheCompletionBranchAdvisesAtEditTime:
    """Plan 00419 N3 — a gate no legal sequence of moves can satisfy.

    Closing a plan requires two changes to one ``PLAN.md``: tick the last
    Success Criterion, and flip the status header. The ``Edit`` tool replaces
    ONE contiguous span, and the header (line 3) and the criteria (near the
    end) are never one span, so the two changes cannot land in one call.

    Both orderings were denied:

    - tick the criterion first -> every box ticked under ``In Progress``,
      denied HERE;
    - flip the header first -> ``Complete`` with the holding-area criterion
      still unticked, denied by this project's own
      ``plan_done_requires_holding_area`` handler.

    The only single-call move left was a whole-file ``Write``, which is
    exactly what ``R-WRITE-CLOBBER`` exists to discourage on a document this
    load-bearing.

    The all-ticked-under-``In Progress`` state is therefore the MANDATORY
    intermediate on the legal path, and denying a mandatory intermediate is a
    defect rather than a policy. The invariant itself is not relaxed: it moves
    to the surfaces that see a SETTLED state -- the commit gate and the sweep
    -- where "finished work still marked In Progress" is real rot rather than
    a half-finished edit.
    """

    def test_the_started_branch_still_blocks_at_edit(self) -> None:
        """Only the completion branch moves.

        ``Not Started`` with some boxes ticked has a legal one-call fix (flip
        the header; no box is being ticked in that same edit), so it is not
        part of the sequencing problem.
        """
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _NOT_STARTED_PARTIALLY_CHECKED)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK

    def test_the_sweep_still_blocks_on_completion(self) -> None:
        """The sweep judges what is settled on disk, so it keeps its teeth."""
        assert SWEEP_CHECK.stage is Stage.SWEEP
        assert SWEEP_CHECK.level == Level.BLOCK

    def test_the_edit_registration_is_still_nominally_blocking(self) -> None:
        """The spec's nominal level describes its strongest finding.

        The started branch still blocks from this registration, so declaring
        it ADVISE would understate it in generated documentation.
        """
        assert CHECK.level == Level.BLOCK


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
    folder = root / "CLAUDE" / "Plan" / "00042-widget"
    folder.mkdir(parents=True)
    (folder / "PLAN.md").write_text(_IN_PROGRESS_PARTIALLY_CHECKED)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _commit_context(root: Path, legacy: frozenset[int] = frozenset()) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        gitfacts=GitFacts(root),
    )


def _stage(repo: Path, content: str) -> None:
    (repo / "CLAUDE/Plan/00042-widget/PLAN.md").write_text(content)
    _git(repo, "add", "-A")


class TestTheCommitGateHoldsTheInvariant:
    """Where the teeth went. Without this the move would be a net loosening.

    An all-ticked ``In Progress`` plan committed to history was previously
    caught only by the NEXT session's sweep, because this check had no commit
    registration at all.
    """

    def test_registered_for_commit_stage(self) -> None:
        assert COMMIT_CHECK.check_id == "header-body-coherence"
        assert COMMIT_CHECK.stage is Stage.COMMIT
        assert COMMIT_CHECK.level == Level.BLOCK
        assert COMMIT_CHECK.sins == ("A3", "A1")

    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert COMMIT_CHECK.run(context) == []

    def test_nothing_staged_is_clean(self, repo: Path) -> None:
        assert COMMIT_CHECK.run(_commit_context(repo)) == []

    def test_committing_an_all_ticked_in_progress_plan_blocks(self, repo: Path) -> None:
        _stage(repo, "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [x] done\n- [x] also\n")
        findings = COMMIT_CHECK.run(_commit_context(repo))
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "header-body-coherence"
        assert finding.level == Level.BLOCK
        assert finding.path == "CLAUDE/Plan/00042-widget/PLAN.md"

    def test_the_legal_close_is_not_blocked(self, repo: Path) -> None:
        """The whole point: the sequence the edit stage now permits must commit.

        Tick the last box (advisory), flip the header, commit. The staged
        document is coherent, so nothing fires.
        """
        _stage(repo, "# Plan 00042: Widget\n\n**Status**: Complete\n\n- [x] done\n- [x] also\n")
        assert COMMIT_CHECK.run(_commit_context(repo)) == []

    def test_a_partially_ticked_in_progress_plan_is_clean(self, repo: Path) -> None:
        _stage(repo, "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [x] done\n- [ ] todo\n")
        assert COMMIT_CHECK.run(_commit_context(repo)) == []

    def test_inherited_incoherence_advises_rather_than_traps(self, repo: Path) -> None:
        """Plan 00343's rule: a commit is blamed for what IT introduced.

        A plan already committed in the violating state must not deny every
        later commit that touches it -- including the one repairing something
        else in the same file.
        """
        violating = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [x] done\n- [x] also\n"
        _stage(repo, violating)
        _git(repo, "commit", "--no-verify", "-m", "pre-existing violation")
        _stage(repo, violating + "\nAn unrelated paragraph.\n")

        findings = COMMIT_CHECK.run(_commit_context(repo))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_a_non_plan_file_is_ignored(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00042-widget/notes.md").write_text(_NOT_STARTED_ALL_CHECKED)
        _git(repo, "add", "-A")
        assert COMMIT_CHECK.run(_commit_context(repo)) == []

    def test_legacy_allowlisted_plan_advises_instead(self, repo: Path) -> None:
        _stage(repo, "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [x] done\n- [x] also\n")
        findings = COMMIT_CHECK.run(_commit_context(repo, legacy=frozenset({42})))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
