"""Tests for namespace-broad session-identity filtering (Plan 00166).

Two `ccy` terminals in the SAME repo share ONE `context-sidecar/` dir (a
bind-mounted `untracked/`), but each runs in its OWN container / PID namespace.
The supervisor must act ONLY on sidecars/signals belonging to its own Claude
instance. Decision 1 (option B): learn the own-session-id SET by scanning the
container's process environs for ``CLAUDE_CODE_SESSION_ID`` (a foreign terminal
never appears there), then filter the shared dir to that set. Fail safe: an
empty/unknown set means act on NOTHING.
"""

import json
import os
from pathlib import Path

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

_NOW = 1_000_000.0
_FRESH = 30.0
_TTL = _mod._DEFAULT_COMPACTION_SIGNAL_TTL_SECONDS

_MINE = "7ef60468-2b56-4b19-a1a2-3521c6939ab3"
_FOREIGN = "e7247afe-978f-4213-946f-52fbbd4c1b4d"


def _write_sidecar(path: Path, *, ts: float, session: str, red: bool = False) -> Path:
    path.write_text(
        json.dumps({"ts": ts, "red": red, "session_id": session, "tier": "green"}),
        encoding="utf-8",
    )
    os.utime(path, (ts, ts))
    return path


def _write_signal(path: Path, *, ts: float, session: str) -> Path:
    path.write_text(json.dumps({"ts": ts, "session_id": session}), encoding="utf-8")
    os.utime(path, (ts, ts))
    return path


def _fake_proc(root: Path, pid_to_env: dict[str, dict[str, str]]) -> Path:
    """Build a fake /proc: root/<pid>/environ with NUL-delimited KEY=VALUE."""
    for pid, env in pid_to_env.items():
        d = root / pid
        d.mkdir(parents=True, exist_ok=True)
        blob = b"".join(f"{k}={v}".encode() + b"\x00" for k, v in env.items())
        (d / "environ").write_bytes(blob)
    return root


# ── _session_ids_from_environ ────────────────────────────────────────────────


class TestSessionIdsFromEnviron:
    def test_extracts_the_session_id(self) -> None:
        blob = b"PATH=/usr/bin\x00CLAUDE_CODE_SESSION_ID=" + _MINE.encode() + b"\x00HOME=/root\x00"
        assert _mod._session_ids_from_environ(blob) == {_MINE}

    def test_absent_var_yields_empty(self) -> None:
        assert _mod._session_ids_from_environ(b"PATH=/usr/bin\x00HOME=/root\x00") == set()

    def test_empty_value_ignored(self) -> None:
        assert _mod._session_ids_from_environ(b"CLAUDE_CODE_SESSION_ID=\x00") == set()

    def test_empty_blob(self) -> None:
        assert _mod._session_ids_from_environ(b"") == set()

    def test_no_false_prefix_match(self) -> None:
        # A var that merely starts with the same letters must not match.
        assert _mod._session_ids_from_environ(b"CLAUDE_CODE_SESSION_ID_X=nope\x00") == set()


# ── resolve_own_session_ids (fake /proc) ─────────────────────────────────────


class TestResolveOwnSessionIds:
    def test_collects_ids_across_processes(self, tmp_path: Path) -> None:
        root = _fake_proc(
            tmp_path,
            {
                "1": {"PATH": "/usr/bin"},
                "76": {"CLAUDE_CODE_SESSION_ID": _MINE},
                "88": {"CLAUDE_CODE_SESSION_ID": _MINE},  # dup -> one entry
            },
        )
        assert _mod.resolve_own_session_ids(root) == frozenset({_MINE})

    def test_ignores_non_pid_dirs(self, tmp_path: Path) -> None:
        root = _fake_proc(tmp_path, {"76": {"CLAUDE_CODE_SESSION_ID": _MINE}})
        (root / "sys").mkdir()  # non-numeric dir must be skipped
        assert _mod.resolve_own_session_ids(root) == frozenset({_MINE})

    def test_missing_proc_root_is_empty(self, tmp_path: Path) -> None:
        assert _mod.resolve_own_session_ids(tmp_path / "nope") == frozenset()

    def test_multiple_distinct_sessions_in_one_namespace(self, tmp_path: Path) -> None:
        # Main + a subagent session, both local -> both are "mine".
        root = _fake_proc(
            tmp_path,
            {
                "76": {"CLAUDE_CODE_SESSION_ID": _MINE},
                "90": {"CLAUDE_CODE_SESSION_ID": _FOREIGN},  # here it's a LOCAL subagent
            },
        )
        assert _mod.resolve_own_session_ids(root) == frozenset({_MINE, _FOREIGN})


