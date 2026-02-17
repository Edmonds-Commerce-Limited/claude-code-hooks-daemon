"""Enhanced error message formatting for plugin load failures.

This module provides user-friendly error messages for common plugin loading
failures, particularly abstract method violations that became more common
after v2.13.0 made get_acceptance_tests() mandatory for handlers.
"""

import re
from dataclasses import dataclass


@dataclass
class AbstractMethodInfo:
    """Information about an abstract method violation."""

    class_name: str
    method_name: str


@dataclass
class EnhancedError:
    """Enhanced error information with user-friendly formatting."""

    summary: str
    details: str
    fix_instructions: str
    handler_path: str

    def format_for_display(self) -> str:
        """Format error for display to users.

        Returns:
            Formatted error message with sections separated by newlines.
        """
        return f"""
❌ {self.summary}

Details:
{self.details}

Fix:
{self.fix_instructions}

Handler: {self.handler_path}
""".strip()


# Version mapping for methods that became mandatory
_METHOD_VERSION_MAP = {
    "get_acceptance_tests": "2.13.0",
}


def detect_abstract_method_violation(traceback_text: str) -> AbstractMethodInfo | None:
    """Detect abstract method violations in exception tracebacks.

    Args:
        traceback_text: The exception traceback as a string.

    Returns:
        AbstractMethodInfo if an abstract method violation is detected, None otherwise.
    """
    if not traceback_text:
        return None

    # Pattern: "Can't instantiate abstract class ClassName with abstract method(s) method_name"
    # Handles both singular "method" and plural "methods"
    pattern = r"Can't instantiate abstract class (\w+) with abstract methods? ([\w, ]+)"
    match = re.search(pattern, traceback_text)

    if not match:
        return None

    class_name = match.group(1)
    methods_str = match.group(2)

    # If multiple methods, take the first one
    method_name = methods_str.split(",")[0].strip()

    return AbstractMethodInfo(class_name=class_name, method_name=method_name)


def get_version_for_method(method_name: str) -> str | None:
    """Get the version where a method became mandatory.

    Args:
        method_name: Name of the method.

    Returns:
        Version string (e.g., "2.13.0") or None if method is not tracked.
    """
    return _METHOD_VERSION_MAP.get(method_name)


def format_plugin_load_error(exception_text: str, handler_path: str) -> EnhancedError | None:
    """Format a plugin load error into a user-friendly message.

    Args:
        exception_text: The exception traceback/message as a string.
        handler_path: Path to the handler that failed to load.

    Returns:
        EnhancedError if formatting is possible, None otherwise.
    """
    # Check if this is an error at all
    if "Error" not in exception_text and "Exception" not in exception_text:
        return None

    # Try to detect abstract method violation
    violation = detect_abstract_method_violation(exception_text)

    if violation:
        version = get_version_for_method(violation.method_name)
        version_info = f" (mandatory since v{version})" if version else ""

        summary = (
            f"Handler '{violation.class_name}' missing required method: "
            f"{violation.method_name}(){version_info}"
        )

        details = f"""
Handler class '{violation.class_name}' must implement '{violation.method_name}()' method.

This method became mandatory in daemon version {version or 'a recent version'}.

Handler location: {handler_path}
""".strip()

        fix_instructions = f"""
1. Open {handler_path}
2. Add the '{violation.method_name}()' method to your handler class
3. See CLAUDE/HANDLER_DEVELOPMENT.md for implementation examples
4. Restart daemon: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
""".strip()

        return EnhancedError(
            summary=summary,
            details=details,
            fix_instructions=fix_instructions,
            handler_path=handler_path,
        )

    # Generic error formatting for other types
    # Extract error type from traceback
    error_type_match = re.search(r"(\w+Error): (.+)$", exception_text, re.MULTILINE)
    if error_type_match:
        error_type = error_type_match.group(1)
        error_msg = error_type_match.group(2)

        summary = f"{error_type} loading handler"

        details = f"""
Handler failed to load: {handler_path}

Error: {error_msg}

Full traceback available in daemon logs.
""".strip()

        fix_instructions = f"""
1. Check the handler file for syntax errors: {handler_path}
2. Verify all imports are available
3. Check daemon logs for full traceback:
   $PYTHON -m claude_code_hooks_daemon.daemon.cli logs
""".strip()

        return EnhancedError(
            summary=summary,
            details=details,
            fix_instructions=fix_instructions,
            handler_path=handler_path,
        )

    return None
