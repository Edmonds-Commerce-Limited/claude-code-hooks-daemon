"""``pid_path_for``: where a checkout's daemon pid file is, without creating anything.

``get_pid_path`` creates the untracked directory as a side effect, so a read-only
scan of ANOTHER checkout cannot call it. Both share ``pid_path_for``, including
the AF_UNIX-overflow relocation (Plan 00470 Task 4.5).
"""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import get_pid_path, pid_file_name, pid_path_for


@pytest.fixture(autouse=True)
def _no_pid_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_HOOKS_PID_PATH", raising=False)


@pytest.fixture
def short_root() -> Iterator[Path]:
    """A root short enough that the pid file is NOT relocated."""
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="hk") as root:
        yield Path(root)


def test_short_root_names_the_file_in_its_untracked_dir(short_root: Path) -> None:
    path = pid_path_for(short_root)

    assert path.name == pid_file_name()
    assert path.parent.name == "untracked"


def test_creates_nothing(short_root: Path) -> None:
    pid_path_for(short_root)

    assert list(short_root.iterdir()) == []


def test_agrees_with_get_pid_path(short_root: Path) -> None:
    assert pid_path_for(short_root) == get_pid_path(short_root)


def test_a_long_root_is_relocated_exactly_as_get_pid_path_relocates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    root = tmp_path / ("d" * 120) / "project"
    root.mkdir(parents=True)

    path = pid_path_for(root)

    assert path.parent == runtime
    assert path == get_pid_path(root)


def test_the_environment_override_is_not_applied(
    short_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The override names THIS process's daemon, not another checkout's."""
    monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(tmp_path / "elsewhere.pid"))

    assert pid_path_for(short_root).name == pid_file_name()
