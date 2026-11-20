"""Acceptance socket discovery follows the daemon's own socket resolver.

When the natural socket path exceeds the AF_UNIX limit the daemon binds a
fallback under ``/tmp``; discovery that only globs ``untracked/`` then misses
it and every acceptance test errors (Plan 00606 Task 1.2).
"""

from __future__ import annotations

import shutil
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.acceptance import conftest as acceptance_conftest


@pytest.fixture
def listening_fallback_socket() -> Iterator[Path]:
    """A live socket at a short ``/tmp`` path, as the daemon's fallback would be."""
    directory = Path(tempfile.mkdtemp(prefix="hd-"))
    path = directory / "d.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    try:
        yield path
    finally:
        server.close()
        shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def empty_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo root with nothing under ``untracked/`` and no env override."""
    (tmp_path / "untracked").mkdir()
    monkeypatch.setattr(acceptance_conftest, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("CLAUDE_HOOKS_SOCKET_PATH", raising=False)
    return tmp_path


class TestDiscoverSocket:
    def test_finds_the_socket_at_the_resolvers_fallback_path(
        self,
        empty_repo: Path,
        listening_fallback_socket: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[Path] = []

        def resolver(project_dir: Path | str) -> Path:
            seen.append(Path(project_dir))
            return listening_fallback_socket

        monkeypatch.setattr(acceptance_conftest, "get_socket_path", resolver)
        assert acceptance_conftest._discover_socket() == listening_fallback_socket
        assert seen == [empty_repo]

    def test_returns_none_when_the_resolved_path_has_no_live_socket(
        self,
        empty_repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            acceptance_conftest, "get_socket_path", lambda project_dir: tmp_path / "absent.sock"
        )
        assert acceptance_conftest._discover_socket() is None

    def test_the_env_override_is_tried_before_the_resolver(
        self,
        empty_repo: Path,
        listening_fallback_socket: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(listening_fallback_socket))

        def resolver(project_dir: Path | str) -> Path:
            raise AssertionError("the env override must win")

        monkeypatch.setattr(acceptance_conftest, "get_socket_path", resolver)
        assert acceptance_conftest._discover_socket() == listening_fallback_socket
