"""Tests for the row-folder-bijection tree check (Plan 00144; sins B1, B2, B7)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.row_folder_bijection import CHECKS
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.model import PlanTree
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"


def _make_folder(root: Path, name: str, sub: str = "") -> None:
    parent = root / sub if sub else root
    parent.mkdir(parents=True, exist_ok=True)
    folder = parent / name
    folder.mkdir()
    number = name.split("-")[0]
    (folder / "PLAN.md").write_text(f"# Plan {number}: Widget\n\n**Status**: In Progress\n")


def _context(
    tmp_path: Path,
    readme_text: str,
    legacy_plan_allowlist: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=tmp_path,
        plan_dir_rel=_PLAN_DIR_REL,
        tree=PlanTree.scan(tmp_path / _PLAN_DIR_REL),
        readme=ReadmeIndex.parse(readme_text),
        legacy_plan_allowlist=legacy_plan_allowlist,
    )


@pytest.fixture
def plan_root(tmp_path: Path) -> Path:
    root = tmp_path / _PLAN_DIR_REL
    root.mkdir(parents=True)
    (root / "Completed").mkdir()
    return root


class TestSpec:
    def test_both_specs_share_id_and_metadata(self) -> None:
        commit_spec, sweep_spec = CHECKS
        assert commit_spec.check_id == "row-folder-bijection"
        assert sweep_spec.check_id == "row-folder-bijection"
        assert {commit_spec.stage, sweep_spec.stage} == {Stage.COMMIT, Stage.SWEEP}
        assert commit_spec.level == Level.BLOCK
        assert commit_spec.sins == ("B1", "B2", "B7")
        assert commit_spec.run is sweep_spec.run


class TestTreeOrReadmeNone:
    def test_returns_empty_when_tree_missing(self) -> None:
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel=_PLAN_DIR_REL,
            readme=ReadmeIndex.parse("## Active Plans\n"),
        )
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_returns_empty_when_readme_missing(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = CheckContext(
            project_root=tmp_path,
            plan_dir_rel=_PLAN_DIR_REL,
            tree=PlanTree.scan(plan_root),
        )
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestClean:
    def test_matching_row_and_folder_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        readme = "## Active Plans\n\n- [00001: Alpha](00001-alpha/PLAN.md) - In Progress\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_completed_folder_in_completed_section_passes(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Completed")
        readme = (
            "## Completed Plans\n\n- [00001: Alpha](Completed/00001-alpha/PLAN.md) - Complete\n"
        )
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_other_location_folders_ignored(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Scratch")
        context = _context(tmp_path, "## Active Plans\n")
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestUnindexedFolder:
    def test_folder_with_no_row_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = _context(tmp_path, "## Active Plans\n")
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "no README index row" in findings[0].message
        assert findings[0].level == Level.BLOCK

    def test_legacy_allowlist_downgrades_unindexed(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = _context(tmp_path, "## Active Plans\n", legacy_plan_allowlist=frozenset({1}))
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestWrongSection:
    def test_root_folder_indexed_under_completed_blocks(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00001-alpha")
        readme = "## Completed Plans\n\n- [00001: Alpha](00001-alpha/PLAN.md) - Complete\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "section" in findings[0].message.lower()
        assert findings[0].level == Level.BLOCK


class TestBrokenLink:
    def test_link_to_missing_folder_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        readme = "## Active Plans\n\n- [00002: Ghost](00002-ghost/PLAN.md) - In Progress\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        messages = [f.message for f in findings]
        assert any("does not exist" in message for message in messages)


class TestOrphanRow:
    def test_row_with_no_folder_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        readme = "## Blocked Plans\n\n- **00099** - Waiting on approval\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert any("no folder" in f.message for f in findings)

    def test_legacy_allowlist_downgrades_orphan_row(self, plan_root: Path, tmp_path: Path) -> None:
        readme = "## Blocked Plans\n\n- **00099** - Waiting on approval\n"
        context = _context(tmp_path, readme, legacy_plan_allowlist=frozenset({99}))
        commit_spec, _sweep_spec = CHECKS
        findings = [f for f in commit_spec.run(context) if "no folder" in f.message]
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real repository whose HEAD already carries a clean plan tree."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    plan_root = root / _PLAN_DIR_REL
    plan_root.mkdir(parents=True)
    (plan_root / "Completed").mkdir()
    _make_folder(plan_root, "00001-alpha")
    (plan_root / "README.md").write_text(
        "## Active Plans\n\n- [00001: Alpha](00001-alpha/PLAN.md) - In Progress\n"
    )
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _commit_context(root: Path) -> CheckContext:
    plan_root = root / _PLAN_DIR_REL
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        tree=PlanTree.scan(plan_root),
        readme=ReadmeIndex.parse((plan_root / "README.md").read_text()),
        gitfacts=GitFacts(root),
    )


def _levels_for(root: Path, fragment: str) -> list[Level]:
    commit_spec, _sweep_spec = CHECKS
    return [f.level for f in commit_spec.run(_commit_context(root)) if fragment in f.message]


class TestACommitIsAnswerableOnlyForThePlansItTouches:
    """Plan 00343 Phase 3.

    Measured, not theorised: replaying this check over 250 commits denied SIX
    that had nothing to do with the plan they were blamed for — supervisor and
    venv-resolver work, all failing on one stale README row for plan 00311 that
    none of them touched. The failure is sticky, which is what makes it
    expensive: until somebody repairs the row, EVERY later commit is denied.

    The rule mirrors `index-row-length._worsens`, whose docstring already
    states the principle: an already-degraded index is never trapped.
    """

    def test_a_stale_row_the_commit_never_touched_only_advises(self, repo: Path) -> None:
        plan_root = repo / _PLAN_DIR_REL
        (plan_root / "README.md").write_text(
            "## Active Plans\n\n"
            "- [00001: Alpha](00001-alpha/PLAN.md) - In Progress\n\n"
            "- [00311: Ghost](00311-ghost/PLAN.md) - In Progress\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "leave a stale row behind")
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")

        assert _levels_for(repo, "does not exist") == [Level.ADVISE]
        assert _levels_for(repo, "no folder exists") == [Level.ADVISE]

    def test_the_same_row_blocks_when_this_commit_introduces_it(self, repo: Path) -> None:
        plan_root = repo / _PLAN_DIR_REL
        (plan_root / "README.md").write_text(
            "## Active Plans\n\n"
            "- [00001: Alpha](00001-alpha/PLAN.md) - In Progress\n\n"
            "- [00311: Ghost](00311-ghost/PLAN.md) - In Progress\n"
        )
        _git(repo, "add", "-A")

        assert _levels_for(repo, "does not exist") == [Level.BLOCK]
        assert _levels_for(repo, "no folder exists") == [Level.BLOCK]

    def test_a_folder_this_commit_creates_without_a_row_still_blocks(self, repo: Path) -> None:
        _make_folder(repo / _PLAN_DIR_REL, "00312-new")
        _git(repo, "add", "-A")

        assert _levels_for(repo, "has no README index row") == [Level.BLOCK]

    def test_a_folder_that_was_already_unindexed_only_advises(self, repo: Path) -> None:
        _make_folder(repo / _PLAN_DIR_REL, "00312-new")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "leave an unindexed folder behind")
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")

        assert _levels_for(repo, "has no README index row") == [Level.ADVISE]

    def test_the_sweep_is_unchanged_because_it_has_no_commit_to_blame(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        """Without gitfacts there is no commit to attribute the state to.

        The sweep reports the tree as it stands, which is its whole job — this
        narrowing is about who gets BLAMED, not about what is true.
        """
        readme = "## Active Plans\n\n- [00002: Ghost](00002-ghost/PLAN.md) - In Progress\n"
        _commit_spec, sweep_spec = CHECKS
        findings = sweep_spec.run(_context(tmp_path, readme))

        assert findings
        assert all(f.level == Level.BLOCK for f in findings)


class TestTheCommitGateSpawnsGitOnce:
    """Plan 00364 Task 2.1.

    This check runs inside the ``git commit`` PreToolUse gate, and the
    blame question it asks per folder went to git every time. Cost scaled
    with plan count, so it grew for exactly the projects that use the plan
    workflow most: 363 spawns measured against one on a real tree.

    Two changes hold the property, and each is pinned below: the facts are
    read once per instance, and the blame question is asked only when there
    is a finding to attach it to.
    """

    @staticmethod
    def _populate(repo: Path, count: int) -> None:
        """Add ``count`` clean, correctly-indexed plan folders to ``repo``."""
        plan_root = repo / _PLAN_DIR_REL
        rows = ["## Active Plans\n", "\n- [00001: Alpha](00001-alpha/PLAN.md) - In Progress\n"]
        for number in range(2, count + 2):
            name = f"{number:05d}-plan"
            _make_folder(plan_root, name)
            rows.append(f"- [{number:05d}: Plan](" + name + "/PLAN.md) - In Progress\n")
        (plan_root / "README.md").write_text("".join(rows))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "a tree of clean plans")

    def test_a_clean_tree_of_many_folders_costs_one_diff(
        self, repo: Path, git_diff_spawns: list[tuple[str, ...]]
    ) -> None:
        """No findings at all, so nothing needs the blame question asked."""
        self._populate(repo, 25)
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")

        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(_commit_context(repo)) == []
        assert len(git_diff_spawns) <= 1

    def test_a_tree_with_findings_still_costs_one_diff(
        self, repo: Path, git_diff_spawns: list[tuple[str, ...]]
    ) -> None:
        """The blame question IS asked here, and still reads one memoised diff."""
        self._populate(repo, 25)
        _make_folder(repo / _PLAN_DIR_REL, "00900-unindexed")
        _git(repo, "add", "-A")

        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(_commit_context(repo))
        assert [f.level for f in findings] == [Level.BLOCK]
        assert len(git_diff_spawns) == 1

    def test_the_verdict_is_unchanged_by_the_lazy_blame_question(self, repo: Path) -> None:
        """Deferring ``_level`` must not move a level, only the work.

        A folder the commit did not touch still advises; one it created
        still blocks. Both verdicts are computed AFTER the finding exists.
        """
        _make_folder(repo / _PLAN_DIR_REL, "00901-stale")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "leave an unindexed folder behind")
        _make_folder(repo / _PLAN_DIR_REL, "00902-fresh")
        _git(repo, "add", "-A")

        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(_commit_context(repo))
        by_folder = {f.path: f.level for f in findings}
        assert by_folder["00901-stale"] == Level.ADVISE
        assert by_folder["00902-fresh"] == Level.BLOCK
