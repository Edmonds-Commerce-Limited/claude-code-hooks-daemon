"""The shared child-pytest runner (Plan 00474 N531).

Every child pytest the suite spawns goes through ``run_child_pytest``. These
tests REALLY spawn a child pytest each: the properties under test (where the
child's temporary tree lives, what it can see of the caller's environment,
what it prints when it hangs) only exist in a separate process.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.load_scaling import scaled_seconds
from tests.support.child_pytest import (
    HELPER_OWNED_ENV_KEYS,
    WATCHDOG_FRACTION,
    ChildPytestError,
    run_child_pytest,
)

#: Idle-host budget for a child that is MEANT to hang: long enough for pytest
#: to start, short enough that the two hang tests stay cheap.
_HANG_BASE_SECONDS = 10.0

#: A timeout the helper must refuse.
_NON_POSITIVE_SECONDS = 0.0


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return path


def _seed_shared_temproot(temproot: Path, count: int) -> Path:
    """Unlocked ``pytest-N`` dirs, the shape every earlier child leaves behind."""
    user_root = temproot / f"pytest-of-{getpass.getuser()}"
    user_root.mkdir(mode=0o700, parents=True)
    for number in range(count):
        seeded = user_root / f"pytest-{number}"
        seeded.mkdir(mode=0o700)
        (seeded / "payload.txt").write_text("left by an earlier child\n", encoding="utf-8")
    return user_root


class TestExitStatus:
    def test_a_passing_child_is_returned(self, tmp_path: Path) -> None:
        _write(tmp_path / "test_ok.py", "def test_ok():\n    assert True\n")

        completed = run_child_pytest(["-q", "test_ok.py"], cwd=tmp_path, tmp_path=tmp_path)

        assert completed.returncode == 0
        assert "1 passed" in completed.stdout

    def test_an_unexpected_exit_raises_with_the_childs_output(self, tmp_path: Path) -> None:
        _write(tmp_path / "test_bad.py", "def test_bad():\n    assert 1 == 2, 'one is not two'\n")

        with pytest.raises(ChildPytestError) as raised:
            run_child_pytest(
                ["-q", "test_bad.py"], cwd=tmp_path, tmp_path=tmp_path, explain="the pair broke"
            )

        message = str(raised.value)
        assert "the pair broke" in message
        assert "exited 1, expected 0" in message
        assert "one is not two" in message

    def test_an_expected_nonzero_exit_is_returned(self, tmp_path: Path) -> None:
        _write(tmp_path / "test_bad.py", "def test_bad():\n    assert False\n")

        completed = run_child_pytest(
            ["-q", "test_bad.py"], cwd=tmp_path, tmp_path=tmp_path, expected_returncode=1
        )

        assert "1 failed" in completed.stdout

    def test_a_non_positive_timeout_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="timeout"):
            run_child_pytest(["-q"], cwd=tmp_path, tmp_path=tmp_path, timeout=_NON_POSITIVE_SECONDS)


class TestTheChildOwnsItsTemporaryTree:
    def test_the_childs_tmp_path_is_under_the_callers_tmp_path(self, tmp_path: Path) -> None:
        record = tmp_path / "child_tmp_path.txt"
        _write(
            tmp_path / "test_where.py",
            f"""
            from pathlib import Path


            def test_where(tmp_path):
                Path({str(record)!r}).write_text(str(tmp_path))
            """,
        )

        run_child_pytest(["-q", "test_where.py"], cwd=tmp_path, tmp_path=tmp_path)

        assert Path(record.read_text(encoding="utf-8")).is_relative_to(tmp_path)

    def test_without_the_helper_a_child_sweeps_the_shared_temproot(self, tmp_path: Path) -> None:
        """Control: the seeded shape IS what an ordinary child's exit deletes,
        so the next test's survival result means something."""
        temproot = tmp_path / "temproot"
        user_root = _seed_shared_temproot(temproot, count=6)
        _write(tmp_path / "suite" / "test_tmp.py", "def test_tmp(tmp_path):\n    pass\n")
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in HELPER_OWNED_ENV_KEYS and not key.startswith("PYTEST_")
        }
        env["PYTEST_DEBUG_TEMPROOT"] = str(temproot)

        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_tmp.py"],
            cwd=tmp_path / "suite",
            env=env,
            capture_output=True,
            text=True,
            timeout=scaled_seconds(60.0),
            check=True,
        )

        assert not (user_root / "pytest-0").exists()

    def test_with_the_helper_the_shared_temproot_is_left_alone(self, tmp_path: Path) -> None:
        temproot = tmp_path / "temproot"
        user_root = _seed_shared_temproot(temproot, count=6)
        _write(tmp_path / "suite" / "test_tmp.py", "def test_tmp(tmp_path):\n    pass\n")

        run_child_pytest(
            ["-q", "-p", "no:cacheprovider", "test_tmp.py"],
            cwd=tmp_path / "suite",
            tmp_path=tmp_path,
            extra_env={"PYTEST_DEBUG_TEMPROOT": str(temproot)},
        )

        assert sorted(path.name for path in user_root.iterdir()) == [
            f"pytest-{number}" for number in range(6)
        ]

    def test_two_children_from_one_caller_get_separate_trees(self, tmp_path: Path) -> None:
        _write(tmp_path / "test_ok.py", "def test_ok(tmp_path):\n    pass\n")

        for _ in range(2):
            run_child_pytest(["-q", "test_ok.py"], cwd=tmp_path, tmp_path=tmp_path)

        assert len([path for path in tmp_path.iterdir() if path.name.startswith(".child")]) == 2


