"""TranscriptArchiverHandler - archives conversation transcript before compaction."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.retention import prune_directory
from claude_code_hooks_daemon.utils.secret_redaction import (
    get_active_secret_terms,
    redact_structure,
    redact_text,
)

# Subdirectory under the daemon's untracked dir where archives are written.
_ARCHIVE_SUBDIR = "transcripts"

# Glob matching this handler's own archive files (used for retention pruning).
#
# Deliberately matches BOTH extensions. Plan 00232 changed the archive from a
# single JSON envelope (``.json``) to line-oriented JSONL (``.jsonl``); archives
# written by earlier versions are still on disk in client projects. A glob
# scoped to one extension would leave the other set permanently uncollected, so
# both share ONE retention budget rather than getting one each.
_ARCHIVE_GLOB = "transcript_*.json*"

# Extension for archives this version writes.
_ARCHIVE_EXTENSION = ".jsonl"

# Plan 00181 retention defaults: one full-transcript snapshot is written per
# compaction, so without a bound this directory grows forever (57 MB / 16 files
# observed in the wild). Keep the newest N and drop anything older than the age
# window. Both are config-overridable via
# ``handlers.pre_compact.transcript_archiver.options.{max_archives,max_archive_age_days}``
# (the registry injects them as ``self._max_archives`` / ``self._max_archive_age_days``).
_DEFAULT_MAX_ARCHIVES = 40
_DEFAULT_MAX_ARCHIVE_AGE_DAYS = 14
_SECONDS_PER_DAY = 86400

# Timestamp format for archive filenames (year-month-day_hour-minute-second).
_ARCHIVE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

# Key under which the archive timestamp is stored in the header line.
_ARCHIVE_KEY_ARCHIVED_AT = "archived_at"

# Key under which the originating transcript path is stored in the header line.
_ARCHIVE_KEY_SOURCE_PATH = "transcript_path"

# Key/value identifying the archive layout, so a future reader can tell a
# header-plus-JSONL archive from the legacy single-envelope JSON one.
_ARCHIVE_KEY_FORMAT = "archive_format"
_ARCHIVE_FORMAT = "jsonl-v1"

# Text encoding for both reading the transcript and writing the archive.
_ARCHIVE_ENCODING = "utf-8"

# A transcript is captured live and may be truncated mid-character or hold a
# stray byte. Strict decoding raised UnicodeDecodeError - a ValueError, which
# this handler's ``except OSError`` never caught, so the exception escaped and
# the compaction hook failed. Replacing the offending byte keeps the archive.
_ARCHIVE_DECODE_ERRORS = "replace"

# Separator between the header line and the transcript body.
_ARCHIVE_LINE_SEPARATOR = "\n"


class TranscriptArchiverHandler(Handler):
    """Archive conversation transcript before compaction.

    Saves transcript to timestamped file for historical reference and debugging.
    Non-terminal to allow compaction to proceed.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal archiver."""
        super().__init__(
            handler_id=HandlerID.TRANSCRIPT_ARCHIVER,
            priority=Priority.TRANSCRIPT_ARCHIVER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ARCHIVING, HandlerTag.NON_TERMINAL],
        )
        # Plan 00181 retention budget (config-overridable — the registry injects
        # matching ``options.*`` keys onto these private attributes).
        self._max_archives = _DEFAULT_MAX_ARCHIVES
        self._max_archive_age_days = _DEFAULT_MAX_ARCHIVE_AGE_DAYS

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all pre-compact events.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (archive all compactions)
        """
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Archive transcript to file.

        Claude Code's PreCompact event sends ``transcript_path`` pointing at a
        JSONL transcript file on disk (it does NOT inline the transcript). This
        reads that file and embeds its contents into the archive.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with allow decision (silent archiving)
        """
        try:
            # Resolve under the daemon's untracked dir so archives land in the
            # project tree regardless of process CWD (matches sibling handlers).
            archive_dir = ProjectContext.daemon_untracked_dir() / _ARCHIVE_SUBDIR
        except RuntimeError as e:
            # ProjectContext not initialised — happens in the default-config /
            # standalone entry-point branch where no project root is resolved.
            logger.warning("Skipping transcript archive (no project context): %s", e)
            return HookResult(decision=Decision.ALLOW)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)

        try:
            archive_dir.mkdir(parents=True, exist_ok=True)

            # Generate timestamp filename
            timestamp = datetime.now().strftime(_ARCHIVE_TIMESTAMP_FORMAT)
            archive_file = archive_dir / f"transcript_{timestamp}{_ARCHIVE_EXTENSION}"

            # Plan 00201: redact BEFORE anything reaches disk — a secret pasted
            # anywhere in the conversation must not survive into this archive.
            secret_terms = get_active_secret_terms()

            # The header carries the SOURCE PATH, which is itself a leak vector:
            # a transcript lives at ~/.claude/projects/<slug-of-project-path>/,
            # so a path-shaped secret term appears here in its slug spelling —
            # exactly the case ``_slug_variant`` exists to catch. Redacting only
            # the transcript body would have left it in the clear.
            header = redact_structure(
                {
                    _ARCHIVE_KEY_ARCHIVED_AT: datetime.now().isoformat(),
                    _ARCHIVE_KEY_SOURCE_PATH: transcript_path,
                    _ARCHIVE_KEY_FORMAT: _ARCHIVE_FORMAT,
                },
                secret_terms,
            )

            # Plan 00232: stream line by line. The previous whole-file read
            # produced a ~660 MB peak on a 72 MB transcript (one non-BMP char
            # promotes the whole str to 4 bytes/char, then redaction and JSON
            # escaping each hold another copy) — and it fired at PreCompact,
            # when memory is already scarce. JSONL is line-oriented and this is
            # a verbatim copy, so nothing needed the file in one piece.
            with archive_file.open("w", encoding=_ARCHIVE_ENCODING) as archive_handle:
                archive_handle.write(json.dumps(header))
                archive_handle.write(_ARCHIVE_LINE_SEPARATOR)
                self._stream_transcript(transcript_path, archive_handle, secret_terms)

            # Plan 00181: bound the archive directory so it cannot grow forever.
            # The file just written is newest, so it is always retained.
            self._prune_archives(archive_dir)

        except OSError as e:
            logger.warning("Failed to archive transcript: %s", e)

        return HookResult(decision=Decision.ALLOW)

    def _prune_archives(self, archive_dir: Path) -> None:
        """Bound the transcript archive directory to the configured budget.

        Keeps the newest ``self._max_archives`` files and drops anything older
        than ``self._max_archive_age_days``. Best-effort (never raises).
        """
        max_archives = getattr(self, "_max_archives", _DEFAULT_MAX_ARCHIVES)
        max_age_days = getattr(self, "_max_archive_age_days", _DEFAULT_MAX_ARCHIVE_AGE_DAYS)
        prune_directory(
            archive_dir,
            pattern=_ARCHIVE_GLOB,
            max_count=max_archives,
            max_age_seconds=max_age_days * _SECONDS_PER_DAY,
            now=time.time(),
        )

    @staticmethod
    def _stream_transcript(
        transcript_path: Any,
        destination: TextIO,
        secret_terms: tuple[str, ...],
    ) -> None:
        """Copy the transcript into ``destination`` one line at a time.

        Peak memory is the longest single LINE, not the file — which is the
        whole point of this handler's Plan 00232 rewrite. Nothing is buffered
        up: each line is read, redacted, and written before the next is read.

        Redacting per line is EQUIVALENT to redacting the whole text, not
        merely similar. ``redact_text`` applies independent per-term literal
        substitutions with no cross-line state, and ``load_secret_terms``
        strips every line it reads, so a term can never itself contain a
        newline — meaning no match can straddle a line boundary.

        A missing or invalid path writes no body at all, leaving an archive
        that is just its header. That is deliberate: the header still records
        what was attempted and when.

        Args:
            transcript_path: Path to the JSONL transcript file (from hook input)
            destination: Open text handle for the archive being written
            secret_terms: Secret terms to redact; empty disables redaction
        """
        if not isinstance(transcript_path, str) or not transcript_path:
            return

        source = Path(transcript_path)
        if not source.is_file():
            logger.warning("Transcript path does not exist: %s", transcript_path)
            return

        with source.open(
            "r", encoding=_ARCHIVE_ENCODING, errors=_ARCHIVE_DECODE_ERRORS
        ) as source_handle:
            for line in source_handle:
                destination.write(redact_text(line, secret_terms) if secret_terms else line)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="transcript archiver handler test",
                command='echo "test"',
                description="Tests transcript archiver handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="PreCompact event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
