"""Strict mode error handling utilities.

Provides DRY helper for three-tier error handling architecture:
- TIER 1: Always fail fast (explicitly configured features)
- TIER 2: Strict mode controlled (discovered/optional features)
- TIER 3: Always graceful (legitimate exceptions)

This module handles TIER 2 errors.
"""

import logging

logger = logging.getLogger(__name__)


def handle_tier2_error(
    error: Exception,
    strict_mode: bool,
    error_message: str,
    graceful_message: str | None = None,
) -> None:
    """Handle TIER 2 errors based on strict_mode setting.

    TIER 2 errors are discovered/optional features that should:
    - CRASH in strict_mode (dogfooding, development)
    - Log and continue in non-strict mode (production graceful)

    Args:
        error: The exception that occurred
        strict_mode: Whether strict_mode is enabled
        error_message: Error message for strict mode crash
        graceful_message: Optional warning message for non-strict mode
                         (defaults to error_message if not provided)

    Raises:
        RuntimeError: If strict_mode is True, wrapping the original error
    """
    if strict_mode:
        # TIER 2: FAIL FAST in strict mode
        raise RuntimeError(error_message) from error
    else:
        # Non-strict: Log warning and continue (graceful)
        log_message = graceful_message if graceful_message else error_message
        logger.warning("%s: %s", log_message, error)


def crash_in_strict_mode(
    strict_mode: bool,
    error_message: str,
) -> None:
    """Crash with RuntimeError if strict_mode is enabled.

    Use this when you've detected an error condition (not caught an exception)
    and need to crash in strict mode.

    Args:
        strict_mode: Whether strict_mode is enabled
        error_message: Error message for the crash

    Raises:
        RuntimeError: If strict_mode is True
    """
    if strict_mode:
        raise RuntimeError(error_message)
    return None
