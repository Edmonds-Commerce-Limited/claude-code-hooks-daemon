"""Tests for formatting constants.

Tests that all formatting limits are properly defined and have
reasonable values for their display purposes.
"""


from claude_code_hooks_daemon.constants.formatting import FormatLimit


class TestHashDisplayLimits:
    """Tests for hash display length constants."""

    def test_hash_lengths(self) -> None:
        """Test hash length constants."""
        assert FormatLimit.HASH_LENGTH == 8
        assert FormatLimit.HASH_LENGTH_FULL == 40

    def test_hash_length_is_reasonable(self) -> None:
        """Test that hash lengths are reasonable."""
        # Short hash should be 7-10 chars (8 is git standard)
        assert 7 <= FormatLimit.HASH_LENGTH <= 10
        # Full hash is SHA-1 (40 hex chars)
        assert FormatLimit.HASH_LENGTH_FULL == 40

    def test_hash_truncation_pattern(self) -> None:
        """Test hash truncation usage pattern."""
        full_hash = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
        short_hash = full_hash[: FormatLimit.HASH_LENGTH]
        assert len(short_hash) == 8
        assert short_hash == "a1b2c3d4"


class TestNameTruncationLimits:
    """Tests for name truncation limits."""

    def test_name_truncation_limits(self) -> None:
        """Test name truncation limit constants."""
        assert FormatLimit.PROJECT_NAME_MAX == 20
        assert FormatLimit.HANDLER_NAME_MAX_DISPLAY == 30
        assert FormatLimit.SESSION_ID_DISPLAY == 8

    def test_name_limits_are_reasonable(self) -> None:
        """Test that name limits are reasonable for display."""
        # Project names should fit in narrow displays
        assert FormatLimit.PROJECT_NAME_MAX <= 30
        # Handler names need more space
        assert FormatLimit.HANDLER_NAME_MAX_DISPLAY >= 20
        # Session IDs should be short
        assert FormatLimit.SESSION_ID_DISPLAY <= 12


class TestPreviewLengthLimits:
    """Tests for preview and snippet length limits."""

    def test_preview_lengths(self) -> None:
        """Test preview length constants."""
        assert FormatLimit.REASON_PREVIEW_LENGTH == 50
        assert FormatLimit.CONTEXT_PREVIEW_LENGTH == 100
        assert FormatLimit.ERROR_MESSAGE_PREVIEW == 200
        assert FormatLimit.TOOL_INPUT_PREVIEW == 150

    def test_preview_lengths_are_ordered(self) -> None:
        """Test that preview lengths are ordered by importance."""
        # Reason < Context < Tool Input < Error
        assert FormatLimit.REASON_PREVIEW_LENGTH < FormatLimit.CONTEXT_PREVIEW_LENGTH
        assert FormatLimit.CONTEXT_PREVIEW_LENGTH < FormatLimit.TOOL_INPUT_PREVIEW
        assert FormatLimit.TOOL_INPUT_PREVIEW < FormatLimit.ERROR_MESSAGE_PREVIEW

    def test_reason_preview_pattern(self) -> None:
        """Test reason preview truncation pattern."""
        long_reason = "This is a very long reason that exceeds the preview length limit"
        preview = long_reason[: FormatLimit.REASON_PREVIEW_LENGTH]
        assert len(preview) == 50


class TestDisplayWidthLimits:
    """Tests for display width assumptions."""

    def test_terminal_widths(self) -> None:
        """Test terminal width constants."""
        assert FormatLimit.TERMINAL_WIDTH_DEFAULT == 80
        assert FormatLimit.TERMINAL_WIDTH_WIDE == 120
        assert FormatLimit.STATUS_LINE_MAX_WIDTH == 100

    def test_terminal_width_relationships(self) -> None:
        """Test that terminal widths have appropriate relationships."""
        # Default < Wide
        assert FormatLimit.TERMINAL_WIDTH_DEFAULT < FormatLimit.TERMINAL_WIDTH_WIDE
        # Status line should fit in default terminal
        assert FormatLimit.STATUS_LINE_MAX_WIDTH <= FormatLimit.TERMINAL_WIDTH_WIDE


class TestColumnWidthLimits:
    """Tests for column width limits."""

    def test_column_widths(self) -> None:
        """Test column width constants."""
        assert FormatLimit.COLUMN_HANDLER_NAME == 30
        assert FormatLimit.COLUMN_PRIORITY == 8
        assert FormatLimit.COLUMN_STATUS == 10
        assert FormatLimit.COLUMN_TAGS == 40

    def test_column_widths_sum_reasonably(self) -> None:
        """Test that column widths can fit in terminal."""
        total_width = (
            FormatLimit.COLUMN_HANDLER_NAME
            + FormatLimit.COLUMN_PRIORITY
            + FormatLimit.COLUMN_STATUS
            + FormatLimit.COLUMN_TAGS
        )
        # Should fit in wide terminal with spacing
        assert total_width <= FormatLimit.TERMINAL_WIDTH_WIDE


