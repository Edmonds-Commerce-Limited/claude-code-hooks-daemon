"""The one sanctioned way to log a failure and carry on (owner ruling B4, N296).

A handler body that only logs and then continues, returns a fallback or passes
hides a failure behind a log line. The error-hiding audit
(``scripts/qa/audit_error_hiding.py``) flags every such body EXCEPT one that
calls :func:`log_and_continue`, whose required ``reason`` makes the decision to
swallow explicit and reviewable at the call site.
"""

from __future__ import annotations

import logging

from claude_code_hooks_daemon.utils.escape_hatch import is_acceptable_reason

#: Name the error-hiding audit recognises as the sanctioned form.
SANCTIONED_HELPER_NAME = "log_and_continue"


def log_and_continue(
    logger: logging.Logger,
    exc: BaseException,
    *,
    reason: str,
    level: int = logging.WARNING,
) -> None:
    """Log ``exc`` with ``reason`` and return, so the caller can carry on.

    Args:
        logger: Logger to record the failure on.
        exc: The caught exception; its traceback is attached to the record.
        reason: Why swallowing this failure is correct. Must be specific: an
            empty, closer-only or placeholder reason is rejected.
        level: Logging level for the record (default WARNING).

    Raises:
        ValueError: If ``reason`` is empty or a placeholder.
    """
    if not is_acceptable_reason(reason):
        raise ValueError(f"log_and_continue needs a specific reason, got: {reason!r}")
    logger.log(level, "%s: %s", reason, exc, exc_info=exc)
