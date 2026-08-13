"""Comprehensive tests for TranscriptArchiverHandler."""

import json
import os
import time
import tracemalloc
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver import (
    TranscriptArchiverHandler,
)
from claude_code_hooks_daemon.utils.secret_redaction import redact_text

_FIXED_TIMESTAMP = "20240120_103000"
_FIXED_ISOFORMAT = "2024-01-20T10:30:00"

# Archive filename this handler writes under the mocked timestamp.
_ARCHIVE_NAME = f"transcript_{_FIXED_TIMESTAMP}.jsonl"


class TestTranscriptArchiverHandler:
    """Test suite for TranscriptArchiverHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return TranscriptArchiverHandler()

    @pytest.fixture
    def archive_dir(self, tmp_path):
        """Patch ProjectContext.daemon_untracked_dir to a temp directory."""
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "ProjectContext.daemon_untracked_dir",
            return_value=untracked,
        ):
            yield untracked / "transcripts"

    @pytest.fixture
    def transcript_file(self, tmp_path):
        """Create a real JSONL transcript fixture file on disk."""
        path = tmp_path / "session-transcript.jsonl"
        path.write_text(
            '{"role": "user", "content": "Hello"}\n'
            '{"role": "assistant", "content": "Hi there"}\n'
        )
        return path

    @pytest.fixture
    def mock_datetime(self):
        """Mock datetime.now() to return fixed timestamp."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver.datetime"
        ) as mock_dt:
            mock_now = mock_dt.now.return_value
            mock_now.strftime.return_value = _FIXED_TIMESTAMP
            mock_now.isoformat.return_value = _FIXED_ISOFORMAT
            yield mock_dt

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'transcript-archiver'."""
        assert handler.name == "transcript-archiver"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal."""
        assert handler.terminal is False

    def test_matches_always_returns_true(self, handler):
        """Should match all pre-compact events."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: "/tmp/whatever.jsonl"}
        assert handler.matches(hook_input) is True

    def test_handle_prunes_old_archives_beyond_max(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Plan 00181: the archive dir is bounded to max_archives (newest kept)."""
        handler._max_archives = 3
        handler._max_archive_age_days = 3650  # effectively disable age pruning here
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Five pre-existing archives with RECENT, ordered mtimes (so only the
        # count criterion binds — ancient mtimes would trip age pruning instead).
        base = time.time() - 100.0
        for i in range(5):
            old = archive_dir / f"transcript_old{i}.json"
            old.write_text("{}")
            os.utime(old, (base + i, base + i))

        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        handler.handle(hook_input)

        remaining = {p.name for p in archive_dir.glob("transcript_*.json*")}
        # The just-written file (real 'now', newest) always survives; only the
        # two most-recent pre-existing archives remain alongside it.
        assert len(remaining) == 3
        assert _ARCHIVE_NAME in remaining
        assert "transcript_old4.json" in remaining
        assert "transcript_old0.json" not in remaining

    def test_handle_prunes_archives_older_than_age_window(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Age-based pruning: an ancient archive is dropped even under the count."""
        handler._max_archives = 100  # count does not bind here
        handler._max_archive_age_days = 1
        archive_dir.mkdir(parents=True, exist_ok=True)
        ancient = archive_dir / "transcript_ancient.json"
        ancient.write_text("{}")
        os.utime(ancient, (1000.0, 1000.0))  # epoch 1970 -> far older than 1 day

        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        handler.handle(hook_input)

        assert not ancient.exists()
        assert (archive_dir / _ARCHIVE_NAME).exists()

    def test_handle_creates_archive_directory(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Should create archive directory if it doesn't exist."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        handler.handle(hook_input)

        assert archive_dir.is_dir()

    def test_handle_saves_transcript_with_timestamp(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Should save transcript with timestamp in filename."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        expected = archive_dir / _ARCHIVE_NAME
        assert expected.is_file()

    def test_handle_embeds_transcript_file_contents(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Should read the transcript_path file and copy its contents.

        Regression: previously the handler read an inline ``transcript`` key
        which Claude Code never sends, producing empty archives in production.
        """
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        archive_file = archive_dir / _ARCHIVE_NAME
        # Plan 00232: header line, then the transcript verbatim.
        body = archive_file.read_text().split("\n", 1)[1]

        assert body == transcript_file.read_text()
        assert body != ""
        assert "Hello" in body
        assert "Hi there" in body

    def test_handle_redacts_secret_term_from_archived_transcript(
        self, handler, archive_dir, tmp_path, mock_datetime
    ):
        """Plan 00201: a secret pasted into the conversation must not survive archiving."""
        transcript_path = tmp_path / "session-transcript.jsonl"
        transcript_path.write_text(
            '{"role": "user", "content": "contains zzqx-nonsense-term here"}\n'
        )
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_path)}

        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "get_active_secret_terms",
            return_value=("zzqx-nonsense-term",),
        ):
            handler.handle(hook_input)

        archive_file = archive_dir / _ARCHIVE_NAME
        assert "zzqx-nonsense-term" not in archive_file.read_text()

    def test_handle_no_terms_configured_archives_unredacted(
        self, handler, archive_dir, tmp_path, mock_datetime
    ):
        transcript_path = tmp_path / "session-transcript.jsonl"
        transcript_path.write_text('{"role": "user", "content": "plain content"}\n')
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_path)}

        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "get_active_secret_terms",
            return_value=(),
        ):
            handler.handle(hook_input)

        archive_file = archive_dir / _ARCHIVE_NAME
        assert "plain content" in archive_file.read_text()

    def test_handle_records_source_path(self, handler, archive_dir, transcript_file, mock_datetime):
        """Should record the originating transcript path in the header."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        archive_file = archive_dir / _ARCHIVE_NAME
        header = json.loads(archive_file.read_text().split("\n", 1)[0])

        assert header["transcript_path"] == str(transcript_file)

    def test_handle_includes_metadata(self, handler, archive_dir, transcript_file, mock_datetime):
        """Should include metadata in the header line."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        archive_file = archive_dir / _ARCHIVE_NAME
        header = json.loads(archive_file.read_text().split("\n", 1)[0])

        assert "archived_at" in header
        assert "transcript_path" in header
        assert "archive_format" in header

    def test_handle_empty_when_no_transcript_path(self, handler, archive_dir, mock_datetime):
        """No path provided: a header-only archive, with no body."""
        hook_input: dict = {}

        handler.handle(hook_input)

        archive_file = archive_dir / _ARCHIVE_NAME
        header_line, body = archive_file.read_text().split("\n", 1)

        assert json.loads(header_line)["transcript_path"] is None
        assert body == ""

    def test_handle_empty_when_transcript_path_missing_file(
        self, handler, archive_dir, tmp_path, mock_datetime
    ):
        """File does not exist: a header-only archive, with no body."""
        missing = tmp_path / "does-not-exist.jsonl"
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(missing)}

        handler.handle(hook_input)

        archive_file = archive_dir / _ARCHIVE_NAME
        header_line, body = archive_file.read_text().split("\n", 1)

        assert json.loads(header_line)["transcript_path"] == str(missing)
        assert body == ""

    def test_handle_returns_allow_decision(self, handler, archive_dir, transcript_file):
        """Should return allow decision."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_gracefully_handles_write_errors(self, handler, archive_dir, transcript_file):
        """Should handle file write errors gracefully."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        with patch.object(Path, "open", side_effect=OSError("Write error")):
            result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_gracefully_handles_missing_project_context(self, handler):
        """Should return allow when ProjectContext is not initialised."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: "/tmp/x.jsonl"}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "ProjectContext.daemon_untracked_dir",
            side_effect=RuntimeError("no project context"),
        ):
            result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_returns_hook_result_instance(self, handler, archive_dir, transcript_file):
        """Should return HookResult instance."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)