class TestCachedOwnSessionIds:
    def test_accumulates_across_calls(self, tmp_path: Path) -> None:
        _mod._own_session_ids_cache.clear()
        r1 = _fake_proc(tmp_path / "a", {"76": {"CLAUDE_CODE_SESSION_ID": _MINE}})
        assert _mod.cached_own_session_ids(r1) == frozenset({_MINE})
        # Next tick has NO process exposing the id (claude idle) -> stays learned.
        r2 = _fake_proc(tmp_path / "b", {"1": {"PATH": "/usr/bin"}})
        assert _mod.cached_own_session_ids(r2) == frozenset({_MINE})
        _mod._own_session_ids_cache.clear()


class TestCachedOwnSessionIdsThrottle:
    """Plan 00182 Phase 3: the full /proc environ scan is the worker-tick latency
    source that made a tick exceed the 2s read timeout and desync. Once our
    session ids are learned, re-scanning every tick is wasteful — throttle it to
    a TTL so most ticks return the accumulated set without touching /proc, while
    an empty cache always forces a scan (we still need to discover our sessions).
    """

    def test_rescan_throttled_once_sessions_known(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mod._own_session_ids_cache.clear()
        monkeypatch.setattr(_mod, "_own_session_ids_last_scan", None)
        calls = {"n": 0}

        def fake_resolve(_proc_root: object = None) -> frozenset[str]:
            calls["n"] += 1
            return frozenset({_MINE})

        monkeypatch.setattr(_mod, "resolve_own_session_ids", fake_resolve)
        # First call: cache empty -> must scan.
        assert _mod.cached_own_session_ids(now=0.0) == frozenset({_MINE})
        assert calls["n"] == 1
        # Within the TTL with a known set -> no re-scan.
        assert _mod.cached_own_session_ids(now=5.0) == frozenset({_MINE})
        assert calls["n"] == 1
        # Past the TTL -> re-scan (catch newly-spawned sessions).
        past = _mod._OWN_SESSION_SCAN_TTL_SECONDS + 1.0
        assert _mod.cached_own_session_ids(now=past) == frozenset({_MINE})
        assert calls["n"] == 2
        _mod._own_session_ids_cache.clear()

    def test_empty_cache_always_rescans_even_within_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mod._own_session_ids_cache.clear()
        monkeypatch.setattr(_mod, "_own_session_ids_last_scan", 100.0)
        calls = {"n": 0}

        def fake_resolve(_proc_root: object = None) -> frozenset[str]:
            calls["n"] += 1
            return frozenset()  # nothing discovered

        monkeypatch.setattr(_mod, "resolve_own_session_ids", fake_resolve)
        # last_scan is recent (now within TTL) but the cache is empty, so we MUST
        # still scan — a fail-safe throttle never starves discovery.
        assert _mod.cached_own_session_ids(now=101.0) == frozenset()
        assert calls["n"] == 1
        _mod._own_session_ids_cache.clear()


# ── filtering: load_compaction_signal ────────────────────────────────────────


class TestCompactionSignalFilter:
    def test_none_means_no_filter(self, tmp_path: Path) -> None:
        _write_signal(tmp_path / f"{_FOREIGN}.compacting", ts=_NOW - 1, session=_FOREIGN)
        got = _mod.load_compaction_signal(tmp_path, now=_NOW, ttl_seconds=_TTL)
        assert got is not None and got.name == f"{_FOREIGN}.compacting"

    def test_foreign_signal_is_ignored(self, tmp_path: Path) -> None:
        _write_signal(tmp_path / f"{_FOREIGN}.compacting", ts=_NOW - 1, session=_FOREIGN)
        got = _mod.load_compaction_signal(
            tmp_path, now=_NOW, ttl_seconds=_TTL, own_sessions=frozenset({_MINE})
        )
        assert got is None

    def test_own_signal_is_returned(self, tmp_path: Path) -> None:
        _write_signal(tmp_path / f"{_MINE}.compacting", ts=_NOW - 1, session=_MINE)
        got = _mod.load_compaction_signal(
            tmp_path, now=_NOW, ttl_seconds=_TTL, own_sessions=frozenset({_MINE})
        )
        assert got is not None and got.name == f"{_MINE}.compacting"

    def test_own_returned_even_when_foreign_also_present(self, tmp_path: Path) -> None:
        _write_signal(tmp_path / f"{_FOREIGN}.compacting", ts=_NOW - 1, session=_FOREIGN)
        _write_signal(tmp_path / f"{_MINE}.compacting", ts=_NOW - 1, session=_MINE)
        got = _mod.load_compaction_signal(
            tmp_path, now=_NOW, ttl_seconds=_TTL, own_sessions=frozenset({_MINE})
        )
        assert got is not None and got.name == f"{_MINE}.compacting"

    def test_empty_set_ignores_everything(self, tmp_path: Path) -> None:
        _write_signal(tmp_path / f"{_MINE}.compacting", ts=_NOW - 1, session=_MINE)
        got = _mod.load_compaction_signal(
            tmp_path, now=_NOW, ttl_seconds=_TTL, own_sessions=frozenset()
        )
        assert got is None


# ── filtering: sidecar scan / foreground ─────────────────────────────────────


class TestSidecarFilter:
    def test_foreground_ignores_foreign_sidecar(self, tmp_path: Path) -> None:
        # Foreign sidecar is FRESHEST; without a filter it would win.
        _write_sidecar(tmp_path / f"{_FOREIGN}.json", ts=_NOW - 1, session=_FOREIGN, red=True)
        _write_sidecar(tmp_path / f"{_MINE}.json", ts=_NOW - 5, session=_MINE, red=True)
        reading, _ = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH, own_sessions=frozenset({_MINE})
        )
        assert reading is not None and reading.session_id == _MINE

    def test_scan_filters_foreign(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path / f"{_FOREIGN}.json", ts=_NOW - 1, session=_FOREIGN)
        _write_sidecar(tmp_path / f"{_MINE}.json", ts=_NOW - 2, session=_MINE)
        scanned = _mod._scan_sidecars(tmp_path, own_sessions=frozenset({_MINE}))
        sessions = {d.get("session_id") for d, _ in scanned}
        assert sessions == {_MINE}

    def test_empty_set_yields_no_reading(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path / f"{_MINE}.json", ts=_NOW - 1, session=_MINE, red=True)
        reading, ambiguous = _mod.load_foreground_sidecar(
            tmp_path, now=_NOW, freshness_seconds=_FRESH, own_sessions=frozenset()
        )
        assert reading is None
        assert ambiguous is False


