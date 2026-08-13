"""Fixture for the ``unbounded-transcript-file-read`` semgrep rule (Plan 00232).

DELIBERATELY DEFECTIVE CODE. Nothing here is imported or executed — it exists
so the rule can be proved non-vacuous, and every function reconstructs a real
spelling of the defect this project shipped.

Markers drive the assertions in
``tests/unit/qa/test_semgrep_unbounded_source_reads.py``:

* ``# EXPECT-HIT``   — the rule MUST report this line
* ``# EXPECT-CLEAN`` — the rule MUST NOT report this line

Add a marker here and the test picks it up with no further wiring.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def read_transcript_deferred(transcript_path: Any) -> str:
    """The exact spelling the shipped defect used: bind, then read later."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return ""

    source = Path(transcript_path)
    if not source.is_file():
        logger.warning("Transcript path does not exist: %s", transcript_path)
        return ""

    return source.read_text()  # EXPECT-HIT


def read_transcript_direct(transcript_path: str) -> str:
    """The same defect written inline."""
    return Path(transcript_path).read_text()  # EXPECT-HIT


def read_transcript_bytes(transcript_path: str) -> bytes:
    """Same defect via read_bytes — no decode, same unbounded materialisation."""
    return Path(transcript_path).read_bytes()  # EXPECT-HIT


def read_transcript_via_open(transcript_path: str) -> str:
    """Same defect via a bare open().read()."""
    return open(transcript_path).read()  # EXPECT-HIT


def read_config_whole(config_path: str) -> str:
    """A config file is bounded by construction — reading it whole is correct."""
    return Path(config_path).read_text()  # EXPECT-CLEAN


def stream_transcript(transcript_path: str) -> int:
    """The CORRECT remedy: stream line by line, never materialising the file."""
    total = 0
    with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            total += len(line)
    return total  # EXPECT-CLEAN
