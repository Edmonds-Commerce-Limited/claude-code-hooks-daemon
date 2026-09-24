"""Tests for the shared markdown formatting transform.

``format_markdown_text`` is the single source of truth for the canonical
mdformat+gfm reformat used by the markdown_table_formatter handler, the
format-markdown CLI command, and the CLAUDE.md injector. These tests pin
its behaviour so all three call sites stay identical.
"""

from claude_code_hooks_daemon.utils.markdown_format import (
    format_markdown_text,
    parse_frontmatter_yaml,
)


class TestFormatMarkdownText:
    """Behaviour of the shared format_markdown_text transform."""

    def test_aligns_table_pipes(self) -> None:
        """Unaligned GFM table pipes are aligned to consistent column widths."""
        unaligned = "# T\n\n| Name | Value |\n|---|---|\n| Short | x |\n| Very Long Name | y |\n"
        result = format_markdown_text(unaligned)
        # Every body/divider row should share the same pipe positions.
        rows = [line for line in result.splitlines() if line.startswith("|")]
        assert len(rows) >= 4
        pipe_positions = {tuple(i for i, c in enumerate(r) if c == "|") for r in rows}
        assert len(pipe_positions) == 1, f"pipes not aligned: {rows}"

    def test_idempotent(self) -> None:
        """Formatting already-formatted text is a no-op (stable output)."""
        unaligned = "# T\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        once = format_markdown_text(unaligned)
        twice = format_markdown_text(once)
        assert once == twice

    def test_preserves_yaml_frontmatter_byte_for_byte(self) -> None:
        """Leading YAML frontmatter is preserved exactly, not mangled."""
        doc = "---\nname: thing\ndescription: a test\n---\n\n# Body\n\ntext here\n"
        result = format_markdown_text(doc)
        assert result.startswith("---\nname: thing\ndescription: a test\n---\n")

    def test_restores_dash_thematic_breaks(self) -> None:
        """``---`` thematic breaks survive (not converted to 70 underscores)."""
        doc = "# A\n\ntext\n\n---\n\n# B\n\nmore\n"
        result = format_markdown_text(doc)
        assert "\n---\n" in result
        assert "_" * 70 not in result

    def test_preserves_consecutive_ordered_list_numbering(self) -> None:
        """Ordered lists keep 1. 2. 3. rather than collapsing to 1. 1. 1."""
        doc = "# L\n\n1. first\n2. second\n3. third\n"
        result = format_markdown_text(doc)
        assert "1. first" in result
        assert "2. second" in result
        assert "3. third" in result


class TestParseFrontmatterYaml:
    """``parse_frontmatter_yaml`` — the project's single frontmatter-to-dict
    parser (Plan 00460), reusing ``split_frontmatter`` rather than a second,
    subtly different splitter."""

    def test_parses_a_simple_mapping(self) -> None:
        doc = "---\nname: code-reviewer\ntools: Read, Grep\n---\n\nBody text.\n"
        assert parse_frontmatter_yaml(doc) == {"name": "code-reviewer", "tools": "Read, Grep"}

    def test_returns_none_when_no_frontmatter(self) -> None:
        assert parse_frontmatter_yaml("# Just a heading\n\nNo frontmatter here.\n") is None

    def test_returns_none_on_invalid_yaml(self) -> None:
        doc = "---\nname: [unclosed\n---\n\nBody.\n"
        assert parse_frontmatter_yaml(doc) is None

    def test_returns_none_when_frontmatter_is_not_a_mapping(self) -> None:
        doc = "---\n- just\n- a\n- list\n---\n\nBody.\n"
        assert parse_frontmatter_yaml(doc) is None
