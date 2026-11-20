"""Which directories under ``untracked/`` a sweep may judge (Plan 00627 DESIGN.md section 4.1).

``untracked/repos``, every reference-repository root and the archive store are
never swept, whatever ``scratch.untracked_ttl`` says, and a ``"*"`` TTL refuses
the root before anything is listed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.core.untracked_roots import resolve_sweep_root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    for name in ("scratch", "repos", "briefs", "scratch-archive", "logs"):
        (project / "untracked" / name).mkdir(parents=True)
    return project


class TestScratch:
    def test_scratch_takes_its_ttl(self, project: Path) -> None:
        root = resolve_sweep_root(
            project / "untracked" / "scratch",
            project_root=project,
            config=ScratchConfig(),
            reference_roots=("untracked/repos",),
        )
        assert (root.refusal, root.ttl_hours, root.skip) == ("", 24, ())

    def test_scratch_with_the_owners_example(self, project: Path) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {"scratch": "7d"}})
        root = resolve_sweep_root(
            project / "untracked" / "scratch",
            project_root=project,
            config=config,
            reference_roots=(),
        )
        assert root.ttl_hours == 168

    @pytest.mark.parametrize(
        "rel", ["tests/support", "src", ".claude/worktrees/x/untracked/scratch"]
    )
    def test_a_root_outside_this_projects_untracked_is_refused(
        self, tmp_path: Path, rel: str
    ) -> None:
        project = tmp_path / "project"
        elsewhere = project / rel
        elsewhere.mkdir(parents=True)
        root = resolve_sweep_root(
            elsewhere, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert root.ttl_hours is None
        assert "not inside this project's untracked/" in root.refusal

    def test_a_tree_outside_the_project_is_refused(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        outside = tmp_path / "elsewhere" / "untracked" / "scratch"
        outside.mkdir(parents=True)
        root = resolve_sweep_root(
            outside, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert root.ttl_hours is None

    @pytest.mark.parametrize("name", ["repos", "scratch-archive"])
    def test_another_checkouts_never_swept_directory_is_refused_at_any_depth(
        self, tmp_path: Path, name: str
    ) -> None:
        project = tmp_path / "project"
        other = project / "untracked" / "scratch" / "clone" / "untracked" / name / "x"
        other.mkdir(parents=True)
        root = resolve_sweep_root(
            other, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert root.ttl_hours is None
        assert f"untracked/{name}" in root.refusal


class TestNeverSwept:
    @pytest.mark.parametrize("name", ["repos", "scratch-archive"])
    def test_a_protected_root_is_refused_even_with_a_finite_ttl(
        self, project: Path, name: str
    ) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {name: "1h"}})
        root = resolve_sweep_root(
            project / "untracked" / name,
            project_root=project,
            config=config,
            reference_roots=(),
        )
        assert root.ttl_hours is None
        assert "never swept" in root.refusal

    def test_a_path_inside_repos_is_refused(self, project: Path) -> None:
        inner = project / "untracked" / "repos" / "alpha"
        inner.mkdir()
        root = resolve_sweep_root(
            inner, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert "never swept" in root.refusal

    def test_a_configured_reference_root_is_refused(self, project: Path) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {"briefs": "36h"}})
        root = resolve_sweep_root(
            project / "untracked" / "briefs",
            project_root=project,
            config=config,
            reference_roots=("untracked/briefs",),
        )
        assert "never swept" in root.refusal

    def test_a_link_to_repos_is_refused(self, project: Path) -> None:
        link = project / "untracked" / "scratch" / "to-repos"
        link.symlink_to(project / "untracked" / "repos")
        root = resolve_sweep_root(
            link, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert "never swept" in root.refusal

    def test_a_root_holding_a_protected_path_skips_that_entry(self, project: Path) -> None:
        config = ScratchConfig.model_validate({"untracked_default_ttl": "36h"})
        root = resolve_sweep_root(
            project / "untracked" / "scratch",
            project_root=project,
            config=config,
            reference_roots=("untracked/scratch/kept-clones/inner",),
        )
        assert root.refusal == ""
        assert root.skip == ("kept-clones",)
        assert any("kept-clones" in note for note in root.notes)

    def test_the_project_root_itself_is_refused(self, project: Path) -> None:
        root = resolve_sweep_root(
            project, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert root.refusal

    def test_untracked_itself_is_refused(self, project: Path) -> None:
        root = resolve_sweep_root(
            project / "untracked",
            project_root=project,
            config=ScratchConfig(),
            reference_roots=(),
        )
        assert root.refusal


class TestStarAndFallthrough:
    def test_an_unlisted_directory_is_never_swept_by_default(self, project: Path) -> None:
        root = resolve_sweep_root(
            project / "untracked" / "logs",
            project_root=project,
            config=ScratchConfig(),
            reference_roots=(),
        )
        assert root.ttl_hours is None
        assert '"*"' in root.refusal

    def test_a_named_directory_takes_its_ttl(self, project: Path) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {"briefs": "36h"}})
        root = resolve_sweep_root(
            project / "untracked" / "briefs",
            project_root=project,
            config=config,
            reference_roots=(),
        )
        assert (root.refusal, root.ttl_hours) == ("", 36)

    def test_a_path_inside_an_unlisted_directory_is_never_swept(self, project: Path) -> None:
        inner = project / "untracked" / "logs" / "inner"
        inner.mkdir()
        root = resolve_sweep_root(
            inner, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert root.ttl_hours is None
        assert "untracked/logs" in root.refusal

    def test_a_path_inside_scratch_keeps_the_scratch_ttl(self, project: Path) -> None:
        inner = project / "untracked" / "scratch" / "box" / "below"
        inner.mkdir(parents=True)
        config = ScratchConfig.model_validate({"untracked_default_ttl": "1h"})
        root = resolve_sweep_root(inner, project_root=project, config=config, reference_roots=())
        assert (root.refusal, root.ttl_hours) == ("", 24)

    def test_a_path_inside_a_named_directory_takes_that_ttl(self, project: Path) -> None:
        inner = project / "untracked" / "briefs" / "x"
        inner.mkdir()
        config = ScratchConfig.model_validate({"untracked_ttl": {"briefs": "36h"}})
        root = resolve_sweep_root(inner, project_root=project, config=config, reference_roots=())
        assert root.ttl_hours == 36

    def test_a_link_from_scratch_into_another_directory_is_refused(self, project: Path) -> None:
        link = project / "untracked" / "scratch" / "to-logs"
        link.symlink_to(project / "untracked" / "logs")
        config = ScratchConfig.model_validate({"untracked_ttl": {"logs": "1h"}})
        root = resolve_sweep_root(link, project_root=project, config=config, reference_roots=())
        assert "more than one" in root.refusal

    def test_an_ancestor_of_the_project_is_refused(self, project: Path) -> None:
        root = resolve_sweep_root(
            project.parent, project_root=project, config=ScratchConfig(), reference_roots=()
        )
        assert "holds the project" in root.refusal

    def test_scratch_set_to_star_is_refused(self, project: Path) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {"scratch": "*"}})
        root = resolve_sweep_root(
            project / "untracked" / "scratch",
            project_root=project,
            config=config,
            reference_roots=(),
        )
        assert root.refusal
