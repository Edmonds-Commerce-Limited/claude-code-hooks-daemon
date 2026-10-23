"""Tests for own-session identity filtering (Plans 00166 and 00551).

Two `ccy` terminals in the SAME repo share ONE `context-sidecar/` dir (a
bind-mounted `untracked/`). The supervisor must act ONLY on sidecars/signals
belonging to its own Claude instance. The own-session-id SET is learned from the
environs of the supervisor's OWN child process tree (the pid it forked and that
pid's descendants by ppid), never from every process `/proc` shows -- on a host
or a shared PID namespace `/proc` also shows other users' and other terminals'
sessions (issue #138). Fail safe: an empty/unknown set means act on NOTHING.
"""

import io
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
_SUBAGENT = "0b6c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"

_CHILD = 100


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


_Proc = tuple[int, dict[str, str], str]


def _p(ppid: int, session: str | None = None, comm: str = "proc") -> _Proc:
    """One fake process: its ppid, its environ (optionally a session id), its comm."""
    env = {"PATH": "/usr/bin"}
    if session is not None:
        env["CLAUDE_CODE_SESSION_ID"] = session
    return (ppid, env, comm)


def _fake_proc(root: Path, processes: dict[int, _Proc]) -> Path:
    """Build a fake /proc: root/<pid>/stat (the kernel's layout) and root/<pid>/environ."""
    for pid, (ppid, env, comm) in processes.items():
        d = root / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 4194560 0\n")
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


# ── _proc_stat_ppid ──────────────────────────────────────────────────────────


class TestProcStatPpid:
    def test_plain_comm(self) -> None:
        assert _mod._proc_stat_ppid("100 (claude) S 42 100 100 0 -1") == 42

    def test_comm_with_spaces_and_parentheses(self) -> None:
        # comm is attacker-chosen (prctl/exec name): it may hold ") S 1 " to
        # forge a ppid if the line is split naively.
        assert _mod._proc_stat_ppid("100 (a) S 1 (b c)) R 42 100 100 0") == 42

    def test_malformed_is_none(self) -> None:
        assert _mod._proc_stat_ppid("") is None
        assert _mod._proc_stat_ppid("100 no-parens S 42") is None
        assert _mod._proc_stat_ppid("100 (x) S") is None
        assert _mod._proc_stat_ppid("100 (x) S notanumber") is None


# ── resolve_own_session_ids (fake /proc) ─────────────────────────────────────


