"""The remote-docs commit gate (Plan 00326 Success Criteria).

The write-time gate keys on `Write`/`Edit`, so a Bash heredoc or redirect
into the tree reaches disk unexamined. That is a real hole, recorded as
BLIND in the bash-write-blindness register, and this is the backstop that
closes it: whatever route a file took to disk, it cannot be COMMITTED
without provenance.

The staleness sweep already reports such a file at the next session start.
This is stronger — it stops the unattributed document entering history at
all, which matters because removing one afterwards needs a rewrite.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_commit_gate import (
    RemoteDocsCommitGateHandler,
)

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


def _commit() -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'add docs'"}}


@pytest.fixture
def handler(tmp_path: Path) -> RemoteDocsCommitGateHandler:
    instance = RemoteDocsCommitGateHandler()
    instance.project_root_reader = lambda: tmp_path
    instance.staged_reader = lambda: []
    return instance


def _write(tmp_path: Path, rel: str, content: str) -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return rel


class TestScope:
    def test_it_matches_a_git_commit(self, handler: RemoteDocsCommitGateHandler) -> None:
        assert handler.matches(_commit()) is True

    def test_it_ignores_other_bash_commands(self, handler: RemoteDocsCommitGateHandler) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is False

    def test_it_ignores_other_tools(self, handler: RemoteDocsCommitGateHandler) -> None:
        assert handler.matches({"tool_name": "Write", "tool_input": {}}) is False


class TestGate:
    def test_a_commit_with_no_remote_docs_is_allowed(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda: [_write(tmp_path, "src/thing.py", "x = 1\n")]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_valid_vendored_document_is_allowed(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda: [_write(tmp_path, "remote-docs/example.com/p.md", _VALID)]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_document_with_no_provenance_is_denied(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        """This is the heredoc hole: it never passed the Write/Edit gate."""
        handler.staged_reader = lambda: [
            _write(tmp_path, "remote-docs/example.com/p.md", "# just prose\n")
        ]

        assert handler.handle(_commit()).decision is Decision.DENY

    def test_the_denial_names_the_offending_file(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda: [
            _write(tmp_path, "remote-docs/example.com/p.md", "# just prose\n")
        ]

        reason = handler.handle(_commit()).reason or ""

        assert "remote-docs/example.com/p.md" in reason

    def test_the_denial_names_the_capture_route(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda: [
            _write(tmp_path, "remote-docs/example.com/p.md", "# just prose\n")
        ]

        assert "remote-docs add" in (handler.handle(_commit()).reason or "")

    def test_every_bad_document_is_reported_at_once(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        """One file per retry would make a bulk import a slog."""
        handler.staged_reader = lambda: [
            _write(tmp_path, "remote-docs/example.com/a.md", "# prose\n"),
            _write(tmp_path, "remote-docs/example.com/b.md", "# prose\n"),
        ]

        reason = handler.handle(_commit()).reason or ""

        assert "a.md" in reason
        assert "b.md" in reason

    def test_a_non_markdown_file_in_the_tree_is_ignored(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda: [_write(tmp_path, "remote-docs/x/data.json", "{}")]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_deleted_file_does_not_block_the_commit(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        """Removing a bad document must never be harder than adding one."""
        handler.staged_reader = lambda: ["remote-docs/example.com/gone.md"]

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_a_markdown_file_outside_the_tree_is_ignored(
        self, handler: RemoteDocsCommitGateHandler, tmp_path: Path
    ) -> None:
        handler.staged_reader = lambda: [_write(tmp_path, "docs/guide.md", "# ours\n")]

        assert handler.handle(_commit()).decision is Decision.ALLOW


class TestResilience:
    def test_an_unreadable_git_index_allows_the_commit(
        self, handler: RemoteDocsCommitGateHandler
    ) -> None:
        """A gate that cannot read the index must not block every commit."""

        def boom() -> list[str]:
            raise OSError("no git here")

        handler.staged_reader = boom

        assert handler.handle(_commit()).decision is Decision.ALLOW

    def test_the_real_staged_reader_survives_a_missing_repository(self, tmp_path: Path) -> None:
        """`git diff --cached` outside a repository must not block the commit.

        Patched BEFORE construction: the readers are bound in `__init__`, so
        a patch applied afterwards would not be seen — and the test would
        pass for the wrong reason.
        """
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            instance = RemoteDocsCommitGateHandler()

            assert instance.handle(_commit()).decision is Decision.ALLOW
