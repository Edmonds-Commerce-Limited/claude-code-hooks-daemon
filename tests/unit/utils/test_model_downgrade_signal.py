"""Tests for the per-session automatic-model-downgrade signal file.

One small JSON file per session, written by the `model_downgrade_recorder`
PostToolUse handler and read by two consumers that both used to GUESS whether a
model change was the machine's: the `downgrade_indicator` status line, and the
ccy supervisor's model auto-restore. This module owns the path and the field
names so the two cannot drift.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.model_downgrade_signal import (
    SIGNAL_SUBDIR,
    SIGNAL_SUFFIX,
    DowngradeSignal,
    read_downgrade_signal,
    signal_path,
    write_downgrade_signal,
)

_SESSION = "sess-abc-123"

_BASE = DowngradeSignal(
    session_id=_SESSION,
    original_model="claude-fable-5",
    fallback_model="claude-opus-4-8",
    original_family="fable",
    fallback_family="opus",
    category="cyber",
    scope="session",
    record_ts="2026-08-27T09:34:10.341Z",
)


def _signal(
    *,
    session_id: str = _BASE.session_id,
    original_family: str | None = _BASE.original_family,
    fallback_family: str | None = _BASE.fallback_family,
    record_ts: str = _BASE.record_ts,
    record_id: str = _BASE.record_id,
) -> DowngradeSignal:
    """``_BASE`` with the named fields replaced, each typed as the field it sets."""
    return dataclasses.replace(
        _BASE,
        session_id=session_id,
        original_family=original_family,
        fallback_family=fallback_family,
        record_ts=record_ts,
        record_id=record_id,
    )


class TestPathing:
    def test_the_signal_lives_beside_the_context_sidecar(self, tmp_path: Path) -> None:
        """The supervisor already watches this directory; no new transport."""
        path = signal_path(tmp_path, _SESSION)

        assert path.parent == tmp_path / SIGNAL_SUBDIR
        assert path.name == f"{_SESSION}{SIGNAL_SUFFIX}"

    def test_the_suffix_is_not_json(self) -> None:
        """A `.json` name would be picked up as a context sidecar by the supervisor."""
        assert not SIGNAL_SUFFIX.endswith(".json")

    @pytest.mark.parametrize(
        "session_id",
        ["../../escape", "a/b", "", "  "],
        ids=["traversal", "separator", "empty", "blank"],
    )
    def test_an_untrusted_session_id_cannot_steer_the_write(
        self, tmp_path: Path, session_id: str
    ) -> None:
        """The id arrives in a hook payload, so it is untrusted input."""
        path = signal_path(tmp_path, session_id)

        assert path.parent == tmp_path / SIGNAL_SUBDIR


class TestRoundTrip:
    def test_a_written_signal_reads_back_identically(self, tmp_path: Path) -> None:
        write_downgrade_signal(tmp_path, _signal(), now=1234.5)

        assert read_downgrade_signal(tmp_path, _SESSION) == _signal()

    def test_the_publish_time_is_recorded_but_is_not_part_of_identity(self, tmp_path: Path) -> None:
        """`ts` is when we wrote it; `record_ts` is when the platform saw it."""
        write_downgrade_signal(tmp_path, _signal(), now=1234.5)

        payload = json.loads(signal_path(tmp_path, _SESSION).read_text(encoding="utf-8"))

        assert payload["ts"] == 1234.5
        assert payload["record_ts"] == "2026-08-27T09:34:10.341Z"

    def test_no_signal_reads_as_none(self, tmp_path: Path) -> None:
        assert read_downgrade_signal(tmp_path, _SESSION) is None

    def test_another_session_signal_is_not_returned(self, tmp_path: Path) -> None:
        write_downgrade_signal(tmp_path, _signal(session_id="somebody-else"), now=1.0)

        assert read_downgrade_signal(tmp_path, _SESSION) is None

    def test_a_payload_naming_a_different_session_is_rejected(self, tmp_path: Path) -> None:
        """The path is not the only claim of ownership; the payload names it too."""
        path = signal_path(tmp_path, _SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_signal(session_id="somebody-else").to_payload(now=1.0)),
            encoding="utf-8",
        )

        assert read_downgrade_signal(tmp_path, _SESSION) is None

    @pytest.mark.parametrize(
        "text",
        ["{not json", "[1,2,3]", "null", ""],
        ids=["malformed", "array", "null", "empty"],
    )
    def test_a_corrupt_signal_reads_as_none_rather_than_raising(
        self, tmp_path: Path, text: str
    ) -> None:
        """Both consumers are on hot paths — a render and a supervisor tick."""
        path = signal_path(tmp_path, _SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

        assert read_downgrade_signal(tmp_path, _SESSION) is None


class TestRewriteDiscipline:
    def test_rewriting_the_same_record_is_skipped(self, tmp_path: Path) -> None:
        """PostToolUse fires constantly; churn would destroy the file's mtime."""
        write_downgrade_signal(tmp_path, _signal(), now=1.0)
        before = signal_path(tmp_path, _SESSION).stat().st_mtime_ns

        written = write_downgrade_signal(tmp_path, _signal(), now=2.0)

        assert written is None
        assert signal_path(tmp_path, _SESSION).stat().st_mtime_ns == before

    def test_a_different_record_does_replace_it(self, tmp_path: Path) -> None:
        write_downgrade_signal(tmp_path, _signal(), now=1.0)

        written = write_downgrade_signal(
            tmp_path, _signal(record_ts="2026-08-27T11:00:00.000Z"), now=2.0
        )

        assert written is not None
        assert read_downgrade_signal(tmp_path, _SESSION) == _signal(
            record_ts="2026-08-27T11:00:00.000Z"
        )

    def test_a_different_record_id_is_a_different_record(self, tmp_path: Path) -> None:
        """Two downgrades can share every other field, including a missing time."""
        write_downgrade_signal(tmp_path, _signal(record_ts="", record_id="offset:10"), now=1.0)

        written = write_downgrade_signal(
            tmp_path, _signal(record_ts="", record_id="offset:900"), now=2.0
        )

        assert written is not None
        found = read_downgrade_signal(tmp_path, _SESSION)
        assert found is not None
        assert found.record_id == "offset:900"


