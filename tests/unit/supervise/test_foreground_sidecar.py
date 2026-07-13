"""Tests for the guarded foreground-sidecar resolver (Plan 00160 Phase 2).

The supervisor drives ONE PTY; whatever it injects lands on the FOREGROUND
Agent-View thread. Only the foreground thread renders its ``statusLine`` (verified
against 205 real Status payloads), so the freshest sidecar is normally the
foreground -- EXCEPT in the brief window right after a thread switch, when the
just-backgrounded thread's sidecar is still fresh and could momentarily be the
freshest. ``load_foreground_sidecar`` returns the freshest reading PLUS an
``ambiguous`` flag that is True when a second, still-fresh sidecar's ts is within
a margin of the freshest -- the caller then defers the compaction rather than
risk compacting the wrong thread. Ambiguity self-resolves: the backgrounded
thread stops rendering and ages to stale within one freshness window.
"""

import json
import os
from pathlib import Path

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

_NOW = 1_000_000.0
_FRESH = 30.0
_MARGIN = _mod._DEFAULT_FOREGROUND_MARGIN_SECONDS


def _write(path: Path, *, ts: float, red: bool = False, session: str | None = None) -> Path:
    payload = {
        "ts": ts,
        "red": red,
        "session_id": session or path.stem,
        "tier": "red" if red else "green",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, (ts, ts))
    return path


class TestLoadForegroundSidecar:
    def test_single_fresh_sidecar_is_unambiguous(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.json", ts=_NOW - 3, red=True, session="a")

        reading, ambiguous = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH
        )

        assert reading is not None
        assert reading.session_id == "a"
        assert reading.red is True
        assert ambiguous is False

    def test_no_sidecars_returns_none_not_ambiguous(self, tmp_path: Path) -> None:
        reading, ambiguous = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH
        )
        assert reading is None
        assert ambiguous is False

    def test_stale_runner_up_is_not_ambiguous(self, tmp_path: Path) -> None:
        """A backgrounded thread that has aged to stale no longer causes ambiguity."""
        _write(tmp_path / "fg.json", ts=_NOW - 2, red=True, session="fg")
        _write(tmp_path / "bg.json", ts=_NOW - (_FRESH + 50), session="bg")  # stale

        reading, ambiguous = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH
        )

        assert reading is not None and reading.session_id == "fg"
        assert ambiguous is False

    def test_two_fresh_far_apart_is_unambiguous(self, tmp_path: Path) -> None:
        """Freshest clearly leads the runner-up by more than the margin."""
        _write(tmp_path / "fg.json", ts=_NOW - 1, red=True, session="fg")
        _write(tmp_path / "other.json", ts=_NOW - (_MARGIN + 5), session="other")

        reading, ambiguous = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH
        )

        assert reading is not None and reading.session_id == "fg"
        assert ambiguous is False

    def test_two_fresh_within_margin_is_ambiguous(self, tmp_path: Path) -> None:
        """Switch window: two fresh sidecars within the margin -> ambiguous."""
        _write(tmp_path / "newfg.json", ts=_NOW - 1, red=True, session="newfg")
        _write(tmp_path / "oldfg.json", ts=_NOW - 2, red=True, session="oldfg")

        reading, ambiguous = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH
        )

        assert reading is not None and reading.session_id == "newfg"  # still the freshest
        assert ambiguous is True

    def test_freshest_stale_is_never_ambiguous(self, tmp_path: Path) -> None:
        """All sidecars stale: a reading is returned (stale) but not ambiguous."""
        _write(tmp_path / "a.json", ts=_NOW - (_FRESH + 5), session="a")
        _write(tmp_path / "b.json", ts=_NOW - (_FRESH + 6), session="b")

        reading, ambiguous = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH
        )

        assert reading is not None and reading.stale is True
        assert ambiguous is False

    def test_margin_is_configurable(self, tmp_path: Path) -> None:
        _write(tmp_path / "fg.json", ts=_NOW - 1, session="fg")
        _write(tmp_path / "other.json", ts=_NOW - 4, session="other")

        # gap = 3s: ambiguous under a 5s margin, unambiguous under a 2s margin.
        _, amb_wide = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH, margin_seconds=5.0
        )
        _, amb_tight = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH, margin_seconds=2.0
        )

        assert amb_wide is True
        assert amb_tight is False

    def test_freshest_matches_load_freshest_sidecar(self, tmp_path: Path) -> None:
        """The reading is identical to what load_freshest_sidecar returns."""
        _write(tmp_path / "a.json", ts=_NOW - 3, red=True, session="a")
        _write(tmp_path / "b.json", ts=_NOW - 9, session="b")

        reading, _ = _mod.load_foreground_sidecar(tmp_path, now=_NOW, freshness_seconds=_FRESH)
        freshest = _mod.load_freshest_sidecar(tmp_path, now=_NOW, freshness_seconds=_FRESH)

        assert reading == freshest

    def test_default_margin_constant_sane(self) -> None:
        """Margin is positive and below the freshness window."""
        assert 0 < _mod._DEFAULT_FOREGROUND_MARGIN_SECONDS < _mod._DEFAULT_FRESHNESS_SECONDS