# ── decide_once integration ──────────────────────────────────────────────────


class TestDecideOnceIdentity:
    def test_noop_on_foreign_compaction(self, tmp_path: Path) -> None:
        """The reported bug: B compacts, A must NOT resume off B's signal."""
        _write_signal(tmp_path / f"{_FOREIGN}.compacting", ts=_NOW - 1, session=_FOREIGN)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        facts = _mod.TickFacts(
            now_wall=_NOW,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
        )
        outcome = _mod.decide_once(
            machine,
            sidecar_dir=tmp_path,
            facts=facts,
            dry_run=True,
            freshness_seconds=_FRESH,
            own_sessions=frozenset({_MINE}),
        )
        assert outcome.decision_value == _mod.Decision.NOOP.value

    def test_resumes_on_own_compaction(self, tmp_path: Path) -> None:
        _write_signal(tmp_path / f"{_MINE}.compacting", ts=_NOW - 1, session=_MINE)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        facts = _mod.TickFacts(
            now_wall=_NOW,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
        )
        outcome = _mod.decide_once(
            machine,
            sidecar_dir=tmp_path,
            facts=facts,
            dry_run=True,
            freshness_seconds=_FRESH,
            own_sessions=frozenset({_MINE}),
        )
        assert outcome.decision_value == _mod.Decision.WOULD_CONTINUE.value
