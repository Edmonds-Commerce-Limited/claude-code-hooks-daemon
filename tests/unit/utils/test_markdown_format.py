"""Tests for the shared markdown formatting transform.

``format_markdown_text`` is the single source of truth for the canonical
mdformat+gfm reformat used by the markdown_table_formatter handler, the
format-markdown CLI command, and the CLAUDE.md injector. These tests pin
its behaviour so all three call sites stay identical.
"""

from claude_code_hooks_daemon.utils.markdown_format import (
    format_markdown_text,
    parse_frontmatter_lenient,
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


class TestParseFrontmatterLenient:
    """``parse_frontmatter_lenient`` (Plan 00468, audit P6): strict YAML
    first, then a top-level ``key: rest-of-line`` fallback.

    Claude Code loads agent files that ``yaml.safe_load`` rejects — this
    repository's own ``code-reviewer.md`` has ``: `` inside its description —
    so a strict-only parse made the daemon blind to agents Claude Code runs.
    """

    def test_valid_yaml_parses_exactly_as_strict_yaml_does(self) -> None:
        doc = "---\nname: x\ntools:\n  - Read\n  - Grep\nmaxTurns: 3\n---\n\nBody.\n"
        assert parse_frontmatter_lenient(doc) == parse_frontmatter_yaml(doc)

    def test_a_colon_in_a_description_no_longer_loses_the_file(self) -> None:
        doc = (
            "---\nname: code-reviewer\n"
            "description: Expert review. Analyzes real quality issues: dead code, confusion\n"
            "tools: Read, Glob, Grep, Bash\n---\n\nBody.\n"
        )
        assert parse_frontmatter_yaml(doc) is None
        parsed = parse_frontmatter_lenient(doc)
        assert parsed is not None
        assert parsed["name"] == "code-reviewer"
        assert parsed["tools"] == "Read, Glob, Grep, Bash"
        assert parsed["description"] == (
            "Expert review. Analyzes real quality issues: dead code, confusion"
        )

    def test_a_block_list_is_collected_in_the_fallback(self) -> None:
        doc = "---\nname: x\ndescription: a: b\ntools:\n  - Read\n  - Grep\n---\n"
        parsed = parse_frontmatter_lenient(doc)
        assert parsed is not None
        assert parsed["tools"] == ["Read", "Grep"]

    def test_quotes_around_a_scalar_are_removed(self) -> None:
        doc = "---\nname: \"quoted\"\ndescription: a: b\nisolation: 'worktree'\n---\n"
        parsed = parse_frontmatter_lenient(doc)
        assert parsed is not None
        assert parsed["name"] == "quoted"
        assert parsed["isolation"] == "worktree"

    def test_an_indented_continuation_folds_into_the_value(self) -> None:
        doc = "---\nname: x\ndescription: first: part\n  second part\n---\n"
        parsed = parse_frontmatter_lenient(doc)
        assert parsed is not None
        assert parsed["description"] == "first: part second part"

    def test_an_empty_value_is_none(self) -> None:
        doc = "---\nname: x\ndescription: a: b\ntools:\n---\n"
        parsed = parse_frontmatter_lenient(doc)
        assert parsed is not None
        assert parsed["tools"] is None

    def test_comments_and_blank_lines_are_skipped(self) -> None:
        doc = "---\n# a comment\n\nname: x\ndescription: a: b\n---\n"
        parsed = parse_frontmatter_lenient(doc)
        assert parsed == {"name": "x", "description": "a: b"}

    def test_no_frontmatter_is_still_none(self) -> None:
        assert parse_frontmatter_lenient("# Heading\n\nBody.\n") is None

    def test_a_block_with_no_key_lines_is_none(self) -> None:
        doc = "---\n- just\n- a\n- list\n---\n\nBody.\n"
        assert parse_frontmatter_lenient(doc) is None
