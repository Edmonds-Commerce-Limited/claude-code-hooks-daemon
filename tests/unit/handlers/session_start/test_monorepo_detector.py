"""Tests for MonorepoDetectorHandler."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.workspace import DeclaredProject, ProjectRegistry
from claude_code_hooks_daemon.handlers.session_start.monorepo_detector import (
    MonorepoDetectorHandler,
)


@pytest.fixture
def handler() -> MonorepoDetectorHandler:
    return MonorepoDetectorHandler()


class TestMonorepoDetectorInit:
    """Handler initialisation tests."""

    def test_init_sets_correct_name(self, handler: MonorepoDetectorHandler) -> None:
        assert handler.name == "monorepo-detector"

    def test_init_sets_terminal_false(self, handler: MonorepoDetectorHandler) -> None:
        assert handler.terminal is False


class TestMonorepoDetectorMatches:
    """matches() tests."""

    def test_matches_new_session_returns_true(self, handler: MonorepoDetectorHandler) -> None:
        hook_input = {"hook_event_name": "SessionStart"}
        assert handler.matches(hook_input) is True

    def test_matches_resume_session_returns_false(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "transcript.json"
        transcript.write_text("x" * 200)
        hook_input = {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}
        assert handler.matches(hook_input) is False


class TestMonorepoDetectorHandle:
    """handle() tests -- the walk, its exclusions, and the advisory shape."""

    def _handle(
        self, handler: MonorepoDetectorHandler, project_root: Path
    ) -> tuple[Decision, list[str]]:
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.monorepo_detector."
            "ProjectContext.project_root",
            return_value=project_root,
        ):
            result = handler.handle({"hook_event_name": "SessionStart"})
        return result.decision, result.context

    def test_no_advisory_for_ordinary_single_project_repo(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        """No manifests anywhere -- nothing to detect."""
        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        assert context == []

    def test_no_advisory_when_root_manifest_exists(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        """A manifest AT the root is a normal single project, even with sub-manifests."""
        (tmp_path / "package.json").write_text("{}")
        sub = tmp_path / "packages" / "web"
        sub.mkdir(parents=True)
        (sub / "package.json").write_text("{}")

        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        assert context == []

    def test_advisory_when_manifests_below_root_and_none_at_root(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        web = tmp_path / "web"
        web.mkdir()
        (web / "package.json").write_text("{}")

        api = tmp_path / "api"
        api.mkdir()
        (api / "composer.json").write_text("{}")

        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        joined = "\n".join(context)
        assert "monorepo" in joined.lower()
        assert "web" in joined
        assert "api" in joined
        assert "projects:" in joined
        assert "root: web" in joined
        assert "root: api" in joined

    def test_advisory_disambiguates_colliding_basenames(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        """Two manifest dirs sharing a basename (`apps/web`, `packages/web`)
        must not both suggest `name: web` -- pasting the block straight in
        would produce a duplicate project name."""
        apps_web = tmp_path / "apps" / "web"
        apps_web.mkdir(parents=True)
        (apps_web / "package.json").write_text("{}")

        packages_web = tmp_path / "packages" / "web"
        packages_web.mkdir(parents=True)
        (packages_web / "package.json").write_text("{}")

        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        joined = "\n".join(context)
        names = re.findall(r"name: (\S+)", joined)
        assert len(names) == len(set(names)), f"duplicate project names in: {joined}"
        assert "name: apps-web" in joined or "name: packages-web" in joined

    def test_no_advisory_when_projects_declared(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        """Declared projects mean the daemon already knows -- advising would be noise."""
        web = tmp_path / "web"
        web.mkdir()
        (web / "package.json").write_text("{}")

        handler._project_registry = ProjectRegistry(
            project_root=tmp_path,
            projects=(DeclaredProject(name="web", root=web),),
        )

        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        assert context == []

    def test_skips_vendor_directories(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        """A manifest sitting inside node_modules must never count as a workspace."""
        nested = tmp_path / "node_modules" / "some-dep"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text("{}")

        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        assert context == []

    def test_does_not_descend_into_nested_git_repos(
        self, handler: MonorepoDetectorHandler, tmp_path: Path
    ) -> None:
        """A subdirectory holding its own .git is a different repository entirely."""
        nested_repo = tmp_path / "vendored-checkout"
        nested_repo.mkdir()
        (nested_repo / ".git").mkdir()
        (nested_repo / "package.json").write_text("{}")

        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        assert context == []

    def test_bounds_walk_depth(self, handler: MonorepoDetectorHandler, tmp_path: Path) -> None:
        """A manifest far below the configured depth bound is not found."""
        deep = tmp_path
        for name in ("a", "b", "c", "d", "e", "f", "g"):
            deep = deep / name
            deep.mkdir()
        (deep / "package.json").write_text("{}")

        decision, context = self._handle(handler, tmp_path)
        assert decision == Decision.ALLOW
        assert context == []

    def test_get_claude_md_returns_none(self, handler: MonorepoDetectorHandler) -> None:
        assert handler.get_claude_md() is None

    def test_get_acceptance_tests_returns_list(self, handler: MonorepoDetectorHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1
