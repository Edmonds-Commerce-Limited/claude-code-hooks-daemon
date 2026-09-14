"""In-memory circular log buffer for daemon logging.

Stores logs in memory to avoid I/O overhead during request processing.
Log cleanup happens asynchronously after responses are sent.
"""

import logging
from collections import deque

from claude_code_hooks_daemon.utils.log_elision import elide_record_arguments

logger = logging.getLogger(__name__)


class MemoryLogHandler(logging.Handler):
    """Logging handler that stores records in a circular in-memory buffer.

    Avoids file I/O overhead during request processing while maintaining
    a viewable log history.
    """

    def __init__(self, max_records: int = 1000) -> None:
        """Initialize memory log handler.

        Args:
            max_records: Maximum number of log records to keep in memory
        """
        super().__init__()
        self.max_records = max_records
        self.records: deque[logging.LogRecord] = deque(maxlen=max_records)

    def emit(self, record: logging.LogRecord) -> None:
        """Store log record in memory buffer.

        Args:
            record: Log record to store
        """
        try:
            # Store the record in circular buffer
            # deque with maxlen automatically drops oldest when full
            self.records.append(record)
        except (MemoryError, AttributeError, TypeError):
            # Expected errors in append/access
            self.handleError(record)
        except Exception as e:
            # Unexpected errors - log and handle
            logger.error("Unexpected error in memory log handler: %s", e, exc_info=True)
            self.handleError(record)

    def get_logs(self, count: int | None = None, *, elide_arguments: bool = False) -> list[str]:
        """Get formatted log messages from buffer.

        Args:
            count: Number of recent logs to return (None = all)
            elide_arguments: Render each record from its format string with the
                interpolated runtime values removed. Off by default, because
                an operator reading their own daemon's logs on their own
                machine has nothing to be protected from. Bug reports turn it
                on: they are generated to be shared on a public tracker, and a
                log window is whatever the user happened to be doing moments
                earlier rather than anything predictable (Plan 00403).

        Returns:
            List of formatted log strings
        """
        records = list(self.records)
        if count is not None:
            records = records[-count:]

        if not elide_arguments:
            return [self.format(record) for record in records]
        return [self.format(elide_record_arguments(record)) for record in records]

    def clear(self) -> None:
        """Clear all logs from memory buffer."""
        self.records.clear()

    def get_record_count(self) -> int:
        """Get number of records currently in buffer.

        Returns:
            Number of log records stored
        """
        return len(self.records)

    def get_claude_md(self) -> str | None:
        return None
