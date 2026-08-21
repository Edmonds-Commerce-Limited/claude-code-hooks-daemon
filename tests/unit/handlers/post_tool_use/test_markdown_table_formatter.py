"""Tests for MarkdownTableFormatterHandler - auto-format markdown tables via mdformat."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.markdown_table_formatter import (
    _LABEL_ASTERISKS,
    _LABEL_ORDERED_LISTS,
    _LABEL_TABLE_PIPES,
    _LABEL_THEMATIC_BREAKS,
    MarkdownTableFormatterHandler,
    _build_reformat_message,
    classify_markdown_changes,
)
from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

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

    def test_does_not_match_bash_tool(self, handler: MarkdownTableFormatterHandler) -> None:
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

    def test_does_not_match_journal_dayfile(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        # Plan 00163: journal day-files are append-only and byte-stable; the
        # formatter must NOT rewrite them (would trip the append-only check).
        journal = tmp_path / "00163-x" / "JOURNAL"
        journal.mkdir(parents=True)
        test_file = journal / "00163-Journal-26-07-14.md"
        test_file.write_text("# Journal\n\n## 09:00 · action · —\n\nx\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is False

    def test_still_matches_plan_md_beside_journal(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        # A normal PLAN.md is still formatted — only the journal grammar is exempt.
        test_file = tmp_path / "00163-x" / "PLAN.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# Plan 00163: x\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_missing_file_path(self, handler: MarkdownTableFormatterHandler) -> None:
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
        test_file.write_text("# Top\n\n---\n\n## Section\n\n| a | b |\n|-|-|\n| 1 | 2 |\n")
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

    def test_advisory_names_the_table_pipe_transformation(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.context == ["Reformatted markdown in doc.md: aligned table pipes"]

    def test_advisory_falls_back_to_generic_message_when_no_category_matches(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        # Setext heading -> ATX + blank-line collapsing: a real, non-empty
        # diff that matches none of the four tracked categories.
        test_file = tmp_path / "doc.md"
        test_file.write_text(
            "Heading\n=======\n\nSome text.\n\n\n\nMore text with trailing spaces.   \n"
        )
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        result = handler.handle(hook_input)
        assert result.context == ["Reformatted markdown in doc.md"]

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
            "markdown_table_formatter.format_markdown_text",
            side_effect=RuntimeError("boom"),
        ):
            result = handler.handle(hook_input)
        # Should not crash dispatch; should return ALLOW
        assert result.decision == Decision.ALLOW

    def test_no_file_path_returns_allow(self, handler: MarkdownTableFormatterHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_preserves_yaml_frontmatter_byte_for_byte(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        """YAML frontmatter (e.g. in SKILL.md) must be preserved exactly.

        Regression test for mdformat mangling `---`-delimited frontmatter into
        a thematic break followed by collapsed heading text.
        """
        test_file = tmp_path / "SKILL.md"
        original = (
            "---\n"
            "name: hooks-daemon\n"
            'description: "A daemon"\n'
            'argument-hint: "[command]"\n'
            "allowed-tools: Bash, Read, Edit\n"
            "---\n"
            "\n"
            "# Heading\n"
            "\n"
            "| a | b |\n"
            "|-|-|\n"
            "| 1 | 2 |\n"
        )
        test_file.write_text(original)
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)
        content_after = test_file.read_text()
        # Frontmatter block must be preserved exactly as written, with a
        # blank line separating it from the body (mdformat strips leading
        # whitespace, so the handler must re-insert the separator).
        assert content_after.startswith(
            "---\n"
            "name: hooks-daemon\n"
            'description: "A daemon"\n'
            'argument-hint: "[command]"\n'
            "allowed-tools: Bash, Read, Edit\n"
            "---\n"
            "\n"
        )
        # mdformat must not have turned `---` into a thematic break
        assert "_" * 70 not in content_after
        assert "## name:" not in content_after
        # Body tables still get aligned
        assert "| a | b |" in content_after or "| a   | b   |" in content_after

    def test_preserves_frontmatter_with_tripled_dashes_in_body(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        """Only the leading frontmatter is stripped; `---` in body still gets thematic-break treatment."""
        test_file = tmp_path / "doc.md"
        test_file.write_text(
            "---\n" "title: Test\n" "---\n" "\n" "# Top\n" "\n" "---\n" "\n" "## Section\n"
        )
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)
        content_after = test_file.read_text()
        # Frontmatter preserved
        assert content_after.startswith("---\ntitle: Test\n---\n")
        # Body thematic break stays as --- (not 70 underscores)
        assert "_" * 70 not in content_after

    def test_no_frontmatter_still_formats_normally(
        self, handler: MarkdownTableFormatterHandler, tmp_path: Path
    ) -> None:
        """Files without frontmatter behave exactly as before."""
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        handler.handle(hook_input)
        content_after = test_file.read_text()
        assert "| Field             |" in content_after


class TestClassifyMarkdownChanges:
    """Tests for the pure ``classify_markdown_changes`` diff classifier.

    Each test drives the REAL ``format_markdown_text`` transform on a
    minimal document engineered to trip exactly one category, so a passing
    test proves the classifier reports that category and no other.
    """

    def test_table_pipes_only(self) -> None:
        formatted = format_markdown_text(_UNALIGNED_TABLE)
        assert classify_markdown_changes(_UNALIGNED_TABLE, formatted) == [_LABEL_TABLE_PIPES]

    def test_ordered_list_renumbering_only(self) -> None:
        before = "1. First\n1. Second\n1. Third\n"
        formatted = format_markdown_text(before)
        assert formatted == "1. First\n2. Second\n3. Third\n"
        assert classify_markdown_changes(before, formatted) == [_LABEL_ORDERED_LISTS]

    def test_thematic_break_restoration_only(self) -> None:
        before = "Top\n\n***\n\nBottom\n"
        formatted = format_markdown_text(before)
        assert formatted == "Top\n\n---\n\nBottom\n"
        assert classify_markdown_changes(before, formatted) == [_LABEL_THEMATIC_BREAKS]

    def test_stray_asterisk_escaping_only(self) -> None:
        before = "Some text with a stray c*d asterisk in a paragraph.\n"
        formatted = format_markdown_text(before)
        assert formatted == "Some text with a stray c\\*d asterisk in a paragraph.\n"
        assert classify_markdown_changes(before, formatted) == [_LABEL_ASTERISKS]

    def test_paired_emphasis_asterisks_are_not_reported_as_escaped(self) -> None:
        # `*x*` is valid emphasis markup, not a stray asterisk - mdformat
        # leaves it alone, so no category should fire for this alone.
        before = "Some *emphasised* text with no other change needed.\n"
        formatted = format_markdown_text(before)
        assert formatted == before
        assert classify_markdown_changes(before, formatted) == []

    def test_multiple_categories_reported_in_fixed_order(self) -> None:
        before = "1. First\n1. Second\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        formatted = format_markdown_text(before)
        labels = classify_markdown_changes(before, formatted)
        # Fixed order (table pipes, then ordered lists) regardless of which
        # change appears first in the document.
        assert labels == [_LABEL_TABLE_PIPES, _LABEL_ORDERED_LISTS]

    def test_frontmatter_is_never_reported_as_changed(self) -> None:
        before = "---\ntitle: Test\n---\n\n" + _UNALIGNED_TABLE
        formatted = format_markdown_text(before)
        # Frontmatter is preserved byte-for-byte by format_markdown_text.
        assert formatted.startswith("---\ntitle: Test\n---\n")
        # Only the body table change is reported - nothing frontmatter-shaped.
        assert classify_markdown_changes(before, formatted) == [_LABEL_TABLE_PIPES]

    def test_fallback_when_no_tracked_category_explains_a_real_diff(self) -> None:
        # Setext heading -> ATX + blank-line collapsing + trailing-whitespace
        # trim: a genuine, non-empty diff that matches none of the four
        # tracked categories.
        before = "Heading\n=======\n\nSome text.\n\n\n\nMore text with trailing spaces.   \n"
        formatted = format_markdown_text(before)
        assert formatted != before
        assert classify_markdown_changes(before, formatted) == []

    def test_no_diff_returns_empty_list(self) -> None:
        assert classify_markdown_changes(_ALIGNED_TABLE, _ALIGNED_TABLE) == []


class TestBuildReformatMessage:
    """Tests for the pure ``_build_reformat_message`` advisory-text builder."""

    def test_single_label(self) -> None:
        message = _build_reformat_message("doc.md", [_LABEL_TABLE_PIPES])
        assert message == "Reformatted markdown in doc.md: aligned table pipes"

    def test_multiple_labels_joined_in_order(self) -> None:
        message = _build_reformat_message("doc.md", [_LABEL_TABLE_PIPES, _LABEL_ORDERED_LISTS])
        assert message == (
            "Reformatted markdown in doc.md: aligned table pipes, renumbered ordered lists"
        )

    def test_generic_fallback_when_no_labels(self) -> None:
        message = _build_reformat_message("doc.md", [])
        assert message == "Reformatted markdown in doc.md"


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


class TestConcurrentWriteIsNotDiscarded:
    """Reformatting must never cost content the handler did not write.

    ``handle`` reads the file, runs mdformat, then writes the result back. Under
    load a PostToolUse dispatch can lag well behind the edit that triggered it,
    so by the time the write lands the file may already hold NEWER content. A
    whole-file write from the stale snapshot silently reverts it.

    This is not theoretical: CLAUDE.md in this repository was written
    byte-identical to a snapshot taken three minutes earlier, dropping a line
    added in between, by a writer that left no backup.

    Skipping the write is the right response rather than reformatting the newer
    content — that newer write triggers its own PostToolUse event and will be
    formatted by it.
    """

    def test_write_landing_during_formatting_is_not_reverted(self, tmp_path: Path) -> None:
        """A newer write must survive a slow reformat of the older content."""
        path = tmp_path / "doc.md"
        path.write_text(_UNALIGNED_TABLE, encoding="utf-8")
        newer = "# Someone else got here first\n"

        def _format_then_someone_else_writes(text: str) -> str:
            path.write_text(newer, encoding="utf-8")
            return _ALIGNED_TABLE

        handler = MarkdownTableFormatterHandler()
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use."
            "markdown_table_formatter.format_markdown_text",
            side_effect=_format_then_someone_else_writes,
        ):
            result = handler.handle({"tool_name": "Write", "tool_input": {"file_path": str(path)}})

        assert (
            path.read_text(encoding="utf-8") == newer
        ), "the formatter silently reverted a write it did not make"
        assert result.decision == Decision.ALLOW
