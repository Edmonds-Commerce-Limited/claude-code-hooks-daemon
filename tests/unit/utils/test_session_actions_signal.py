"""Plan 00416 Task 2.3 — the session-actions directive signal (daemon half).

The plan's layer 2: *the supervisor sends one turn-level directive after
session start*. The reason that works is CHANNEL, not volume — the owner
proved it on another machine with a single typed line, after which the agent
acted on the whole start-up block unprompted. SessionStart context is scenery;
a user-role turn is a turn.

This is the SENSOR half — one small JSON file per session dropped into the
same context-sidecar directory the supervisor already watches, mirroring
`operator_signal` and `model_downgrade_signal`.

**The payload carries no text, and that is the whole design.** It is a
positive integer COUNT and nothing else. Every word the agent ever reads is
composed by the supervisor's own fixed template, so this channel cannot be
made to type prose of a writer's choosing — not by a forged file, not by a
future widening of this module. `operator_signal` earned that shape because
it is reachable from outside the container; this one adopts it because there
was never a reason to carry text in the first place, and a channel that
cannot carry text cannot be abused into carrying it later.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.session_actions_signal import (
    FIELD_COUNT,
    FIELD_SESSION_ID,
    FIELD_TS,
    SIGNAL_SUBDIR,
    SIGNAL_SUFFIX,
    clear_session_actions_signal,
    signal_path,
    write_session_actions_signal,
)

_NOW = 1_700_000_000.0
_SESSION = "sess-abc-1"


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class TestThePathIsTheSharedSidecarDirectory:
    def test_it_lands_beside_the_context_sidecar(self, tmp_path: Path) -> None:
        path = signal_path(tmp_path, _SESSION)
        assert path.parent == tmp_path / SIGNAL_SUBDIR
        assert path.name == f"{_SESSION}{SIGNAL_SUFFIX}"

    def test_the_suffix_is_not_json(self) -> None:
        # The supervisor's sidecar reader globs `*.json`; a signal wearing
        # that extension would be read as a context sidecar.
        assert not SIGNAL_SUFFIX.endswith(".json")

    def test_an_untrusted_session_id_cannot_steer_the_write(self, tmp_path: Path) -> None:
        path = signal_path(tmp_path, "../../etc/passwd")
        assert path.parent == tmp_path / SIGNAL_SUBDIR
        assert "/" not in path.name.removesuffix(SIGNAL_SUFFIX)

    def test_an_empty_session_id_still_yields_a_file(self, tmp_path: Path) -> None:
        path = signal_path(tmp_path, "   ")
        assert path.name.endswith(SIGNAL_SUFFIX)
        assert path.name != SIGNAL_SUFFIX


class TestWritingASignal:
    def test_it_records_the_count_and_the_session(self, tmp_path: Path) -> None:
        path = write_session_actions_signal(tmp_path, session_id=_SESSION, count=2, now=_NOW)
        payload = _read(path)
        assert payload[FIELD_COUNT] == 2
        assert payload[FIELD_SESSION_ID] == _SESSION
        assert payload[FIELD_TS] == _NOW

    def test_it_creates_the_directory(self, tmp_path: Path) -> None:
        assert not (tmp_path / SIGNAL_SUBDIR).exists()
        write_session_actions_signal(tmp_path, session_id=_SESSION, count=1, now=_NOW)
        assert (tmp_path / SIGNAL_SUBDIR).is_dir()

    def test_it_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        write_session_actions_signal(tmp_path, session_id=_SESSION, count=1, now=_NOW)
        names = sorted(p.name for p in (tmp_path / SIGNAL_SUBDIR).iterdir())
        assert names == [f"{_SESSION}{SIGNAL_SUFFIX}"]

    def test_rewriting_replaces_rather_than_appends(self, tmp_path: Path) -> None:
        write_session_actions_signal(tmp_path, session_id=_SESSION, count=1, now=_NOW)
        path = write_session_actions_signal(tmp_path, session_id=_SESSION, count=5, now=_NOW + 1)
        assert _read(path)[FIELD_COUNT] == 5


class TestTheCountIsTheOnlyPayloadAndItIsValidated:
    """A shape check at the point of writing, so a caller fails fast.

    The supervisor re-validates independently against the untyped bytes on
    disk — this is not that check, and neither replaces the other.
    """

    def test_zero_is_refused(self, tmp_path: Path) -> None:
        # Nothing to action is not a directive worth typing; the caller is
        # expected to CLEAR instead, so a zero here is a caller bug.
        with pytest.raises(ValueError):
            write_session_actions_signal(tmp_path, session_id=_SESSION, count=0, now=_NOW)

    def test_a_negative_count_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            write_session_actions_signal(tmp_path, session_id=_SESSION, count=-1, now=_NOW)

    def test_a_bool_is_refused_despite_being_an_int(self, tmp_path: Path) -> None:
        # `bool` is an `int` subclass in Python: True would silently become a
        # one-item directive.
        truthy: Any = True
        with pytest.raises(ValueError):
            write_session_actions_signal(tmp_path, session_id=_SESSION, count=truthy, now=_NOW)

    def test_a_float_is_refused(self, tmp_path: Path) -> None:
        fractional: Any = 1.5
        with pytest.raises(ValueError):
            write_session_actions_signal(tmp_path, session_id=_SESSION, count=fractional, now=_NOW)

    def test_the_payload_carries_no_free_text_field(self, tmp_path: Path) -> None:
        """The property the whole module exists to hold.

        Every value on disk is a number or the session id the daemon already
        knows — nothing a reader could render as a sentence.
        """
        path = write_session_actions_signal(tmp_path, session_id=_SESSION, count=3, now=_NOW)
        payload = _read(path)
        assert set(payload) == {FIELD_TS, FIELD_SESSION_ID, FIELD_COUNT}


class TestClearing:
    def test_it_removes_a_pending_signal(self, tmp_path: Path) -> None:
        path = write_session_actions_signal(tmp_path, session_id=_SESSION, count=1, now=_NOW)
        clear_session_actions_signal(tmp_path, session_id=_SESSION)
        assert not path.exists()

    def test_clearing_nothing_is_not_an_error(self, tmp_path: Path) -> None:
        # A healthy session clears on every start; the file is usually absent.
        clear_session_actions_signal(tmp_path, session_id=_SESSION)

    def test_it_leaves_another_sessions_signal_alone(self, tmp_path: Path) -> None:
        other = write_session_actions_signal(tmp_path, session_id="sess-other", count=1, now=_NOW)
        clear_session_actions_signal(tmp_path, session_id=_SESSION)
        assert other.exists()
