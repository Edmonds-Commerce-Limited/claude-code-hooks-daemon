"""Tests for enhanced error message formatting.

This module tests the error formatter that provides user-friendly error messages
for common plugin loading failures, particularly abstract method violations.
"""

from claude_code_hooks_daemon.utils.error_formatter import (
    EnhancedError,
    detect_abstract_method_violation,
    format_plugin_load_error,
    get_version_for_method,
)


class TestDetectAbstractMethodViolation:
    """Test detection of abstract method violations in tracebacks."""

    def test_detects_get_acceptance_tests_missing(self) -> None:
        """Should detect when get_acceptance_tests() is not implemented."""
        traceback_text = """
Traceback (most recent call last):
  File "handler.py", line 10, in <module>
    handler = MyHandler()
TypeError: Can't instantiate abstract class MyHandler with abstract method get_acceptance_tests
"""
        result = detect_abstract_method_violation(traceback_text)

        assert result is not None
        assert result.class_name == "MyHandler"
        assert result.method_name == "get_acceptance_tests"

    def test_detects_multiple_abstract_methods(self) -> None:
        """Should detect when multiple abstract methods are missing."""
        traceback_text = """
TypeError: Can't instantiate abstract class MyHandler with abstract methods get_acceptance_tests, handle
"""
        result = detect_abstract_method_violation(traceback_text)

        assert result is not None
        assert result.class_name == "MyHandler"
        # Should return first method in list
        assert result.method_name == "get_acceptance_tests"

    def test_returns_none_for_non_abstract_errors(self) -> None:
        """Should return None for errors that aren't abstract method violations."""
        traceback_text = """
Traceback (most recent call last):
  File "handler.py", line 10, in <module>
    raise ValueError("Something went wrong")
ValueError: Something went wrong
"""
        result = detect_abstract_method_violation(traceback_text)
        assert result is None

    def test_handles_empty_traceback(self) -> None:
        """Should return None for empty traceback text."""
        result = detect_abstract_method_violation("")
        assert result is None


class TestGetVersionForMethod:
    """Test mapping of methods to versions where they became mandatory."""

    def test_get_acceptance_tests_maps_to_v2_13_0(self) -> None:
        """get_acceptance_tests() became mandatory in v2.13.0."""
        version = get_version_for_method("get_acceptance_tests")
        assert version == "2.13.0"

    def test_unknown_method_returns_none(self) -> None:
        """Unknown methods should return None."""
        version = get_version_for_method("some_random_method")
        assert version is None


class TestFormatPluginLoadError:
    """Test formatting of plugin load errors into user-friendly messages."""

    def test_formats_abstract_method_violation(self) -> None:
        """Should format abstract method violations with clear fix instructions."""
        exception_text = """
Traceback (most recent call last):
  File "handler.py", line 10, in <module>
    handler = MyHandler()
TypeError: Can't instantiate abstract class MyHandler with abstract method get_acceptance_tests
"""
        handler_path = ".claude/project-handlers/pre_tool_use/my_handler.py"

        result = format_plugin_load_error(exception_text, handler_path)

        assert isinstance(result, EnhancedError)
        assert "MyHandler" in result.summary
        assert "get_acceptance_tests" in result.summary
        assert "2.13.0" in result.details
        assert handler_path in result.details
        assert "HANDLER_DEVELOPMENT.md" in result.fix_instructions

    def test_formats_generic_import_error(self) -> None:
        """Should format generic import errors."""
        exception_text = """
Traceback (most recent call last):
  File "handler.py", line 5, in <module>
    from nonexistent import module
ImportError: cannot import name 'module' from 'nonexistent'
"""
        handler_path = ".claude/project-handlers/pre_tool_use/my_handler.py"

        result = format_plugin_load_error(exception_text, handler_path)

        assert isinstance(result, EnhancedError)
        assert "ImportError" in result.summary
        assert handler_path in result.details

    def test_returns_none_for_non_error_text(self) -> None:
        """Should return None if exception_text doesn't contain errors."""
        result = format_plugin_load_error("All good, no errors here", "handler.py")
        assert result is None


class TestEnhancedError:
    """Test the EnhancedError dataclass structure."""

    def test_creates_enhanced_error(self) -> None:
        """Should create EnhancedError with all fields."""
        error = EnhancedError(
            summary="Handler failed to load",
            details="MyHandler is missing get_acceptance_tests()",
            fix_instructions="Add the required method",
            handler_path="/path/to/handler.py",
        )

        assert error.summary == "Handler failed to load"
        assert "MyHandler" in error.details
        assert "Add the required method" in error.fix_instructions
        assert error.handler_path == "/path/to/handler.py"

    def test_formats_for_display(self) -> None:
        """Should provide formatted display text."""
        error = EnhancedError(
            summary="Abstract method violation",
            details="Missing get_acceptance_tests()",
            fix_instructions="Implement the method",
            handler_path="/handler.py",
        )

        display = error.format_for_display()

        assert "Abstract method violation" in display
        assert "Missing get_acceptance_tests()" in display
        assert "Implement the method" in display
        assert "/handler.py" in display
