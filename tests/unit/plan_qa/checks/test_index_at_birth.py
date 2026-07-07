"""Tests for the index-at-birth check (Plan 00144; sins B1, B2, D2, G2).

Builds real git repos with staged changes per the ``test_gitfacts.py``
pattern, since this check consumes ``GitFacts`` over the staged tree.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.index_at_birth import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
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
    plan_dir = root / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "README.md").write_text("# Plans Index\n\n## Active Plans\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _context(
    root: Path,
    readme_text: str | None,
    legacy: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        gitfacts=GitFacts(root),
        readme=ReadmeIndex.parse(readme_text) if readme_text is not None else None,
    )


def _stage_new_plan(root: Path, folder: str) -> None:
    plan_folder = root / "CLAUDE" / "Plan" / folder
    plan_folder.mkdir(parents=True)
    (plan_folder / "PLAN.md").write_text(
        f"# Plan {folder.split('-')[0]}: x\n\n**Status**: Not Started\n"
    )
    _git(root, "add", "-A")


class TestSpec:
    def test_registered_for_commit_stage(self) -> None:
        assert CHECK.check_id == "index-at-birth"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.BLOCK
        assert set(CHECK.sins) == {"B1", "B2", "D2", "G2"}


class TestScope:
    def test_no_gitfacts_returns_empty(self, repo: Path) -> None:
        context = CheckContext(
            project_root=repo,
            plan_dir_rel=_PLAN_DIR_REL,
            readme=ReadmeIndex.parse("# Plans Index\n"),
        )
        assert CHECK.run(context) == []

    def test_no_readme_returns_empty(self, repo: Path) -> None:
        _stage_new_plan(repo, "00002-widget")
        context = CheckContext(
            project_root=repo,
            plan_dir_rel=_PLAN_DIR_REL,
            gitfacts=GitFacts(repo),
            readme=None,
        )
        assert CHECK.run(context) == []

    def test_no_staged_new_plan_folders_is_clean(self, repo: Path) -> None:
        context = _context(repo, "# Plans Index\n\n## Active Plans\n")
        assert CHECK.run(context) == []


class TestFindings:
    def test_new_plan_indexed_in_same_commit_is_clean(self, repo: Path) -> None:
        _stage_new_plan(repo, "00002-widget")
        readme_text = "# Plans Index\n\n## Active Plans\n\n- [00002: Widget](00002-widget/PLAN.md) - Not Started\n"
        context = _context(repo, readme_text)
        assert CHECK.run(context) == []

    def test_new_plan_folder_without_readme_row_blocks(self, repo: Path) -> None:
        _stage_new_plan(repo, "00002-widget")
        context = _context(repo, "# Plans Index\n\n## Active Plans\n")
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "index-at-birth"
        assert finding.level == Level.BLOCK
        assert "00002" in finding.message
        assert "README.md" in finding.remediation

    def test_multiple_new_plans_each_reported(self, repo: Path) -> None:
        _stage_new_plan(repo, "00002-widget")
        _stage_new_plan(repo, "00003-gadget")
        context = _context(repo, "# Plans Index\n\n## Active Plans\n")
        findings = CHECK.run(context)
        assert len(findings) == 2
        numbers = {f.message for f in findings}
        assert any("00002" in message for message in numbers)
        assert any("00003" in message for message in numbers)

    def test_only_plan_md_file_needed_to_count_as_new_folder(self, repo: Path) -> None:
        plan_folder = repo / "CLAUDE" / "Plan" / "00002-widget"
        plan_folder.mkdir(parents=True)
        (plan_folder / "notes.md").write_text("scratch\n")
        _git(repo, "add", "-A")
        context = _context(repo, "# Plans Index\n\n## Active Plans\n")
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert "00002" in findings[0].message
