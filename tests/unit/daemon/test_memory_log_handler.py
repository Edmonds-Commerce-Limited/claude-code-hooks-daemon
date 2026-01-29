"""Tests for MemoryLogHandler."""

import logging
from unittest.mock import MagicMock

import pytest

from claude_code_hooks_daemon.daemon.memory_log_handler import MemoryLogHandler


class TestMemoryLogHandler:
    """Tests for MemoryLogHandler class."""

    @pytest.fixture
    def handler(self) -> MemoryLogHandler:
        """Create memory log handler for testing."""
        handler = MemoryLogHandler(max_records=100)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        return handler

    def test_initialization(self) -> None:
        """Handler should initialize with specified max records."""
        handler = MemoryLogHandler(max_records=50)
        assert handler.max_records == 50
        assert len(handler.records) == 0

    def test_initialization_default_max_records(self) -> None:
        """Handler should use default max_records if not specified."""
        handler = MemoryLogHandler()
        assert handler.max_records == 1000

    def test_emit_stores_record(self, handler: MemoryLogHandler) -> None:
        """emit should store log record in buffer."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        handler.emit(record)

        assert len(handler.records) == 1
        assert handler.records[0] is record

    def test_emit_multiple_records(self, handler: MemoryLogHandler) -> None:
        """emit should store multiple records in order."""
        records = [
            logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            for i in range(10)
        ]

        for record in records:
            handler.emit(record)

        assert len(handler.records) == 10
        assert list(handler.records) == records

    def test_emit_circular_buffer(self) -> None:
        """emit should drop oldest records when buffer is full."""
        handler = MemoryLogHandler(max_records=5)

        # Add more records than max_records
        for i in range(10):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        # Should only have last 5 records
        assert len(handler.records) == 5
        messages = [r.msg for r in handler.records]
        assert messages == ["Message 5", "Message 6", "Message 7", "Message 8", "Message 9"]

    def test_emit_handles_errors(self, handler: MemoryLogHandler) -> None:
        """emit should handle errors gracefully."""
        # Create a record that will cause an error during append
        # We'll mock the handleError method to verify it's called
        handler.handleError = MagicMock()  # type: ignore[method-assign]

        # Force an exception by making records raise on append
        original_records = handler.records
        handler.records = MagicMock()  # type: ignore[assignment]
        handler.records.append.side_effect = RuntimeError("Test error")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        handler.emit(record)

        # handleError should have been called
        handler.handleError.assert_called_once_with(record)

        # Restore original records
        handler.records = original_records

    def test_emit_handles_memory_error(self, handler: MemoryLogHandler) -> None:
        """emit should handle MemoryError specifically."""
        handler.handleError = MagicMock()  # type: ignore[method-assign]

        original_records = handler.records
        handler.records = MagicMock()  # type: ignore[assignment]
        handler.records.append.side_effect = MemoryError("Out of memory")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        handler.emit(record)

        # handleError should have been called
        handler.handleError.assert_called_once_with(record)

        # Restore original records
        handler.records = original_records

    def test_get_logs_all(self, handler: MemoryLogHandler) -> None:
        """get_logs should return all formatted logs when count is None."""
        # Add some records
        for i in range(5):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        logs = handler.get_logs()

        assert len(logs) == 5
        assert logs[0] == "INFO: Message 0"
        assert logs[4] == "INFO: Message 4"

    def test_get_logs_with_count(self, handler: MemoryLogHandler) -> None:
        """get_logs should return specified number of recent logs."""
        # Add 10 records
        for i in range(10):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        logs = handler.get_logs(count=3)

        assert len(logs) == 3
        assert logs[0] == "INFO: Message 7"
        assert logs[1] == "INFO: Message 8"
        assert logs[2] == "INFO: Message 9"

    def test_get_logs_count_larger_than_buffer(self, handler: MemoryLogHandler) -> None:
        """get_logs should return all logs if count > buffer size."""
        # Add 5 records
        for i in range(5):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        logs = handler.get_logs(count=100)

        assert len(logs) == 5

    def test_get_logs_empty_buffer(self, handler: MemoryLogHandler) -> None:
        """get_logs should return empty list for empty buffer."""
        logs = handler.get_logs()
        assert logs == []

    def test_get_logs_formatting(self) -> None:
        """get_logs should use handler's formatter."""
        handler = MemoryLogHandler(max_records=10)
        handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))

        record = logging.LogRecord(
            name="mylogger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        handler.emit(record)

        logs = handler.get_logs()
        assert logs[0] == "mylogger - Test message"

    def test_clear(self, handler: MemoryLogHandler) -> None:
        """clear should remove all records from buffer."""
        # Add some records
        for i in range(10):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        assert len(handler.records) == 10

        handler.clear()

        assert len(handler.records) == 0
        assert handler.get_logs() == []

    def test_get_record_count_empty(self, handler: MemoryLogHandler) -> None:
        """get_record_count should return 0 for empty buffer."""
        assert handler.get_record_count() == 0

    def test_get_record_count_with_records(self, handler: MemoryLogHandler) -> None:
        """get_record_count should return number of records in buffer."""
        for i in range(7):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        assert handler.get_record_count() == 7

    def test_get_record_count_after_clear(self, handler: MemoryLogHandler) -> None:
        """get_record_count should return 0 after clear."""
        for i in range(5):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=i,
                msg=f"Message {i}",
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        handler.clear()

        assert handler.get_record_count() == 0

    def test_different_log_levels(self, handler: MemoryLogHandler) -> None:
        """Handler should work with different log levels."""
        levels = [
            (logging.DEBUG, "DEBUG", "Debug message"),
            (logging.INFO, "INFO", "Info message"),
            (logging.WARNING, "WARNING", "Warning message"),
            (logging.ERROR, "ERROR", "Error message"),
            (logging.CRITICAL, "CRITICAL", "Critical message"),
        ]

        for level, level_name, msg in levels:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="test.py",
                lineno=10,
                msg=msg,
                args=(),
                exc_info=None,
            )
            handler.emit(record)

        logs = handler.get_logs()
        assert len(logs) == 5

        for (_, level_name, msg), log in zip(levels, logs):
            assert log == f"{level_name}: {msg}"

    def test_integration_with_logger(self) -> None:
        """Handler should work with real logger."""
        handler = MemoryLogHandler(max_records=10)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        logger = logging.getLogger("test_logger")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")

        logs = handler.get_logs()
        assert len(logs) == 3
        assert "INFO: Test info message" in logs
        assert "WARNING: Test warning message" in logs
        assert "ERROR: Test error message" in logs

        # Cleanup
        logger.removeHandler(handler)
