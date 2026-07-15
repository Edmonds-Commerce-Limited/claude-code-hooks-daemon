"""Tests for the policy-worker error safety net (Plan 00166).

The policy worker runs as a subprocess of the PTY host. Its stderr MUST NEVER
reach the inherited terminal: a per-tick exception (or a host/worker version
skew after a hot-reload) would otherwise flood the live Claude session with
tracebacks. Two guarantees are enforced here:

1. The worker's stderr is redirected to a FILE (or ``/dev/null``), never a tty
   (``PolicyWorker.start`` Popen ``stderr``; ``_redirect_worker_stderr_to_log``).
2. A single tick's exception can never kill the worker -- it is caught, the
   traceback is written to the error FILE, and a safe NOOP is emitted so the
   host still gets a reply (``run_worker`` per-tick guard).
"""

import io
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    import pytest

_mod = load_supervisor_module()

_NOW = 1_000_000.0
_SUPERVISOR = Path("/workspace/.claude/ccy/claude-supervise.py")


def _tick_line() -> str:
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )
    return _mod._facts_to_json(facts) + "\n"


class _FakeProc:
    """Minimal stand-in for the worker subprocess handle."""

    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0


# ── error-log helpers ────────────────────────────────────────────────────────


class TestWorkerErrorLog:
    def test_open_returns_writable_handle(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        errlog = tmp_path / "sub" / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: errlog)
        handle = _mod.open_worker_error_log()
        assert handle is not None
        handle.write("hi\n")
        handle.close()
        assert errlog.read_text(encoding="utf-8") == "hi\n"

    def test_open_returns_none_when_unopenable(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        # A file sits where a directory would need to be, so mkdir/open fail and
        # the None sentinel is returned (caller then uses DEVNULL).
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            _mod, "worker_error_log_path", lambda: blocker / "nested" / "worker.err.log"
        )
        assert _mod.open_worker_error_log() is None

    def test_append_writes_timestamped_line(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        errlog = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: errlog)
        _mod.append_worker_error("boom happened")
        text = errlog.read_text(encoding="utf-8")
        assert "boom happened" in text
        assert text.startswith("[")  # timestamp prefix

    def test_append_never_raises_when_unwritable(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            _mod, "worker_error_log_path", lambda: blocker / "nested" / "worker.err.log"
        )
        # Must not raise -- last-resort logger silently drops.
        _mod.append_worker_error("this cannot be written")


# ── NOOP fallback ────────────────────────────────────────────────────────────


class TestWorkerErrorNoop:
    def test_is_noop_with_null_machine_state(self) -> None:
        outcome = _mod._worker_error_noop()
        assert outcome.decision_value == _mod.Decision.NOOP.value
        assert outcome.payload is None
        # machine_state None leaves the host's authoritative state untouched.
        assert outcome.machine_state is None


# ── run_worker per-tick safety net ───────────────────────────────────────────


class TestRunWorkerSafetyNet:
    def test_survives_raising_decide_once(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        errlog = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: errlog)

        def _boom(*_a: object, **_k: object) -> object:
            raise RuntimeError("simulated decide_once explosion")

        monkeypatch.setattr(_mod, "decide_once", _boom)
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({"s"}))

        out = io.StringIO()
        cap_err = io.StringIO()
        monkeypatch.setattr("sys.stderr", cap_err)
        rc = _mod.run_worker(
            io.StringIO(_tick_line() * 3),
            out,
            dry_run=True,
            sidecar_dir=tmp_path,
            policy=_mod.CompactPolicy(),
        )

        assert rc == 0  # survived all three exploding ticks
        emitted = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
        assert len(emitted) == 3
        assert all(o["decision_value"] == _mod.Decision.NOOP.value for o in emitted)
        # The traceback went to the FILE, and NOTHING leaked to stderr.
        assert cap_err.getvalue() == ""
        assert "simulated decide_once explosion" in errlog.read_text(encoding="utf-8")

    def test_bad_tick_line_logged_not_stderr(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        errlog = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: errlog)
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({"s"}))

        out = io.StringIO()
        cap_err = io.StringIO()
        monkeypatch.setattr("sys.stderr", cap_err)
        # A malformed line followed by a valid one: the worker logs the bad line
        # to the file, then processes the good tick.
        rc = _mod.run_worker(
            io.StringIO("{not json}\n" + _tick_line()),
            out,
            dry_run=True,
            sidecar_dir=tmp_path,
            policy=_mod.CompactPolicy(),
        )
        assert rc == 0
        assert cap_err.getvalue() == ""
        assert "bad tick line" in errlog.read_text(encoding="utf-8")
        assert len([line for line in out.getvalue().splitlines() if line.strip()]) == 1


# ── PolicyWorker.start stderr redirection ────────────────────────────────────


class TestPolicyWorkerStderrRedirect:
    def test_start_never_inherits_stderr(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        errlog = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: errlog)
        captured: dict[str, object] = {}

        def _fake_popen(argv: list[str], **kwargs: object) -> _FakeProc:
            captured.update(kwargs)
            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        worker = _mod.PolicyWorker(_SUPERVISOR, dry_run=True)
        assert worker.start() is True
        # stderr MUST be a real handle (or DEVNULL) -- never None, which would
        # inherit the terminal.
        assert "stderr" in captured
        assert captured["stderr"] is not None
        worker.close()

    def test_start_falls_back_to_devnull_when_log_unopenable(
        self, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        monkeypatch.setattr(_mod, "open_worker_error_log", lambda: None)
        captured: dict[str, object] = {}

        def _fake_popen(argv: list[str], **kwargs: object) -> _FakeProc:
            captured.update(kwargs)
            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        worker = _mod.PolicyWorker(_SUPERVISOR, dry_run=True)
        assert worker.start() is True
        # No file handle available -> DEVNULL, still never the inherited tty.
        assert captured["stderr"] == subprocess.DEVNULL
        worker.close()
