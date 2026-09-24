"""Tests for the upgrade-guides resolver (Plan 00376 Tasks 4.2 and 4.3).

The resolver answers one question for the rest of the upgrade path: which
parts of ``CLAUDE/UPGRADES/`` does a ``from -> to`` upgrade cross? Two callers
depend on it: the pre-install REQUIRED READING list (Task 4.2) and the
mandatory post-upgrade-tasks step (Task 4.3). A guide list that matches only
``v{M}.{m}-to-v{M}.{m+1}`` names inside ``v{target_major}/`` cannot see a
patch-versioned guide directory (``v3.62.1-to-v3.63.0``) or the
``UNRELEASED/`` holding area, which is the defect these tests pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install import upgrade_guides
from claude_code_hooks_daemon.install.upgrade_guides import (
    crossed_guide_dirs,
    guide_document,
    guide_documents,
    unreleased_staged_documents,
)

_TASK_HEADER = """# Task: {title}

**Type**: {type}
**Severity**: {severity}
**Applies to**: all
**Idempotent**: yes

## Why

Because.
"""


def _task(path: Path, *, severity: str = "recommended", task_type: str = "audit") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TASK_HEADER.format(title=path.stem, type=task_type, severity=severity))
    return path


def _guide(upgrades: Path, major_dir: str, name: str, *, main: bool = True) -> Path:
    guide_dir = upgrades / major_dir / name
    guide_dir.mkdir(parents=True, exist_ok=True)
    if main:
        (guide_dir / f"{name}.md").write_text(f"# {name}\n")
    return guide_dir


@pytest.fixture
def upgrades(tmp_path: Path) -> Path:
    root = tmp_path / "CLAUDE" / "UPGRADES"
    _guide(root, "v3", "v3.57-to-v3.58")
    _guide(root, "v3", "v3.62.1-to-v3.63.0")
    _guide(root, "v3", "v3.63.0-to-v3.64.0", main=False)
    _guide(root, "v3", "v3.64.0-to-v3.65.0")
    _task(root / "v3" / "v3.57-to-v3.58" / "post-upgrade-tasks" / "01-old.md")
    _task(root / "v3" / "v3.63.0-to-v3.64.0" / "post-upgrade-tasks" / "01-rewrite.md")
    _task(
        root / "v3" / "v3.63.0-to-v3.64.0" / "post-upgrade-tasks" / "02-audit.md",
        severity="critical",
    )
    (root / "v3" / "v3.63.0-to-v3.64.0" / "post-upgrade-tasks" / "README.md").write_text("idx\n")
    _task(root / "UNRELEASED" / "post-upgrade-tasks" / "01-staged.md", severity="optional")
    (root / "UNRELEASED" / "post-upgrade-tasks" / "README.md").write_text("convention\n")
    (root / "UNRELEASED" / "README.md").write_text("holding area\n")
    (root / "UNRELEASED" / "release-notes").mkdir(parents=True)
    (root / "UNRELEASED" / "release-notes" / "README.md").write_text("convention\n")
    (root / "UNRELEASED" / "release-notes" / "01-callout.md").write_text("# Callout\n")
    _task(root / "upgrade-template" / "post-upgrade-tasks" / "00-EXAMPLE-task.md")
    return root


class TestCrossedGuideDirs:
    def test_patch_versioned_directories_are_crossed(self, upgrades: Path) -> None:
        crossed = crossed_guide_dirs(upgrades, "3.62.1", "3.65.0")
        assert [d.name for d in crossed] == [
            "v3.62.1-to-v3.63.0",
            "v3.63.0-to-v3.64.0",
            "v3.64.0-to-v3.65.0",
        ]

    def test_range_excludes_from_and_includes_to(self, upgrades: Path) -> None:
        crossed = crossed_guide_dirs(upgrades, "3.63.0", "3.64.0")
        assert [d.name for d in crossed] == ["v3.63.0-to-v3.64.0"]

    def test_minor_only_names_compare_as_patch_zero(self, upgrades: Path) -> None:
        crossed = crossed_guide_dirs(upgrades, "3.57.2", "3.58.0")
        assert [d.name for d in crossed] == ["v3.57-to-v3.58"]

    def test_tag_prefix_and_build_metadata_are_accepted(self, upgrades: Path) -> None:
        crossed = crossed_guide_dirs(upgrades, "v3.63.0", "3.64.0+main.abc1234")
        assert [d.name for d in crossed] == ["v3.63.0-to-v3.64.0"]

    def test_template_and_holding_area_are_never_guides(self, upgrades: Path) -> None:
        crossed = crossed_guide_dirs(upgrades, "0.0.1", "99.0.0")
        names = {d.name for d in crossed}
        assert "upgrade-template" not in names
        assert "UNRELEASED" not in names

    def test_missing_tree_is_empty(self, tmp_path: Path) -> None:
        assert crossed_guide_dirs(tmp_path / "nope", "3.0.0", "3.1.0") == []

    def test_backwards_range_is_refused(self, upgrades: Path) -> None:
        with pytest.raises(ValueError, match="from_version"):
            crossed_guide_dirs(upgrades, "3.65.0", "3.64.0")

    def test_unparseable_version_is_refused(self, upgrades: Path) -> None:
        with pytest.raises(ValueError, match="version"):
            crossed_guide_dirs(upgrades, "main", "3.64.0")


class TestGuideDocument:
    def test_main_guide_wins(self, upgrades: Path) -> None:
        guide_dir = upgrades / "v3" / "v3.64.0-to-v3.65.0"
        (guide_dir / "README.md").write_text("also here\n")
        assert guide_document(guide_dir) == guide_dir / "v3.64.0-to-v3.65.0.md"

    def test_readme_is_the_fallback(self, tmp_path: Path) -> None:
        guide_dir = tmp_path / "v2.32-to-v3.0"
        guide_dir.mkdir()
        (guide_dir / "README.md").write_text("guide\n")
        assert guide_document(guide_dir) == guide_dir / "README.md"

    def test_task_only_directory_has_no_guide_document(self, upgrades: Path) -> None:
        assert guide_document(upgrades / "v3" / "v3.63.0-to-v3.64.0") is None


class TestUnreleasedStagedDocuments:
    def test_every_staged_document_except_scaffolding(self, upgrades: Path) -> None:
        staged = unreleased_staged_documents(upgrades)
        assert [p.relative_to(upgrades / "UNRELEASED").as_posix() for p in staged] == [
            "post-upgrade-tasks/01-staged.md",
            "release-notes/01-callout.md",
        ]

    def test_absent_holding_area_is_empty(self, tmp_path: Path) -> None:
        assert unreleased_staged_documents(tmp_path) == []


class TestGuideDocuments:
    def test_crossed_documents_then_staged_ones(self, upgrades: Path) -> None:
        documents = guide_documents(upgrades, "3.62.1", "3.65.0", include_unreleased=True)
        assert [d.relative_to(upgrades).as_posix() for d in documents] == [
            "v3/v3.62.1-to-v3.63.0/v3.62.1-to-v3.63.0.md",
            "v3/v3.64.0-to-v3.65.0/v3.64.0-to-v3.65.0.md",
            "UNRELEASED/post-upgrade-tasks/01-staged.md",
            "UNRELEASED/release-notes/01-callout.md",
        ]

    def test_default_asks_the_install_stamp(
        self, upgrades: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(upgrade_guides, "is_branch_install", lambda: False)
        documents = guide_documents(upgrades, "3.64.0", "3.65.0")
        assert [d.name for d in documents] == ["v3.64.0-to-v3.65.0.md"]

    def test_default_tree_is_the_daemons_own(self) -> None:
        tree = upgrade_guides.default_upgrades_dir()
        assert (tree / "UNRELEASED" / "post-upgrade-tasks" / "README.md").is_file()
