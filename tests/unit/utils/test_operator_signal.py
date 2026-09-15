"""Tests for the operator-signal writer (Plan 00417).

A channel from OUTSIDE the container into a running agent's context is a
prompt-injection surface by default, so this one is built closed: a fixed set
of `kind`s and, for the two that need one, a bare positive-integer `minutes` —
never free text, never a reason field. This module is the WRITER half (the
CLI's sensor); the supervisor's `load_operator_signal`/`_render_operator_message`
in `.claude/ccy/claude-supervise.py` is the READER/RENDERER half that actually
composes what the agent sees. The two are pinned to each other on the `kind`
strings by `tests/unit/supervise/test_operator_signal.py`, which also covers
the untyped-JSON shape rejections (non-integer, string, negative `minutes`)
that only make sense on the reader side of an on-disk file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.operator_signal import (
    FIELD_KIND,
    FIELD_MINUTES,
    FIELD_SESSION_ID,
    FIELD_SOURCE,
    FIELD_TS,
    KIND_REBOOT_CANCELLED,
    KIND_REBOOT_WARNING,
    KIND_SHUTDOWN_WARNING,
    KINDS,
    KINDS_WITH_MINUTES,
    SIGNAL_SUBDIR,
    SIGNAL_SUFFIX,
    discover_session_ids,
    signal_path,
    write_operator_signal,
)

_SESSION = "op-session-1"


class TestPathing:
    def test_the_signal_lives_beside_the_context_sidecar(self, tmp_path: Path) -> None:
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
        path = signal_path(tmp_path, session_id)

        assert path.parent == tmp_path / SIGNAL_SUBDIR


class TestClosedKindSet:
    """The rejection cases ARE the security properties -- RED first."""

    def test_unknown_kind_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown operator signal kind"):
            write_operator_signal(
                tmp_path, session_id=_SESSION, kind="not-a-kind", minutes=5, now=1.0
            )

    def test_bool_minutes_is_rejected(self, tmp_path: Path) -> None:
        """`bool` is an `int` subclass -- must not silently coerce True -> 1.

        A `bool` passes Python's own `int | None` type check (it IS an
        `int`), so this is a genuine runtime gap static types cannot catch --
        unlike a string or a float, which mypy would already refuse at the
        call site and so are covered on the READ side instead
        (`tests/unit/supervise/test_operator_signal.py`), where the value
        arrives from untyped JSON and the type check is the whole point.
        """
        with pytest.raises(ValueError, match="positive integer"):
            write_operator_signal(
                tmp_path, session_id=_SESSION, kind=KIND_REBOOT_WARNING, minutes=True, now=1.0
            )

    def test_zero_minutes_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            write_operator_signal(
                tmp_path, session_id=_SESSION, kind=KIND_REBOOT_WARNING, minutes=0, now=1.0
            )

    def test_negative_minutes_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            write_operator_signal(
                tmp_path, session_id=_SESSION, kind=KIND_SHUTDOWN_WARNING, minutes=-1, now=1.0
            )

    def test_missing_minutes_on_a_kind_that_needs_one_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            write_operator_signal(
                tmp_path, session_id=_SESSION, kind=KIND_REBOOT_WARNING, minutes=None, now=1.0
            )

    def test_minutes_on_a_kind_that_takes_none_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="takes no minutes"):
            write_operator_signal(
                tmp_path, session_id=_SESSION, kind=KIND_REBOOT_CANCELLED, minutes=5, now=1.0
            )

    def test_kinds_with_minutes_is_a_strict_subset_of_kinds(self) -> None:
        assert KINDS_WITH_MINUTES < KINDS
        assert KIND_REBOOT_CANCELLED not in KINDS_WITH_MINUTES


class TestRoundTrip:
    def test_writes_a_valid_reboot_warning_signal(self, tmp_path: Path) -> None:
        path = write_operator_signal(
            tmp_path, session_id=_SESSION, kind=KIND_REBOOT_WARNING, minutes=10, now=1234.5
        )

        assert path == signal_path(tmp_path, _SESSION)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload[FIELD_SESSION_ID] == _SESSION
        assert payload[FIELD_KIND] == KIND_REBOOT_WARNING
        assert payload[FIELD_MINUTES] == 10
        assert payload[FIELD_TS] == 1234.5
        assert payload[FIELD_SOURCE] == "cli"

    def test_writes_a_valid_cancelled_signal_with_no_minutes_key(self, tmp_path: Path) -> None:
        path = write_operator_signal(
            tmp_path, session_id=_SESSION, kind=KIND_REBOOT_CANCELLED, minutes=None, now=1.0
        )

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload[FIELD_KIND] == KIND_REBOOT_CANCELLED
        assert FIELD_MINUTES not in payload

    def test_a_later_write_overwrites_the_earlier_one(self, tmp_path: Path) -> None:
        write_operator_signal(
            tmp_path, session_id=_SESSION, kind=KIND_REBOOT_WARNING, minutes=10, now=1.0
        )
        write_operator_signal(
            tmp_path, session_id=_SESSION, kind=KIND_REBOOT_CANCELLED, minutes=None, now=2.0
        )

        payload = json.loads(signal_path(tmp_path, _SESSION).read_text(encoding="utf-8"))
        assert payload[FIELD_KIND] == KIND_REBOOT_CANCELLED


class TestDiscoverSessionIds:
    def test_missing_directory_yields_no_ids(self, tmp_path: Path) -> None:
        assert discover_session_ids(tmp_path) == []

    def test_finds_every_live_context_sidecar(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / SIGNAL_SUBDIR
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")
        (sidecar_dir / "sess-b.json").write_text("{}", encoding="utf-8")

        assert discover_session_ids(tmp_path) == ["sess-a", "sess-b"]

    def test_ignores_non_json_signal_files(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / SIGNAL_SUBDIR
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")
        (sidecar_dir / "sess-a.goal-intent").write_text("{}", encoding="utf-8")
        (sidecar_dir / "sess-a.compacting").write_text("{}", encoding="utf-8")

        assert discover_session_ids(tmp_path) == ["sess-a"]

    def test_ignores_dotfile_temp_writes(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / SIGNAL_SUBDIR
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")
        (sidecar_dir / ".sess-a.json.123.456.tmp").write_text("{}", encoding="utf-8")

        assert discover_session_ids(tmp_path) == ["sess-a"]