class TestTheChildEnvironmentIsBuiltExplicitly:
    def test_an_ambient_variable_does_not_reach_the_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("N531_AMBIENT_SENTINEL", "leaked")
        _write(
            tmp_path / "test_env.py",
            """
            import os


            def test_env():
                assert "N531_AMBIENT_SENTINEL" not in os.environ
            """,
        )

        run_child_pytest(["-q", "test_env.py"], cwd=tmp_path, tmp_path=tmp_path)

    def test_extra_env_and_pythonpath_reach_the_child(self, tmp_path: Path) -> None:
        library = tmp_path / "lib"
        _write(library / "n531_probe_module.py", "VALUE = 'imported'\n")
        _write(
            tmp_path / "test_env.py",
            """
            import os

            import n531_probe_module


            def test_env():
                assert os.environ["N531_EXTRA"] == "given"
                assert n531_probe_module.VALUE == "imported"
            """,
        )

        run_child_pytest(
            ["-q", "test_env.py"],
            cwd=tmp_path,
            tmp_path=tmp_path,
            extra_env={"N531_EXTRA": "given"},
            pythonpath=(library,),
        )

    @pytest.mark.parametrize("key", sorted(HELPER_OWNED_ENV_KEYS))
    def test_extra_env_may_not_set_a_helper_owned_key(self, tmp_path: Path, key: str) -> None:
        with pytest.raises(ValueError, match=key):
            run_child_pytest(["-q"], cwd=tmp_path, tmp_path=tmp_path, extra_env={key: "x"})


class TestALauncher:
    def test_a_pytest_started_by_a_launcher_still_gets_its_own_tree(self, tmp_path: Path) -> None:
        record = tmp_path / "child_tmp_path.txt"
        _write(
            tmp_path / "test_where.py",
            f"""
            from pathlib import Path


            def test_where(tmp_path):
                Path({str(record)!r}).write_text(str(tmp_path))
            """,
        )

        run_child_pytest(
            [],
            cwd=tmp_path,
            tmp_path=tmp_path,
            launcher=["bash", "-c", f"{sys.executable} -m pytest -q test_where.py"],
        )

        assert Path(record.read_text(encoding="utf-8")).is_relative_to(tmp_path)

    def test_pytest_arguments_beside_a_launcher_are_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="launcher"):
            run_child_pytest(["-q"], cwd=tmp_path, tmp_path=tmp_path, launcher=["bash"])


class TestAHangPrintsTheChildsStacks:
    """A hang must report WHERE the child is, not a bare ``TimeoutExpired``."""

    def test_the_watchdog_fires_before_the_callers_timeout(self) -> None:
        assert 0 < WATCHDOG_FRACTION < 1

    def test_a_hang_inside_a_test(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "test_hang.py",
            """
            import time


            def test_hangs_inside_the_test():
                time.sleep(600)
            """,
        )

        with pytest.raises(ChildPytestError) as raised:
            run_child_pytest(
                ["-q", "test_hang.py"],
                cwd=tmp_path,
                tmp_path=tmp_path,
                timeout=scaled_seconds(_HANG_BASE_SECONDS),
            )

        message = str(raised.value)
        assert "timed out" in message
        assert "test_hangs_inside_the_test" in message

    def test_a_hang_after_the_summary(self, tmp_path: Path) -> None:
        """The N531 shape: every test passed, then the process did not exit."""
        _write(
            tmp_path / "conftest.py",
            """
            import atexit
            import time


            def _hang_at_exit():
                time.sleep(600)


            atexit.register(_hang_at_exit)
            """,
        )
        _write(tmp_path / "test_ok.py", "def test_ok():\n    pass\n")

        with pytest.raises(ChildPytestError) as raised:
            run_child_pytest(
                ["-q", "test_ok.py"],
                cwd=tmp_path,
                tmp_path=tmp_path,
                timeout=scaled_seconds(_HANG_BASE_SECONDS),
            )

        message = str(raised.value)
        assert "1 passed" in message
        assert "_hang_at_exit" in message