class TestPaddingAndAlignment:
    """Tests for padding and alignment constants."""

    def test_padding_values(self) -> None:
        """Test padding and indentation constants."""
        assert FormatLimit.INDENT_SPACES == 2
        assert FormatLimit.LIST_INDENT == 4

    def test_indent_relationships(self) -> None:
        """Test that indentation values have appropriate relationships."""
        # List indent should be larger than basic indent
        assert FormatLimit.LIST_INDENT >= FormatLimit.INDENT_SPACES


class TestNumberFormatting:
    """Tests for number formatting precision."""

    def test_precision_values(self) -> None:
        """Test number formatting precision constants."""
        assert FormatLimit.DURATION_PRECISION == 2
        assert FormatLimit.PERCENTAGE_PRECISION == 1

    def test_precision_is_reasonable(self) -> None:
        """Test that precision values are reasonable."""
        # Precision should be 0-3 decimal places
        assert 0 <= FormatLimit.DURATION_PRECISION <= 3
        assert 0 <= FormatLimit.PERCENTAGE_PRECISION <= 3

    def test_duration_formatting_pattern(self) -> None:
        """Test duration formatting usage pattern."""
        duration = 1.23456
        formatted = f"{duration:.{FormatLimit.DURATION_PRECISION}f}"
        assert formatted == "1.23"

    def test_percentage_formatting_pattern(self) -> None:
        """Test percentage formatting usage pattern."""
        percentage = 95.67
        formatted = f"{percentage:.{FormatLimit.PERCENTAGE_PRECISION}f}"
        assert formatted == "95.7"


class TestFormatLimitTypes:
    """Tests for format limit types."""

    def test_all_limits_are_integers(self) -> None:
        """Test that all format limits are integers."""
        for key, value in vars(FormatLimit).items():
            if not key.startswith("_"):
                assert isinstance(value, int), f"{key} should be an integer"

    def test_all_limits_are_positive(self) -> None:
        """Test that all format limits are positive."""
        for key, value in vars(FormatLimit).items():
            if not key.startswith("_") and isinstance(value, int):
                assert value > 0, f"{key}={value} should be positive"


class TestFormatLimitExport:
    """Tests for module exports."""

    def test_all_exports(self) -> None:
        """Test that __all__ contains expected exports."""
        from claude_code_hooks_daemon.constants import formatting

        assert hasattr(formatting, "__all__")
        assert "FormatLimit" in formatting.__all__

    def test_format_limit_importable_from_constants(self) -> None:
        """Test that FormatLimit can be imported from constants package."""
        from claude_code_hooks_daemon.constants import FormatLimit as ImportedFormatLimit

        assert ImportedFormatLimit.HASH_LENGTH == 8
        assert ImportedFormatLimit.PROJECT_NAME_MAX == 20


class TestFormatUsagePatterns:
    """Tests for format limit usage patterns."""

    def test_string_truncation_pattern(self) -> None:
        """Test string truncation usage pattern."""
        long_string = "This is a very long project name that needs truncation"
        truncated = long_string[: FormatLimit.PROJECT_NAME_MAX]
        assert len(truncated) <= FormatLimit.PROJECT_NAME_MAX

    def test_display_width_check_pattern(self) -> None:
        """Test display width check pattern."""
        text = "Some status line text"
        fits_in_status = len(text) <= FormatLimit.STATUS_LINE_MAX_WIDTH
        assert fits_in_status is True

    def test_column_alignment_pattern(self) -> None:
        """Test column alignment usage pattern."""
        handler_name = "my-handler"
        # Pad to column width
        padded = handler_name.ljust(FormatLimit.COLUMN_HANDLER_NAME)
        assert len(padded) == FormatLimit.COLUMN_HANDLER_NAME


class TestCommonFormattingScenarios:
    """Tests for common formatting scenarios."""

    def test_log_entry_formatting(self) -> None:
        """Test typical log entry formatting."""
        # Typical log entry: [HASH] Handler: Reason
        hash_part = "a1b2c3d4"[: FormatLimit.HASH_LENGTH]
        handler_part = "my-handler"[: FormatLimit.HANDLER_NAME_MAX_DISPLAY]
        reason_part = "Some reason"[: FormatLimit.REASON_PREVIEW_LENGTH]

        assert len(hash_part) <= FormatLimit.HASH_LENGTH
        assert len(handler_part) <= FormatLimit.HANDLER_NAME_MAX_DISPLAY
        assert len(reason_part) <= FormatLimit.REASON_PREVIEW_LENGTH

    def test_status_display_formatting(self) -> None:
        """Test status display formatting."""
        # Typical status display with columns
        handler_col = "handler-name".ljust(FormatLimit.COLUMN_HANDLER_NAME)
        priority_col = "50".rjust(FormatLimit.COLUMN_PRIORITY)
        status_col = "enabled".ljust(FormatLimit.COLUMN_STATUS)

        assert len(handler_col) == FormatLimit.COLUMN_HANDLER_NAME
        assert len(priority_col) == FormatLimit.COLUMN_PRIORITY
        assert len(status_col) == FormatLimit.COLUMN_STATUS
