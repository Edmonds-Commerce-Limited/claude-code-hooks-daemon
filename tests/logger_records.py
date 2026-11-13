"""Records of one logger out of a ``caplog`` capture.

``caplog`` hangs its handler on the ROOT logger, so it collects every record any
logger in the process emits while a test runs: a daemon thread, a worker, a
neighbouring test under a parallel run. A test that asserts the whole capture is
empty therefore passes alone and fails under load. Assert on the records of the
logger under test instead.
"""

from __future__ import annotations

import logging

import pytest


def records_from(caplog: pytest.LogCaptureFixture, logger_name: str) -> list[logging.LogRecord]:
    """The captured records emitted by exactly ``logger_name``."""
    return [record for record in caplog.records if record.name == logger_name]
