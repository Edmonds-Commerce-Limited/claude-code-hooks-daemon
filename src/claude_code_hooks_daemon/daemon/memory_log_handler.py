"""In-memory circular log buffer for daemon logging.

Stores logs in memory to avoid I/O overhead during request processing.
Log cleanup happens asynchronously after responses are sent.
"""

import logging
from collections import deque


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
        except Exception:
            # Don't let logging errors break the daemon
            self.handleError(record)

    def get_logs(self, count: int | None = None) -> list[str]:
        """Get formatted log messages from buffer.

        Args:
            count: Number of recent logs to return (None = all)

        Returns:
            List of formatted log strings
        """
        records = list(self.records)
        if count is not None:
            records = records[-count:]

        return [self.format(record) for record in records]

    def clear(self) -> None:
        """Clear all logs from memory buffer."""
        self.records.clear()

    def get_record_count(self) -> int:
        """Get number of records currently in buffer.

        Returns:
            Number of log records stored
        """
        return len(self.records)
