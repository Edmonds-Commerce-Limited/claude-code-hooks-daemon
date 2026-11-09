"""A walked directory entry is opened only when it is a regular file.

The supervisor globs its signal directories and reads what it finds. A FIFO
there (planted or left by accident) made ``read_text`` block in ``open`` for
ever, hanging the tick that read it; fedora-desktop's
walk-opens-non-regular-file gate found these sites at v3.73.0. Each loader must
skip or report a non-regular entry and return, never block.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

#: Far above any real read, far below "for ever".
_RETURN_WITHIN_SECONDS = 5.0


def _release(fifo: Path) -> None:
    """Unblock a reader stuck opening ``fifo`` (a writer's open completes its open)."""
    try:
        descriptor = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return
    os.close(descriptor)


def _returns(call: Callable[[], object], fifo: Path) -> bool:
    finished = threading.Event()

    def run() -> None:
        try:
            call()
        finally:
            finished.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    returned = finished.wait(_RETURN_WITHIN_SECONDS)
    if not returned:
        _release(fifo)
        worker.join(_RETURN_WITHIN_SECONDS)
    return returned


_NOW = 1_800_000_000.0

#: (FIFO name, the loader reading the directory it sits in).
_LOADERS: list[tuple[str, Callable[[Path], object]]] = [
    ("x.json", lambda d: _mod._scan_sidecars(d)),
    ("x.compacting", lambda d: _mod.load_compaction_signal(d, now=_NOW, ttl_seconds=60.0)),
    (
        f"x{_mod._USAGE_PAUSE_SUFFIX}",
        lambda d: _mod.load_usage_pause(d, now=_NOW, own_sessions=None),
    ),
    ("x.goal-clear", lambda d: _mod.load_goal_clear_signal(d, now=_NOW)),
    ("x.goal-intent", lambda d: _mod.load_goal_signal(d, now=_NOW)),
    ("x.standing-auth-intent", lambda d: _mod.load_standing_auth_signal(d, now=_NOW)),
    (
        f"x{_mod._SESSION_ACTIONS_SIGNAL_SUFFIX}",
        lambda d: _mod.load_session_actions_signal(d, now=_NOW),
    ),
    (f"x{_mod._MODEL_SWITCH_SIGNAL_SUFFIX}", lambda d: _mod.load_model_switch_signal(d, now=_NOW)),
    (
        _mod._MODEL_DOWNGRADE_SIGNAL_GLOB.replace("*", "x"),
        lambda d: _mod.load_model_downgrade_signal(d),
    ),
    (
        _mod._OPERATOR_SIGNAL_GLOB.replace("*", "x"),
        lambda d: _mod.load_operator_signal(d, now=_NOW),
    ),
    (
        f"x{_mod._SESSION_MODES_SUFFIX}",
        lambda d: _mod.load_session_modes(d, now=_NOW, own_sessions=None),
    ),
]


@pytest.mark.parametrize(("name", "loader"), _LOADERS, ids=[name for name, _ in _LOADERS])
def test_a_fifo_in_the_walked_directory_does_not_block(
    tmp_path: Path, name: str, loader: Callable[[Path], object]
) -> None:
    fifo = tmp_path / name
    os.mkfifo(fifo)
    assert _returns(lambda: loader(tmp_path), fifo), f"{name}: the loader blocked opening a FIFO"


def test_a_fifo_under_the_proc_root_does_not_block(tmp_path: Path) -> None:
    pid_dir = tmp_path / "4242"
    pid_dir.mkdir()
    fifo = pid_dir / "stat"
    os.mkfifo(fifo)
    assert _returns(lambda: _mod._proc_parent_map(tmp_path), fifo)


class TestReadRegularText:
    def test_reads_a_regular_file(self, tmp_path: Path) -> None:
        path = tmp_path / "a.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        assert _mod._read_regular_text(path) == '{"a": 1}'

    def test_refuses_a_fifo_as_an_os_error_without_blocking(self, tmp_path: Path) -> None:
        fifo = tmp_path / "f.json"
        os.mkfifo(fifo)
        errors: list[BaseException] = []

        def call() -> None:
            try:
                _mod._read_regular_text(fifo)
            except OSError as error:
                errors.append(error)

        assert _returns(call, fifo)
        assert errors, "a FIFO must be refused with an OSError"

    def test_refuses_a_directory(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            _mod._read_regular_text(tmp_path)

    def test_a_missing_file_is_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _mod._read_regular_text(tmp_path / "absent")