class TestResolveOwnSessionIds:
    def test_issue_138_reproduction_returns_only_the_child_tree(self, tmp_path: Path) -> None:
        """Two environs visible in /proc: the supervisor's child and an unrelated session.

        On a host (or a shared PID namespace) the unrelated session is another
        terminal's Claude Code; only the child's id is this supervisor's own.
        """
        root = _fake_proc(
            tmp_path,
            {
                1: _p(0, comm="init"),
                _CHILD: _p(50, _MINE, comm="claude"),
                200: _p(1, _FOREIGN, comm="claude"),
            },
        )
        assert _mod.resolve_own_session_ids(_CHILD, root) == frozenset({_MINE})

    def test_grandchild_id_is_own(self, tmp_path: Path) -> None:
        root = _fake_proc(
            tmp_path,
            {
                _CHILD: _p(50, comm="claude"),  # the child itself exposes no id
                101: _p(_CHILD, comm="bash"),
                102: _p(101, _MINE, comm="hook"),
                103: _p(_CHILD, _SUBAGENT, comm="node"),
            },
        )
        assert _mod.resolve_own_session_ids(_CHILD, root) == frozenset({_MINE, _SUBAGENT})

    def test_reparented_process_is_not_own(self, tmp_path: Path) -> None:
        # Its parent left the tree (it was re-parented to init), so it is no
        # longer a descendant -- whatever id it carries is not ours.
        root = _fake_proc(
            tmp_path,
            {
                _CHILD: _p(50, _MINE, comm="claude"),
                300: _p(1, _FOREIGN, comm="daemonised"),
            },
        )
        assert _mod.resolve_own_session_ids(_CHILD, root) == frozenset({_MINE})

    def test_hostile_comm_cannot_forge_a_parent(self, tmp_path: Path) -> None:
        # comm ") S 100 " would read as ppid 100 if the line were split on spaces.
        root = _fake_proc(
            tmp_path,
            {
                _CHILD: _p(50, _MINE, comm="claude"),
                400: _p(1, _FOREIGN, comm=f"x) S {_CHILD} "),
            },
        )
        assert _mod.resolve_own_session_ids(_CHILD, root) == frozenset({_MINE})

    def test_child_gone_fails_safe(self, tmp_path: Path) -> None:
        root = _fake_proc(tmp_path, {200: _p(1, _FOREIGN)})
        assert _mod.resolve_own_session_ids(_CHILD, root) == frozenset()

    def test_ignores_non_pid_dirs(self, tmp_path: Path) -> None:
        root = _fake_proc(tmp_path, {_CHILD: _p(50, _MINE)})
        (root / "sys").mkdir()  # non-numeric dir must be skipped
        assert _mod.resolve_own_session_ids(_CHILD, root) == frozenset({_MINE})

    def test_unreadable_stat_contributes_nothing(self, tmp_path: Path) -> None:
        root = _fake_proc(tmp_path, {_CHILD: _p(50, _MINE)})
        (root / "500").mkdir()  # vanished between listdir and read: no stat
        assert _mod.resolve_own_session_ids(_CHILD, root) == frozenset({_MINE})

    def test_missing_proc_root_is_empty(self, tmp_path: Path) -> None:
        assert _mod.resolve_own_session_ids(_CHILD, tmp_path / "nope") == frozenset()


@pytest.fixture
def _clean_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_mod, "_own_session_ids_cache", set())
    monkeypatch.setattr(_mod, "_own_session_ids_last_scan", None)
    monkeypatch.setattr(_mod, "_own_session_ids_child_pid", None)


@pytest.mark.usefixtures("_clean_cache")
class TestCachedOwnSessionIds:
    def test_accumulates_across_calls(self, tmp_path: Path) -> None:
        r1 = _fake_proc(tmp_path / "a", {_CHILD: _p(50, _MINE)})
        assert _mod.cached_own_session_ids(_CHILD, r1) == frozenset({_MINE})
        # Next scan has NO process exposing the id (claude idle) -> stays learned.
        r2 = _fake_proc(tmp_path / "b", {_CHILD: _p(50)})
        past = _mod._OWN_SESSION_SCAN_TTL_SECONDS + 1.0
        assert _mod.cached_own_session_ids(_CHILD, r2, now=past) == frozenset({_MINE})

    def test_unknown_child_fails_safe_without_scanning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_resolve(*_args: object, **_kwargs: object) -> frozenset[str]:
            raise AssertionError("no child pid must never scan /proc")

        monkeypatch.setattr(_mod, "resolve_own_session_ids", fail_resolve)
        assert _mod.cached_own_session_ids(None) == frozenset()

    def test_unknown_child_does_not_expose_a_learned_set(self, tmp_path: Path) -> None:
        root = _fake_proc(tmp_path, {_CHILD: _p(50, _MINE)})
        assert _mod.cached_own_session_ids(_CHILD, root) == frozenset({_MINE})
        assert _mod.cached_own_session_ids(None, root) == frozenset()

    def test_a_different_child_starts_a_fresh_set(self, tmp_path: Path) -> None:
        # The union cache never carries an id across trees: what was learned
        # under one child is not admitted for another.
        root = _fake_proc(tmp_path, {_CHILD: _p(50, _MINE), 600: _p(50, _FOREIGN)})
        assert _mod.cached_own_session_ids(_CHILD, root, now=0.0) == frozenset({_MINE})
        assert _mod.cached_own_session_ids(600, root, now=1.0) == frozenset({_FOREIGN})

    def test_the_cache_never_admits_an_id_from_outside_the_tree(self, tmp_path: Path) -> None:
        root = _fake_proc(tmp_path / "a", {_CHILD: _p(50, _MINE), 200: _p(1, _FOREIGN)})
        assert _mod.cached_own_session_ids(_CHILD, root, now=0.0) == frozenset({_MINE})
        later = _fake_proc(tmp_path / "b", {_CHILD: _p(50), 200: _p(1, _FOREIGN)})
        past = _mod._OWN_SESSION_SCAN_TTL_SECONDS + 1.0
        assert _mod.cached_own_session_ids(_CHILD, later, now=past) == frozenset({_MINE})