class TestRecordIdentity:
    """Plan 00466 N47 review 4 item 4: the record's identity is published."""

    def test_the_record_id_is_written_and_read_back(self, tmp_path: Path) -> None:
        write_downgrade_signal(tmp_path, _signal(record_id="uuid-1"), now=1.0)

        payload = json.loads(signal_path(tmp_path, _SESSION).read_text(encoding="utf-8"))

        assert payload["record_id"] == "uuid-1"
        assert read_downgrade_signal(tmp_path, _SESSION) == _signal(record_id="uuid-1")

    def test_a_signal_from_before_record_ids_reads_back_with_an_empty_one(
        self, tmp_path: Path
    ) -> None:
        """An older daemon's file has no `record_id`; that is not a corrupt file."""
        path = signal_path(tmp_path, _SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _signal(record_id="uuid-1").to_payload(now=1.0)
        del payload["record_id"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        found = read_downgrade_signal(tmp_path, _SESSION)

        assert found is not None
        assert found.record_id == ""


class TestAttribution:
    def test_a_signal_naming_this_family_attributes_the_drop(self, tmp_path: Path) -> None:
        write_downgrade_signal(tmp_path, _signal(), now=1.0)

        found = read_downgrade_signal(tmp_path, _SESSION)

        assert found is not None
        assert found.attributes(from_family="fable", to_family="opus") is True

    def test_a_signal_for_a_different_pair_does_not_attribute_this_drop(
        self, tmp_path: Path
    ) -> None:
        write_downgrade_signal(
            tmp_path, _signal(original_family="opus", fallback_family="sonnet"), now=1.0
        )

        found = read_downgrade_signal(tmp_path, _SESSION)

        assert found is not None
        assert found.attributes(from_family="fable", to_family="opus") is False

    def test_an_unresolved_family_attributes_nothing(self, tmp_path: Path) -> None:
        """A null family means the recorder could not name the model."""
        write_downgrade_signal(tmp_path, _signal(original_family=None), now=1.0)

        found = read_downgrade_signal(tmp_path, _SESSION)

        assert found is not None
        assert found.attributes(from_family="fable", to_family="opus") is False
