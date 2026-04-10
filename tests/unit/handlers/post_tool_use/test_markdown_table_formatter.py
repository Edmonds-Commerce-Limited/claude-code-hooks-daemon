"""Tests for MarkdownTableFormatterHandler - auto-format markdown tables via mdformat."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.markdown_table_formatter import (
    MarkdownTableFormatterHandler,
)

_UNALIGNED_TABLE = (
    "# Test\n"
    "\n"
    "| Field | Key | Zoho Type |\n"
    "|-------|-----|-----------|\n"
    "| Snapshot Taken At | `cf_stat_snapshot_taken_at` | DateTime |\n"
    "| Total Orders | `cf_stat_total_orders` | Number |\n"
)

_ALIGNED_TABLE = (
    "# Test\n"
    "\n"
    "| Field             | Key                         | Zoho Type |\n"
    "| ----------------- | --------------------------- | --------- |\n"
    "| Snapshot Taken At | `cf_stat_snapshot_taken_at` | DateTime  |\n"
    "| Total Orders      | `cf_stat_total_orders`      | Number    |\n"
)


@pytest.fixture()
def handler() -> MarkdownTableFormatterHandler:
    return MarkdownTableFormatterHandler()


class TestInit:
    def test_handler_id_config_key(self, handler: MarkdownTableFormatterHandler) -> None:
        assert handler.handler_id.config_key == "markdown_table_formatter"

    def test_priority(self, handler: MarkdownTableFormatterHandler) -> None:
        from claude_code_hooks_daemon.constants import Priority

        assert handler.priority == Priority.MARKDOWN_TABLE_FORMATTER

    def test_terminal_is_false(self, handler: MarkdownTableFormatterHandler) -> None:
        assert handler.terminal is False

    def test_has_markdown_tag(self, handler: MarkdownTableFormatterHandler) -> None:
        from claude_code_hooks_daemon.constants import HandlerTag

        assert HandlerTag.MARKDOWN in handler.tags


class TestMatches:
    def test_matches_write_md_file(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text("# Doc\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_md_file(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text("# Doc\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_matches_markdown_extension(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.markdown"
        test_file.write_text("# Doc\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_matches_uppercase_md_extension(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "README.MD"
        test_file.write_text("# Doc\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_bash_tool(
        self, handler: MarkdownTableFormatterHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_read_tool(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text("# Doc\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Read",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_python_file(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 1\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_file_path(
        self, handler: MarkdownTableFormatterHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_when_file_missing_from_disk(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        missing = tmp_path / "not_there.md"
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(missing)},
        }
        assert handler.matches(hook_input) is False


class TestHandle:
    def test_reformats_unaligned_table(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        content_after = test_file.read_text()
        # Pipes should now be vertically aligned
        assert "| Field             |" in content_after
        assert "| Snapshot Taken At |" in content_after
        # Delimiter row should match cell widths
        assert "| ----------------- |" in content_after

    def test_idempotent_on_already_aligned_file(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_ALIGNED_TABLE)
        content_before = test_file.read_text()
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)
        content_after = test_file.read_text()
        assert content_before == content_after

    def test_preserves_consecutive_ordered_list_numbering(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(
            "# List\n\n1. First\n2. Second\n3. Third\n\n| a | b |\n|-|-|\n| 1 | 2 |\n"
        )
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)
        content_after = test_file.read_text()
        # Consecutive numbering preserved (not renumbered to 1. 1. 1.)
        assert "1. First" in content_after
        assert "2. Second" in content_after
        assert "3. Third" in content_after

    def test_restores_dashed_thematic_break(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(
            "# Top\n\n---\n\n## Section\n\n| a | b |\n|-|-|\n| 1 | 2 |\n"
        )
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)
        content_after = test_file.read_text()
        # --- preserved, not converted to 70 underscores
        assert "\n---\n" in content_after
        assert "_" * 70 not in content_after

    def test_returns_allow_decision(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_skips_missing_file_race_condition(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        missing = tmp_path / "vanished.md"
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(missing)},
        }
        result = handler.handle(hook_input)
        # Should not crash; should return ALLOW
        assert result.decision == Decision.ALLOW

    def test_graceful_on_mdformat_exception(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use."
            "markdown_table_formatter.mdformat.text",
            side_effect=RuntimeError("boom"),
        ):
            result = handler.handle(hook_input)
        # Should not crash dispatch; should return ALLOW
        assert result.decision == Decision.ALLOW

    def test_no_file_path_returns_allow(
        self, handler: MarkdownTableFormatterHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


class TestGuidance:
    def test_get_claude_md_returns_non_empty_guidance(
        self, handler: MarkdownTableFormatterHandler
    ) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "markdown_table_formatter" in guidance
        assert "mdformat" in guidance

    def test_get_acceptance_tests_returns_list(
        self, handler: MarkdownTableFormatterHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