@pytest.mark.usefixtures("_clean_cache")
class TestCachedOwnSessionIdsThrottle:
    """Plan 00182 Phase 3: the full /proc scan is the worker-tick latency
    source that made a tick exceed the 2s read timeout and desync. Once our
    session ids are learned, re-scanning every tick is wasteful — throttle it to
    a TTL so most ticks return the accumulated set without touching /proc, while
    an empty cache always forces a scan (we still need to discover our sessions).
    """

    def test_rescan_throttled_once_sessions_known(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []

        def fake_resolve(child_pid: int, _proc_root: object = None) -> frozenset[str]:
            calls.append(child_pid)
            return frozenset({_MINE})

        monkeypatch.setattr(_mod, "resolve_own_session_ids", fake_resolve)
        # First call: cache empty -> must scan.
        assert _mod.cached_own_session_ids(_CHILD, now=0.0) == frozenset({_MINE})
        assert calls == [_CHILD]
        # Within the TTL with a known set -> no re-scan.
        assert _mod.cached_own_session_ids(_CHILD, now=5.0) == frozenset({_MINE})
        assert calls == [_CHILD]
        # Past the TTL -> re-scan (catch newly-spawned sessions).
        past = _mod._OWN_SESSION_SCAN_TTL_SECONDS + 1.0
        assert _mod.cached_own_session_ids(_CHILD, now=past) == frozenset({_MINE})
        assert calls == [_CHILD, _CHILD]

    def test_empty_cache_always_rescans_even_within_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_own_session_ids_child_pid", _CHILD)
        monkeypatch.setattr(_mod, "_own_session_ids_last_scan", 100.0)
        calls = {"n": 0}

        def fake_resolve(_child_pid: int, _proc_root: object = None) -> frozenset[str]:
            calls["n"] += 1
            return frozenset()  # nothing discovered

        monkeypatch.setattr(_mod, "resolve_own_session_ids", fake_resolve)
        # last_scan is recent (now within TTL) but the cache is empty, so we MUST
        # still scan — a fail-safe throttle never starves discovery.
        assert _mod.cached_own_session_ids(_CHILD, now=101.0) == frozenset()
        assert calls["n"] == 1


# ── WorkerChildPid: how the child pid reaches the --worker subprocess ────────


class TestWorkerChildPid:
    def test_the_host_sent_pid_is_used(self, tmp_path: Path) -> None:
        child = _mod.WorkerChildPid(proc_root=tmp_path, host_pid=lambda: 50, own_pid=lambda: 51)
        assert child.learn(_CHILD) == _CHILD
        assert child.pid == _CHILD

    def test_unknown_before_any_tick(self, tmp_path: Path) -> None:
        child = _mod.WorkerChildPid(proc_root=tmp_path, host_pid=lambda: 50, own_pid=lambda: 51)
        assert child.pid is None

    def test_reparented_worker_never_adopts_init_children(self, tmp_path: Path) -> None:
        # The host died and the worker was re-parented to init: init's
        # descendants are the whole namespace, never this supervisor's tree.
        root = _fake_proc(tmp_path, {1: _p(0), 51: _p(1), 200: _p(1, _FOREIGN)})
        child = _mod.WorkerChildPid(proc_root=root, host_pid=lambda: 1, own_pid=lambda: 51)
        assert child.learn(None) is None
        assert child.own_session_ids() == frozenset()

    def test_a_learned_pid_is_kept_when_a_later_tick_sends_none(self, tmp_path: Path) -> None:
        child = _mod.WorkerChildPid(proc_root=tmp_path, host_pid=lambda: 50, own_pid=lambda: 51)
        child.learn(_CHILD)
        assert child.learn(None) == _CHILD

    def test_own_session_ids_reads_the_learned_tree(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen: list[object] = []
        monkeypatch.setattr(
            _mod,
            "cached_own_session_ids",
            lambda child_pid, *a, **k: seen.append(child_pid) or frozenset({_MINE}),
        )
        child = _mod.WorkerChildPid(proc_root=tmp_path, host_pid=lambda: 50, own_pid=lambda: 51)
        child.learn(_CHILD)
        assert child.own_session_ids() == frozenset({_MINE})
        assert seen == [_CHILD]


# ── hot-reload fallback: a host that sends no child pid ──────────────────────

_HOST = 2
_PINGBUS = 70
_CLAUDE = 78
_TOOL_SHELL = 900
_WORKER = 114781
_WORKER_CHILD = 114790


def _live_shape(root: Path) -> Path:
    """The live tree of the 00551 regression: the host has TWO other children.

    tini (1) -> host (2) -> {pingbus (70, no id), claude (78, no id), worker}.
    Claude's tool shell carries the session id; a foreign claude sits under
    tini, and the worker's own subtree carries an id that must not be taken.
    """
    return _fake_proc(
        root,
        {
            1: _p(0, comm="tini"),
            _HOST: _p(1, comm="python3"),
            _PINGBUS: _p(_HOST, comm="python3"),
            _CLAUDE: _p(_HOST, comm="claude"),
            _TOOL_SHELL: _p(_CLAUDE, _MINE, comm="bash"),
            _WORKER: _p(_HOST, comm="python3"),
            _WORKER_CHILD: _p(_WORKER, _SUBAGENT, comm="python3"),
            200: _p(1, _FOREIGN, comm="claude"),
        },
    )


@pytest.mark.usefixtures("_clean_cache")
class TestLegacyHostFallback:
    def test_live_shape_resolves_the_claude_grandchild(self, tmp_path: Path) -> None:
        child = _mod.WorkerChildPid(
            proc_root=_live_shape(tmp_path), host_pid=lambda: _HOST, own_pid=lambda: _WORKER
        )
        assert child.learn(None) is None
        assert child.own_session_ids() == frozenset({_MINE})

    def test_resolver_excludes_the_worker_subtree_and_foreign_trees(self, tmp_path: Path) -> None:
        root = _live_shape(tmp_path)
        assert _mod.resolve_host_session_ids(_HOST, _WORKER, root) == frozenset({_MINE})

    def test_pid_one_host_resolves_nothing(self, tmp_path: Path) -> None:
        root = _live_shape(tmp_path)
        assert _mod.resolve_host_session_ids(1, _WORKER, root) == frozenset()

    def test_host_gone_resolves_nothing(self, tmp_path: Path) -> None:
        root = _fake_proc(tmp_path, {_WORKER: _p(1), 200: _p(1, _FOREIGN)})
        assert _mod.resolve_host_session_ids(_HOST, _WORKER, root) == frozenset()

    def test_a_sent_pid_replaces_the_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        child = _mod.WorkerChildPid(
            proc_root=_live_shape(tmp_path), host_pid=lambda: _HOST, own_pid=lambda: _WORKER
        )
        child.learn(None)
        seen: list[object] = []
        monkeypatch.setattr(
            _mod,
            "cached_own_session_ids",
            lambda child_pid, *a, **k: seen.append(child_pid) or frozenset({_MINE}),
        )
        assert child.learn(_CLAUDE) == _CLAUDE
        assert child.own_session_ids() == frozenset({_MINE})
        assert seen == [_CLAUDE]

    def test_run_worker_on_a_legacy_line_uses_the_host_tree(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen: list[object] = []
        real_decide = _mod.decide_once

        def record(*args: object, **kwargs: object) -> object:
            seen.append(kwargs["own_sessions"])
            return real_decide(*args, **kwargs)

        monkeypatch.setattr(_mod, "decide_once", record)
        facts = _mod.TickFacts(
            now_wall=_NOW,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
        )
        sidecars = tmp_path / "sidecars"
        sidecars.mkdir()
        _mod.run_worker(
            io.StringIO(_mod._facts_to_json(facts) + "\n"),
            io.StringIO(),
            dry_run=True,
            sidecar_dir=sidecars,
            policy=_mod.CompactPolicy(),
            child=_mod.WorkerChildPid(
                proc_root=_live_shape(tmp_path / "proc"),
                host_pid=lambda: _HOST,
                own_pid=lambda: _WORKER,
            ),
        )
        assert seen == [frozenset({_MINE})]


# ── the child pid crosses the host -> worker pipe ────────────────────────────


class TestChildPidOnTheWire:
    def _facts(self, **overrides: object) -> object:
        base: dict[str, object] = {
            "now_wall": _NOW,
            "idle": True,
            "input_line_empty": True,
            "human_compact_submitted": False,
            "work_idle": True,
        }
        base.update(overrides)
        return _mod.TickFacts(**base)

    def test_child_pid_round_trips(self) -> None:
        facts = self._facts(child_pid=_CHILD)
        assert _mod._facts_from_json(_mod._facts_to_json(facts)) == facts

    def test_a_legacy_host_line_has_no_child_pid(self) -> None:
        line = json.dumps(
            {
                "now_wall": _NOW,
                "idle": True,
                "input_line_empty": True,
                "human_compact_submitted": False,
                "work_idle": True,
            }
        )
        assert _mod._facts_from_json(line).child_pid is None

    def test_run_worker_scopes_identity_to_the_sent_child(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen: list[object] = []

        def record(child_pid: object, *_a: object, **_k: object) -> frozenset[str]:
            seen.append(child_pid)
            return frozenset()

        monkeypatch.setattr(_mod, "cached_own_session_ids", record)
        in_stream = io.StringIO(_mod._facts_to_json(self._facts(child_pid=_CHILD)) + "\n")
        out_stream = io.StringIO()
        _mod.run_worker(
            in_stream,
            out_stream,
            dry_run=True,
            sidecar_dir=tmp_path,
            policy=_mod.CompactPolicy(),
        )
        assert seen == [_CHILD]


class TestHostThreadsTheForkedPid:
    """The PTY host knows the pid it forked; every identity lookup uses it."""

    def _run(self, tmp_path: Path, **kwargs: object) -> int:
        stdin_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            code: int = _mod.supervise(
                ["bash", "-c", f"echo $$ > {tmp_path / 'pid'}; sleep 0.4; exit 0"],
                dry_run=True,
                stdin_fd=stdin_fd,
                poll_seconds=0.05,
                sidecar_dir=tmp_path / "context-sidecar",
                **kwargs,
            )
        finally:
            os.close(stdin_fd)
        return code

    def test_worker_ticks_carry_the_child_pid(self, tmp_path: Path) -> None:
        sent: list[object] = []

        def decider(facts: object) -> None:
            sent.append(getattr(facts, "child_pid", None))

        assert self._run(tmp_path, decider=decider) == 0
        child_pid = int((tmp_path / "pid").read_text().strip())
        assert sent
        assert set(sent) == {child_pid}

    def test_in_process_fallback_scopes_to_the_child_pid(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen: list[object] = []

        def record(child_pid: object, *_a: object, **_k: object) -> frozenset[str]:
            seen.append(child_pid)
            return frozenset()

        monkeypatch.setattr(_mod, "cached_own_session_ids", record)
        assert self._run(tmp_path) == 0
        child_pid = int((tmp_path / "pid").read_text().strip())
        assert seen
        assert set(seen) == {child_pid}


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