class TestTranscriptArchiverStreaming:
    """Plan 00232: archiving must not materialise the whole transcript.

    The defect these pin: a 72 MB transcript produced a ~660 MB RSS spike,
    because ``read_text()`` built one ``str`` (promoted to 4 bytes/char by a
    single emoji), ``redact_text`` copied it, and ``json.dump`` escaped it into
    a third buffer — all at PreCompact, when memory is already scarce.
    """

    # Big enough that a whole-file read is unmistakable against the assertion
    # below, small enough that the fixture writes in well under a second.
    _LINE_COUNT = 20_000
    _PAYLOAD = "x" * 400

    @pytest.fixture
    def handler(self):
        return TranscriptArchiverHandler()

    @pytest.fixture
    def archive_dir(self, tmp_path):
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "ProjectContext.daemon_untracked_dir",
            return_value=untracked,
        ):
            yield untracked / "transcripts"

    @pytest.fixture
    def mock_datetime(self):
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver.datetime"
        ) as mock_dt:
            mock_now = mock_dt.now.return_value
            mock_now.strftime.return_value = _FIXED_TIMESTAMP
            mock_now.isoformat.return_value = _FIXED_ISOFORMAT
            yield mock_dt

    @pytest.fixture
    def large_transcript(self, tmp_path):
        """A multi-megabyte transcript containing a non-BMP character.

        The emoji is load-bearing, not decoration: ONE non-BMP character
        anywhere in the file promotes the entire Python ``str`` to 4 bytes per
        character, which is what turned 72 MB into ~288 MB in the field.
        """
        path = tmp_path / "large-session.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            handle.write('{"role": "user", "content": "start 🚀"}\n')
            for index in range(self._LINE_COUNT):
                handle.write(f'{{"i": {index}, "content": "{self._PAYLOAD}"}}\n')
            handle.write('{"role": "assistant", "content": "end"}\n')
        return path

    def test_peak_memory_is_bounded_by_line_not_by_file(
        self, handler, archive_dir, large_transcript, mock_datetime
    ):
        """Peak allocation must be a function of the longest LINE, not the file.

        This is the non-vacuity guard for the whole plan. Run against the
        pre-fix implementation it fails outright, because ``read_text()`` alone
        allocates more than the file's size on disk.
        """
        file_size = large_transcript.stat().st_size
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(large_transcript)}

        tracemalloc.start()
        try:
            handler.handle(hook_input)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        # Generous: an eighth of the file. The old implementation's peak was
        # several times the file size, so this cannot pass by accident, while
        # leaving ample headroom for interpreter noise and I/O buffers.
        assert peak < file_size // 8, (
            f"peak allocation {peak} bytes is not bounded by line size "
            f"(transcript is {file_size} bytes) — the whole file was materialised"
        )

    def test_archive_is_faithful_every_line_in_order(
        self, handler, archive_dir, large_transcript, mock_datetime
    ):
        """Streaming must not drop, reorder, or truncate any transcript line."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(large_transcript)}

        handler.handle(hook_input)

        archived = (archive_dir / _ARCHIVE_NAME).read_text(encoding="utf-8").splitlines()
        source_lines = large_transcript.read_text(encoding="utf-8").splitlines()

        # Line 1 is the metadata header this handler adds; the rest is verbatim.
        assert archived[1:] == source_lines
        assert "🚀" in archived[1]

    def test_header_line_is_parseable_metadata(
        self, handler, archive_dir, large_transcript, mock_datetime
    ):
        """The first line is a JSON object describing the archive."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(large_transcript)}

        handler.handle(hook_input)

        first_line = (archive_dir / _ARCHIVE_NAME).read_text(encoding="utf-8").split("\n")[0]
        header = json.loads(first_line)

        assert header["transcript_path"] == str(large_transcript)
        assert header["archived_at"] == _FIXED_ISOFORMAT
        assert header["archive_format"]

    def test_per_line_redaction_matches_whole_text_redaction(
        self, handler, archive_dir, tmp_path, mock_datetime
    ):
        """Redacting line-by-line must be IDENTICAL to redacting the whole text.

        Safe because a secret term can never contain a newline —
        ``load_secret_terms`` strips each line — so no match can straddle the
        line boundary that streaming introduces.
        """
        terms = ("zzqx-nonsense-term", "second/secret/path")
        transcript_path = tmp_path / "session.jsonl"
        body = (
            '{"content": "leading zzqx-nonsense-term trailing"}\n'
            '{"content": "ZZQX-NONSENSE-TERM uppercase"}\n'
            '{"content": "zzqx_nonsense_term underscore spelling"}\n'
            '{"content": "second/secret/path and its second_secret_path slug"}\n'
            '{"content": "clean line"}\n'
        )
        transcript_path.write_text(body, encoding="utf-8")
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_path)}

        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "get_active_secret_terms",
            return_value=terms,
        ):
            handler.handle(hook_input)

        archived = (archive_dir / _ARCHIVE_NAME).read_text(encoding="utf-8")
        transcript_part = archived.split("\n", 1)[1]

        assert transcript_part == redact_text(body, terms)
        for term in terms:
            assert term not in archived

    def test_source_path_in_header_is_redacted(
        self, handler, archive_dir, tmp_path, mock_datetime
    ):
        """Plan 00232: the HEADER's source path is a leak vector too.

        A transcript lives at ``~/.claude/projects/<slug-of-project-path>/``,
        so a path-shaped secret term appears in the archive header in its slug
        spelling — the exact case ``secret_redaction._slug_variant`` exists to
        catch. The pre-existing code redacted only the transcript BODY, which
        left the path in the clear in every archive.
        """
        secret_dir = tmp_path / "zzqx-secret-project"
        secret_dir.mkdir()
        transcript_path = secret_dir / "session.jsonl"
        transcript_path.write_text('{"content": "nothing sensitive here"}\n', encoding="utf-8")

        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "get_active_secret_terms",
            return_value=("zzqx-secret-project",),
        ):
            handler.handle({HookInputField.TRANSCRIPT_PATH: str(transcript_path)})

        archived = (archive_dir / _ARCHIVE_NAME).read_text(encoding="utf-8")
        assert "zzqx-secret-project" not in archived
        # The header must still be parseable JSON after redaction.
        assert json.loads(archived.split("\n", 1)[0])["transcript_path"]

    def test_legacy_json_archives_are_still_pruned(
        self, handler, archive_dir, large_transcript, mock_datetime
    ):
        """The extension change must not strand pre-existing .json archives.

        They were written by earlier versions and share ONE retention budget
        with the new .jsonl files — otherwise the old ones are never collected
        and the directory grows without bound.
        """
        handler._max_archives = 2
        handler._max_archive_age_days = 3650
        archive_dir.mkdir(parents=True, exist_ok=True)
        base = time.time() - 100.0
        for index in range(4):
            legacy = archive_dir / f"transcript_legacy{index}.json"
            legacy.write_text("{}")
            os.utime(legacy, (base + index, base + index))

        handler.handle({HookInputField.TRANSCRIPT_PATH: str(large_transcript)})

        remaining = {path.name for path in archive_dir.glob("transcript_*.json*")}
        assert len(remaining) == 2
        assert _ARCHIVE_NAME in remaining
        assert "transcript_legacy0.json" not in remaining

    def test_malformed_bytes_degrade_instead_of_raising(
        self, handler, archive_dir, tmp_path, mock_datetime
    ):
        """A transcript with invalid UTF-8 must not raise.

        ``read_text()`` used strict decoding, so a corrupt byte raised
        ``UnicodeDecodeError`` — which is a ``ValueError``, and the handler
        only ever caught ``OSError``. The exception escaped the handler.
        """
        transcript_path = tmp_path / "corrupt.jsonl"
        transcript_path.write_bytes(b'{"content": "ok"}\n{"content": "\xff\xfe bad"}\n')

        result = handler.handle({HookInputField.TRANSCRIPT_PATH: str(transcript_path)})

        assert result.decision == "allow"
        assert (archive_dir / _ARCHIVE_NAME).is_file()
