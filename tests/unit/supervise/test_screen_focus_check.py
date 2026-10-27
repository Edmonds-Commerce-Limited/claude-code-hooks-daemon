"""Plan 00538 Phase 2 -- the screen verdict that decides the main-thread focus hold.

The supervisor keeps a bounded copy of the child's raw output (no parsing on
the hot path) and, only when a keystroke latch asks for a verdict, spawns
`hooks-screen` on it. Only `transcript` / `panel-selected` hold; everything
else, including every failure, fails OPEN.
"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
ScreenBuffer = _mod.ScreenBuffer
ScreenFocusCheck = _mod.ScreenFocusCheck
FocusHold = _mod.FocusHold
InputActivity = _mod.InputActivity
OutputActivity = _mod.OutputActivity
resolve_screen_binary = _mod.resolve_screen_binary

_HOLD = FocusHold(reason="bare Up arrow", since=1.0, latch_bytes="\\x1b[A")


def _stub(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _word_stub(tmp_path: Path, word: str) -> Path:
    return _stub(tmp_path / f"screen-{word}", f"cat >/dev/null; echo {word}")


def _check(binary: Path | None, buf: Any = None, **kw: Any) -> Any:
    buffer = buf if buf is not None else ScreenBuffer()
    buffer.append(b"some output")
    return ScreenFocusCheck(buffer, binary=binary, size_fn=lambda: (100, 30), **kw)


class TestScreenBuffer:
    def test_appends_and_snapshots(self) -> None:
        buf = ScreenBuffer(cap=100)
        buf.append(b"abc")
        buf.append(b"def")
        assert buf.snapshot() == b"abcdef"
        assert buf.total_appended == 6

    def test_overflow_drops_from_the_front(self) -> None:
        buf = ScreenBuffer(cap=10)
        buf.append(b"0123456789")
        buf.append(b"abcd")
        assert buf.snapshot() == b"456789abcd"
        assert buf.total_appended == 14

    def test_chunk_larger_than_cap_keeps_its_tail(self) -> None:
        buf = ScreenBuffer(cap=4)
        buf.append(b"abcdefgh")
        assert buf.snapshot() == b"efgh"

    @pytest.mark.parametrize(
        "marker",
        [b"\x1b[2J", b"\x1b[3J", b"\x1b[?1049h", b"\x1b[?1049l"],
    )
    def test_full_redraw_boundary_resets_to_the_marker(self, marker: bytes) -> None:
        buf = ScreenBuffer(cap=1000)
        buf.append(b"old frame\r\n")
        buf.append(b"tail of old" + marker + b"new")
        assert buf.snapshot() == marker + b"new"

    def test_last_boundary_in_a_chunk_wins(self) -> None:
        buf = ScreenBuffer(cap=1000)
        buf.append(b"a\x1b[2Jb\x1b[3Jc")
        assert buf.snapshot() == b"\x1b[3Jc"

    def test_no_boundary_keeps_everything(self) -> None:
        buf = ScreenBuffer(cap=1000)
        buf.append(b"x\x1b[Ay\x1b[2Ky")
        assert buf.snapshot() == b"x\x1b[Ay\x1b[2Ky"

    def test_default_cap_is_256_kib(self) -> None:
        assert ScreenBuffer().cap == 256 * 1024

    def test_rejects_a_non_positive_cap(self) -> None:
        with pytest.raises(ValueError, match="cap"):
            ScreenBuffer(cap=0)


class TestOutputActivityFeedsBuffer:
    def test_record_appends_when_a_buffer_is_attached(self) -> None:
        oa = OutputActivity()
        oa.buffer = ScreenBuffer()
        oa.record(b"hi")
        assert oa.buffer.snapshot() == b"hi"

    def test_record_without_a_buffer_copies_nothing(self) -> None:
        oa = OutputActivity()
        oa.record(b"hi")
        assert oa.buffer is None


class TestVerdict:
    @pytest.mark.parametrize("word", ["main", "transcript", "panel-selected", "unknown"])
    def test_each_word_is_returned(self, tmp_path: Path, word: str) -> None:
        assert _check(_word_stub(tmp_path, word)).verdict() == word

    def test_missing_binary_is_unknown(self, tmp_path: Path) -> None:
        assert _check(tmp_path / "nope").verdict() == "unknown"

    def test_no_binary_configured_is_unknown(self) -> None:
        assert _check(None).verdict() == "unknown"

    def test_non_zero_exit_is_unknown(self, tmp_path: Path) -> None:
        stub = _stub(tmp_path / "bad", "cat >/dev/null; echo transcript; exit 3")
        assert _check(stub).verdict() == "unknown"

    def test_timeout_is_unknown(self, tmp_path: Path) -> None:
        stub = _stub(tmp_path / "slow", "sleep 5; echo transcript")
        assert _check(stub, timeout=0.2).verdict() == "unknown"

    def test_unrecognised_word_is_unknown(self, tmp_path: Path) -> None:
        stub = _stub(tmp_path / "odd", "cat >/dev/null; echo banana")
        assert _check(stub).verdict() == "unknown"

    def test_unexecutable_binary_is_unknown(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.write_text("not executable")
        assert _check(plain).verdict() == "unknown"

    def test_buffer_and_size_are_passed_through(self, tmp_path: Path) -> None:
        seen = tmp_path / "seen"
        stub = _stub(tmp_path / "rec", f'echo "$@" >{seen}.args; cat >{seen}.stdin; echo main')
        buf = ScreenBuffer()
        check = ScreenFocusCheck(buf, binary=stub, size_fn=lambda: (120, 40))
        buf.append(b"RAW\x1b[2K")
        assert check.verdict() == "main"
        assert (tmp_path / "seen.args").read_text().split() == ["--cols", "120", "--rows", "40"]
        assert (tmp_path / "seen.stdin").read_bytes() == b"RAW\x1b[2K"


class TestEffectiveHold:
    def test_no_latch_means_no_hold_and_no_spawn(self, tmp_path: Path) -> None:
        marker = tmp_path / "spawned"
        stub = _stub(tmp_path / "s", f"touch {marker}; echo transcript")
        assert _check(stub).effective_hold(None) is None
        assert not marker.exists()

    @pytest.mark.parametrize("word", ["transcript", "panel-selected"])
    def test_holding_words_keep_the_latch(self, tmp_path: Path, word: str) -> None:
        assert _check(_word_stub(tmp_path, word)).effective_hold(_HOLD) is _HOLD

    @pytest.mark.parametrize("word", ["main", "unknown"])
    def test_other_words_release_the_latch(self, tmp_path: Path, word: str) -> None:
        assert _check(_word_stub(tmp_path, word)).effective_hold(_HOLD) is None

    def test_missing_binary_fails_open(self, tmp_path: Path) -> None:
        assert _check(tmp_path / "nope").effective_hold(_HOLD) is None

    def test_unchanged_screen_is_not_rendered_twice(self, tmp_path: Path) -> None:
        count = tmp_path / "count"
        stub = _stub(tmp_path / "s", f"cat >/dev/null; echo x >>{count}; echo transcript")
        clock = [0.0]
        check = _check(stub, clock=lambda: clock[0])
        assert check.effective_hold(_HOLD) is _HOLD
        clock[0] = 50.0
        assert check.effective_hold(_HOLD) is _HOLD
        assert count.read_text().count("x") == 1

    def test_changed_screen_is_rendered_again_after_the_min_interval(self, tmp_path: Path) -> None:
        count = tmp_path / "count"
        stub = _stub(tmp_path / "s", f"cat >/dev/null; echo x >>{count}; echo transcript")
        clock = [0.0]
        buf = ScreenBuffer()
        check = _check(stub, buf, clock=lambda: clock[0], min_interval=1.0)
        check.effective_hold(_HOLD)
        buf.append(b"more")
        clock[0] = 0.5
        check.effective_hold(_HOLD)
        assert count.read_text().count("x") == 1
        clock[0] = 2.0
        check.effective_hold(_HOLD)
        assert count.read_text().count("x") == 2


class TestCapture:
    def test_decision_writes_raw_dump_and_verdict(self, tmp_path: Path) -> None:
        stub = _stub(
            tmp_path / "s",
            'cat >/dev/null; if [ "$1" = "--dump" ] || [ "$5" = "--dump" ]; '
            "then echo ROW; else echo unknown; fi",
        )
        cap = tmp_path / "cap"
        check = _check(stub, capture_dir=cap)
        check.effective_hold(_HOLD)
        files = sorted(p.name for p in cap.iterdir())
        assert [f.split(".")[-1] for f in files] == ["dump", "raw", "verdict"]
        assert (next(cap.glob("*.raw"))).read_bytes() == b"some output"
        assert next(cap.glob("*.verdict")).read_text().strip() == "unknown"

    def test_only_the_last_twenty_decisions_are_kept(self, tmp_path: Path) -> None:
        cap = tmp_path / "cap"
        buf = ScreenBuffer()
        clock = [0.0]
        check = _check(
            _word_stub(tmp_path, "unknown"), buf, capture_dir=cap, clock=lambda: clock[0]
        )
        for i in range(25):
            clock[0] += 10.0
            buf.append(bytes([65 + i % 26]))
            check.effective_hold(_HOLD)
        assert len(list(cap.glob("*.raw"))) == 20
        assert len(list(cap.glob("*"))) == 60

    def test_no_capture_dir_writes_nothing(self, tmp_path: Path) -> None:
        _check(_word_stub(tmp_path, "unknown")).effective_hold(_HOLD)
        assert not (tmp_path / "cap").exists()


class TestResolveBinary:
    def _exe(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        return _stub(path, "true")

    def test_env_override_wins(self, tmp_path: Path) -> None:
        override = self._exe(tmp_path / "mine")
        self._exe(tmp_path / "proj" / "untracked" / "bin" / "hooks-screen")
        env = {"CCY_HOOKS_SCREEN": str(override)}
        assert resolve_screen_binary(tmp_path / "proj", env) == override

    def test_deployed_path_then_built_path(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        built = self._exe(
            proj / "untracked" / "screen-build" / "hooks-screen-x86_64-unknown-linux-musl"
        )
        assert resolve_screen_binary(proj, {}) == built
        deployed = self._exe(proj / "untracked" / "bin" / "hooks-screen")
        assert resolve_screen_binary(proj, {}) == deployed

    def test_nothing_found_is_none(self, tmp_path: Path) -> None:
        assert resolve_screen_binary(tmp_path, {}) is None

    def test_non_executable_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "untracked" / "bin" / "hooks-screen"
        path.parent.mkdir(parents=True)
        path.write_text("x")
        path.chmod(0o644)
        assert resolve_screen_binary(tmp_path, {}) is None


class TestInputActivityDecision:
    """The screen verdict, not the keystroke latch alone, decides the hold."""

    def _armed(self, tmp_path: Path, word: str) -> Any:
        activity = InputActivity()
        activity.focus = _mod.MainFocusModel(enabled=True)
        activity.screen = _check(_word_stub(tmp_path, word))
        activity.focus.feed(b"\x1b[A", now=1.0)
        return activity

    def test_latch_plus_transcript_holds(self, tmp_path: Path) -> None:
        activity = self._armed(tmp_path, "transcript")
        assert activity.effective_focus_hold() is not None
        assert activity.focus_confirmed() is False

    def test_latch_plus_unknown_does_not_hold(self, tmp_path: Path) -> None:
        activity = self._armed(tmp_path, "unknown")
        assert activity.effective_focus_hold() is None
        assert activity.focus_confirmed() is True

    def test_without_a_screen_check_the_latch_alone_decides(self) -> None:
        activity = InputActivity()
        activity.focus = _mod.MainFocusModel(enabled=True)
        activity.focus.feed(b"\x1b[A", now=1.0)
        assert activity.effective_focus_hold() is not None

    def test_without_a_latch_nothing_holds(self, tmp_path: Path) -> None:
        activity = InputActivity()
        activity.focus = _mod.MainFocusModel(enabled=True)
        activity.screen = _check(_word_stub(tmp_path, "transcript"))
        assert activity.effective_focus_hold() is None


class TestEnvSwitches:
    def test_capture_is_opt_in_with_exactly_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CCY_SCREEN_CAPTURE", raising=False)
        assert _mod._screen_capture_enabled_from_env() is False
        monkeypatch.setenv("CCY_SCREEN_CAPTURE", "yes")
        assert _mod._screen_capture_enabled_from_env() is False
        monkeypatch.setenv("CCY_SCREEN_CAPTURE", "1")
        assert _mod._screen_capture_enabled_from_env() is True

    def test_winsize_cells_decodes_rows_and_cols(self) -> None:
        import struct

        raw = struct.pack("HHHH", 30, 100, 0, 0)
        assert _mod._winsize_cells(raw) == (100, 30)


class TestBuildScreenCheck:
    def test_attaches_a_buffer_and_resolves_the_binary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _word_stub(tmp_path, "transcript")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CCY_HOOKS_SCREEN", str(stub))
        monkeypatch.delenv("CCY_SCREEN_CAPTURE", raising=False)
        oa = OutputActivity()
        read_fd, write_fd = os.pipe()
        try:
            check = _mod._build_screen_check(oa, stdin_fd=read_fd, log=None)
            oa.record(b"frame")
            assert oa.buffer is not None
            assert oa.buffer.snapshot() == b"frame"
            assert check.verdict() == "transcript"
            assert not (tmp_path / "untracked" / "supervise" / "screen-capture").exists()
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_capture_env_sets_the_capture_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CCY_HOOKS_SCREEN", str(_word_stub(tmp_path, "unknown")))
        monkeypatch.setenv("CCY_SCREEN_CAPTURE", "1")
        oa = OutputActivity()
        check = _mod._build_screen_check(oa, stdin_fd=0, log=None)
        oa.record(b"frame")
        check.effective_hold(_HOLD)
        assert list((tmp_path / "untracked" / "supervise" / "screen-capture").glob("*.raw"))
