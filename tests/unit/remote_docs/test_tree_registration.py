"""The remote tree is registered as a first-class axis (Plan 00326 Task 1.3).

D12: the remote tree is a TOP-LEVEL directory, never a ``docs/``
subdirectory, because the deployed human-docs role rule (``docs/**/*.md``)
instructs "keep it terse, summarise" -- the opposite of verbatim capture --
and rule globs cannot be negated.

The allowance must derive from the registration rather than from an
``extra_allowed_markdown_paths`` entry every project has to remember, which
is why ``markdown_organization`` reads the axis off ``ProjectLayout``
exactly as it already does for the agent and human trees.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.config.models import DocumentationTreesConfig
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
    MarkdownOrganizationHandler,
)

#: The handler resolves paths against the PROJECT ROOT, not against whatever
#: `_workspace_root` is set to afterwards. Writing test files under `tmp_path`
#: while the root is mocked elsewhere puts every path OUTSIDE the project,
#: where the handler allows everything -- so such a test passes without
#: exercising the rule at all. Both must be the same path.
_ROOT = Path("/tmp/test")


@pytest.fixture(autouse=True)
def mock_project_context() -> Iterator[MagicMock]:
    """`MarkdownOrganizationHandler.__init__` resolves the project root."""
    target = "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
    with patch(target) as mock:
        mock.return_value = _ROOT
        yield mock


class TestTreesConfig:
    def test_remote_tree_has_a_default(self) -> None:
        trees = DocumentationTreesConfig()

        assert trees.remote == "remote-docs"

    def test_remote_tree_is_configurable(self) -> None:
        trees = DocumentationTreesConfig(remote="upstream-docs-docs")

        assert trees.remote == "upstream-docs-docs"

    def test_absolute_remote_tree_is_rejected(self) -> None:
        """Tree roots are repository-relative, same rule as agent/human."""
        try:
            DocumentationTreesConfig(remote="/etc/docs")
        except ValueError:
            return
        raise AssertionError("an absolute remote tree root should be rejected")


class TestProjectLayoutAxis:
    def test_built_in_default_carries_the_remote_axis(self) -> None:
        layout = ProjectLayout.built_in_default()

        assert layout.remote_docs_dir == "remote-docs"

    def test_is_remote_docs_path_matches_under_the_tree(self) -> None:
        layout = ProjectLayout.built_in_default()

        assert layout.is_remote_docs_path("remote-docs/example.com/page.md") is True

    def test_is_remote_docs_path_rejects_paths_outside_the_tree(self) -> None:
        layout = ProjectLayout.built_in_default()

        assert layout.is_remote_docs_path("docs/guides/thing.md") is False
        assert layout.is_remote_docs_path("CLAUDE/ARCHITECTURE.md") is False

    def test_is_remote_docs_path_does_not_match_a_similar_prefix(self) -> None:
        """`remote-docs-notes/` is a different directory, not this tree."""
        layout = ProjectLayout.built_in_default()

        assert layout.is_remote_docs_path("remote-docs-notes/x.md") is False

    def test_remote_tree_is_not_a_docs_path(self) -> None:
        """D1/D12: remote is a THIRD tree, not part of the authored corpus.

        If `is_docs_path` claimed it, every consumer keyed on that predicate
        would treat vendored upstream prose as project-authored documentation
        -- which is exactly the inheritance D12 exists to avoid.
        """
        layout = ProjectLayout.built_in_default()

        assert layout.is_docs_path("remote-docs/example.com/page.md") is False

    def test_for_project_inherits_the_remote_axis(self) -> None:
        """Doc axes are supplied by the root layout, like agent/human."""
        root = ProjectLayout.built_in_default()

        derived = ProjectLayout.for_project(None, root)

        assert derived.remote_docs_dir == root.remote_docs_dir


class TestMarkdownLocationAllowance:
    """D12's payoff: the allowance derives from the registration.

    The alternative was an `extra_allowed_markdown_paths` regex every project
    has to add and keep in sync with its tree config -- two statements of one
    truth, and the second one silently rots.
    """

    def _handler(self, layout: ProjectLayout) -> MarkdownOrganizationHandler:
        handler = MarkdownOrganizationHandler()
        handler._project_layout = layout
        handler._workspace_root = _ROOT
        return handler

    def _write(self, rel: str) -> dict[str, Any]:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": str(_ROOT / rel), "content": "# upstream\n"},
        }

    def test_an_unregistered_top_level_tree_is_blocked(self) -> None:
        """The control: without the registration these paths are refused.

        Without this, the allowance test below could pass simply because the
        handler allows everything, and prove nothing.
        """
        handler = self._handler(ProjectLayout.built_in_default())

        assert handler.matches(self._write("some-other-tree/x.com/page.md")) is True

    def test_capture_into_the_remote_tree_is_allowed(self) -> None:
        handler = self._handler(ProjectLayout.built_in_default())

        blocked = handler.matches(self._write("remote-docs/example.com/page.md"))

        assert blocked is False

    def test_a_reconfigured_remote_tree_is_honoured(self) -> None:
        """The axis is read off the facade, not a hardcoded literal."""
        layout = ProjectLayout.built_in_default()
        reconfigured = ProjectLayout(
            source_dirs=layout.source_dirs,
            test_dirs=layout.test_dirs,
            config_dirs=layout.config_dirs,
            vendor_dirs=layout.vendor_dirs,
            agent_docs_dir=layout.agent_docs_dir,
            human_docs_dir=layout.human_docs_dir,
            plan_dir=layout.plan_dir,
            plan_archive_dirs=layout.plan_archive_dirs,
            remote_docs_dir="upstream-docs",
        )
        handler = self._handler(reconfigured)

        assert handler.matches(self._write("upstream-docs/x.com/page.md")) is False
        # Moving the tree moves the allowance with it: the built-in default
        # name carries no special status of its own.
        assert handler.matches(self._write("remote-docs/x.com/page.md")) is True
