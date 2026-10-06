"""N98: the AF_UNIX fallback paths differ per hostname."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.daemon.paths import (
    get_event_socket_dir,
    get_pid_path,
    get_socket_path,
)


@pytest.fixture
def long_project(tmp_path: Path) -> Path:
    """A project whose natural socket and events paths overflow the AF_UNIX limit."""
    project = tmp_path / ("p" * 100)
    (project / "untracked").mkdir(parents=True)
    return project


def _fallback_paths(project: Path, host: str, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    monkeypatch.setenv("HOSTNAME", host)
    paths._resolve_hostname_from_env.cache_clear()
    return [get_socket_path(project), get_pid_path(project), get_event_socket_dir(project)]


class TestFallbackPathsPerHost:
    """Two hosts sharing a filesystem must not resolve the same fallback files."""

    def test_two_hostnames_get_distinct_paths(
        self, long_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(long_project.parent))
        host_a = _fallback_paths(long_project, "host-a", monkeypatch)
        host_b = _fallback_paths(long_project, "host-b", monkeypatch)
        assert all(a != b for a, b in zip(host_a, host_b, strict=True))
        assert all(str(p).startswith(str(long_project.parent)) for p in host_a)

    def test_the_same_hostname_gets_the_same_paths(
        self, long_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(long_project.parent))
        first = _fallback_paths(long_project, "host-a", monkeypatch)
        assert _fallback_paths(long_project, "host-a", monkeypatch) == first
