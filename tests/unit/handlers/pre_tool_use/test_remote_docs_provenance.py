"""The write-time provenance gate (Plan 00326 Task 3.4, D17).

BRAINSTORM's triage calls this the single highest-value rule in the set: it
is what makes "every vendored document declares where it came from" an
invariant rather than an aspiration. Missing provenance is a FACT, checkable
offline with no judgement involved, so D7 says it blocks.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_provenance import (
    RemoteDocsProvenanceHandler,
)

_ROOT = Path("/tmp/test")

_VALID = """---
source_url: https://example.com/p
fetched_at: 2026-09-03T10:00:00+00:00
fidelity: verbatim
source_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
licence: CC-BY-4.0
stale_after: 2026-12-01
---

# Upstream
"""


@pytest.fixture(autouse=True)
def _mock_project_context():
    """The handler resolves the workspace root at construction time."""
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
    ) as mock:
        mock.return_value = _ROOT
        yield mock


@pytest.fixture
def handler() -> RemoteDocsProvenanceHandler:
    instance = RemoteDocsProvenanceHandler()
    instance._project_layout = ProjectLayout.built_in_default()
    instance._workspace_root = _ROOT
    return instance


def _write(rel: str, content: str) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(_ROOT / rel), "content": content},
    }


class TestScope:
    def test_ignores_files_outside_the_remote_tree(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        assert handler.matches(_write("docs/guide.md", "# No frontmatter\n")) is False

    def test_ignores_non_markdown_inside_the_tree(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        assert handler.matches(_write("remote-docs/x/data.json", "{}")) is False

    def test_matches_a_markdown_write_inside_the_tree(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        assert handler.matches(_write("remote-docs/x/p.md", "# No frontmatter\n")) is True


class TestGate:
    def test_valid_provenance_is_allowed(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        hook_input = _write("remote-docs/example.com/p.md", _VALID)

        assert handler.matches(hook_input) is False

    def test_missing_frontmatter_is_denied(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        hook_input = _write("remote-docs/example.com/p.md", "# Just prose\n")

        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision is Decision.DENY

    def test_the_deny_message_names_every_missing_field(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        """One field per retry would make fixing a bad file a slog."""
        hook_input = _write(
            "remote-docs/example.com/p.md",
            "---\nsource_url: https://example.com/p\n---\n\nbody\n",
        )

        reason = handler.handle(hook_input).reason or ""

        for field in ("fetched_at", "fidelity", "source_sha256", "licence"):
            assert field in reason

    def test_the_deny_message_points_at_the_capture_command(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        """A gate that only says no teaches nothing; name the way through."""
        hook_input = _write("remote-docs/example.com/p.md", "# prose\n")

        reason = handler.handle(hook_input).reason or ""

        assert "remote-docs add" in reason

    def test_an_edit_is_gated_on_the_resulting_content(
        self, handler: RemoteDocsProvenanceHandler
    ) -> None:
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(_ROOT / "remote-docs/x/p.md"),
                "new_string": "# reworded upstream prose\n",
            },
        }

        assert handler.matches(hook_input) is True

    def test_a_reconfigured_tree_is_honoured(self) -> None:
        layout = ProjectLayout.built_in_default()
        moved = ProjectLayout(
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
        instance = RemoteDocsProvenanceHandler()
        instance._project_layout = moved
        instance._workspace_root = _ROOT

        assert instance.matches(_write("upstream-docs/x/p.md", "# prose\n")) is True
        assert instance.matches(_write("remote-docs/x/p.md", "# prose\n")) is False
