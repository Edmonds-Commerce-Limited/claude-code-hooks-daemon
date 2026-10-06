"""A protected-file index build never outlives the test that started it.

``index_for`` builds in a background thread that runs ``git`` through
``subprocess.run``. Left running into the next test, that thread consumed the
``side_effect`` list of a ``subprocess.run`` mock the next test had patched, and
the test's own call raised ``StopIteration`` (order-dependent, passes alone).
The autouse fixture in ``tests/conftest.py`` waits for, then forgets, every build.

The two tests below depend on running in this order (pytest keeps definition
order); this module deliberately has no cache-resetting fixture of its own, which
would mask the leak.
"""

import threading
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import protected_file_index as pfi

_RELEASE = threading.Event()


class TestABuildStartedByOneTestIsGoneBeforeTheNext:
    def test_a_starts_a_build_that_is_still_running_when_the_test_ends(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _RELEASE.clear()

        def slow(root: Path, patterns: tuple[str, ...]) -> None:
            _RELEASE.wait(timeout=10)

        monkeypatch.setattr(pfi, "build_index", slow)
        threading.Timer(0.3, _RELEASE.set).start()

        assert pfi.index_for(tmp_path, ("x",)) is None
        assert pfi._building

    def test_b_finds_no_build_in_flight_and_no_remembered_failure(self) -> None:
        assert not pfi._building
        assert not pfi._failed_at
        assert not pfi._cache


class TestResetForgetsEverything:
    def test_failures_and_builds_are_cleared(self, tmp_path: Path) -> None:
        key = pfi._key(tmp_path, ("x",))
        pfi._failed_at[key] = 1.0

        pfi.reset_index_cache()

        assert not pfi._failed_at
        assert not pfi._building
        assert not pfi._cache
