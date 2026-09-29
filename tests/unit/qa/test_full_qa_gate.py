"""The pytest-side sink of the host-wide full-QA lock (Plan 00463 round 9).

Each test here REALLY EXECUTES a pytest subprocess (`subprocess.run` of a
real `python -m pytest` invocation, including through a bash/python launcher
wrapper) against a small fixture suite, with the plugin's own real threshold —
proving the mechanism closes the evasion class regardless of what LAUNCHED
the pytest process, rather than asserting against the function in isolation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.qa.full_qa_gate import (
    WHOLE_SUITE_FRACTION,
    whole_suite_refusal_message,
)
from claude_code_hooks_daemon.qa.full_qa_lock import acquire_full_qa_lock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"


def _init_repo(root: Path) -> None:
    env = {**os.environ, "HOME": str(root)}
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        env[name] = "t"
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        env[name] = "t@t"
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=root, check=True, env=env)


def _write_fixture_suite(root: Path, file_count: int) -> None:
    """A tiny real repo + real test tree, so the total is naturally small."""
    _init_repo(root)
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "conftest.py").write_text(
        # Review 10 B1: the SAME re-export shape as the real tests/conftest.py
        # -- `pytest_plugins = [...]` registers the daemon's OWN module as
        # the plugin (anchoring on its `qa/` source directory, not this
        # fixture's tests dir), which `_gate_anchor` would find but count
        # zero real test files under, refusing every run. Importing the
        # function makes THIS conftest.py the plugin pytest registers, so
        # its own directory is the anchor -- exactly the production shape.
        "from claude_code_hooks_daemon.qa.full_qa_gate import pytest_collection_modifyitems\n"
        "__all__ = ['pytest_collection_modifyitems']\n"
    )
    for i in range(file_count):
        (tests_dir / f"test_f{i}.py").write_text(
            f"def test_ok_{i}() -> None:\n    assert {i} == {i}\n"
        )


def _run_pytest_subprocess(
    root: Path, args: list[str], *, extra_fds: tuple[int, ...] = ()
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        pass_fds=extra_fds,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )


class TestThreshold:
    def test_quarter_is_the_configured_fraction(self) -> None:
        """Pinned so a silent widening (e.g. to 0.9) is a diff, not a surprise."""
        assert WHOLE_SUITE_FRACTION == pytest.approx(0.25)

    def test_refusal_message_names_the_lock_and_the_canonical_entrypoints(self) -> None:
        message = whole_suite_refusal_message(3, 4)
        assert "full-QA lock" in message
        assert "run_tests.sh" in message


class TestSmallSelectionRunsNormally:
    def test_a_single_file_of_four_is_under_threshold_and_runs(self, tmp_path: Path) -> None:
        _write_fixture_suite(tmp_path, file_count=4)
        result = _run_pytest_subprocess(tmp_path, ["tests/test_f0.py"])
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" not in result.stdout


class TestWholeSuiteSizedRunIsRefusedWithoutTheLock:
    """The sink closes the evasion class: it does not matter HOW pytest was
    launched -- only whether the lock is held when it collects."""

    def test_bare_pytest_over_threshold_is_refused(self, tmp_path: Path) -> None:
        _write_fixture_suite(tmp_path, file_count=4)
        result = _run_pytest_subprocess(tmp_path, ["tests/"])
        assert result.returncode == 1
        assert "REFUSED" in result.stdout
        assert "full-QA lock" in result.stdout

    def test_a_bash_wrapper_invoking_pytest_is_still_refused(self, tmp_path: Path) -> None:
        """Family M6/B1 shape: an indirect launcher, not a bare pytest call."""
        _write_fixture_suite(tmp_path, file_count=4)
        wrapper = tmp_path / "run.sh"
        wrapper.write_text(f"#!/bin/bash\ncd {tmp_path}\n{sys.executable} -m pytest tests/\n")
        wrapper.chmod(0o755)
        result = subprocess.run(
            ["bash", str(wrapper)],
            env={**os.environ, "PYTHONPATH": str(SRC_ROOT)},
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_LONG,
            check=False,
        )
        assert result.returncode == 1
        assert "REFUSED" in result.stdout, result.stdout + result.stderr

    def test_a_python_c_exec_wrapper_invoking_pytest_is_still_refused(self, tmp_path: Path) -> None:
        """Family M3/M4 shape: code that reaches pytest via exec/subprocess,
        not a direct `pytest` argv -- the handler cannot read every such
        wrapper, but the sink does not need to: it only sees the real
        pytest process this eventually spawns."""
        _write_fixture_suite(tmp_path, file_count=4)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import subprocess, sys; "
                f"sys.exit(subprocess.run([sys.executable, '-m', 'pytest', 'tests/'], "
                f"cwd={str(tmp_path)!r}).returncode)",
            ],
            env={**os.environ, "PYTHONPATH": str(SRC_ROOT)},
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_LONG,
            check=False,
        )
        assert result.returncode == 1

    def test_rootdir_pointed_at_an_empty_directory_is_still_refused(self, tmp_path: Path) -> None:
        """Review 10 B1: `--rootdir` repoints `config.rootpath`, but never
        where conftest.py is discovered from -- the count must anchor on the
        conftest's own directory, not the caller-controlled rootdir."""
        _write_fixture_suite(tmp_path, file_count=4)
        empty = tmp_path.parent / f"{tmp_path.name}-empty"
        empty.mkdir()
        result = _run_pytest_subprocess(tmp_path, ["-q", f"--rootdir={empty}", "tests/"])
        assert result.returncode == 1
        assert "REFUSED" in result.stdout, result.stdout + result.stderr

    def test_config_file_dev_null_with_empty_rootdir_is_still_refused(self, tmp_path: Path) -> None:
        """Review 10 B1, the D2 composite shape."""
        _write_fixture_suite(tmp_path, file_count=4)
        empty = tmp_path.parent / f"{tmp_path.name}-empty2"
        empty.mkdir()
        result = _run_pytest_subprocess(
            tmp_path, ["-q", "-c", "/dev/null", f"--rootdir={empty}", "tests/"]
        )
        assert result.returncode == 1
        assert "REFUSED" in result.stdout, result.stdout + result.stderr

    def test_k_selecting_one_test_is_not_refused(self, tmp_path: Path) -> None:
        """Review 10 m2: `-k` deselects AFTER this hook's default ordering
        runs, so the file count must be taken post-deselection
        (`trylast=True`) or a single selected test is wrongly refused."""
        _write_fixture_suite(tmp_path, file_count=4)
        result = _run_pytest_subprocess(tmp_path, ["-q", "-k", "test_ok_0", "tests/"])
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" not in result.stdout


class TestWholeSuiteSizedRunSucceedsWithTheLock:
    def test_holding_the_lock_permits_the_same_run_that_was_refused(self, tmp_path: Path) -> None:
        _write_fixture_suite(tmp_path, file_count=4)
        with acquire_full_qa_lock(tmp_path) as fd:
            os.set_inheritable(fd, True)
            result = _run_pytest_subprocess(tmp_path, ["tests/"], extra_fds=(fd,))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" not in result.stdout


_FORCED_PLUGIN_ARGS: list[str] = ["-p", "claude_code_hooks_daemon_full_qa_gate_loader"]


class TestNoconftestNoLongerDropsTheSink:
    """Round 10 M1: `-p claude_code_hooks_daemon_full_qa_gate_loader` in this
    project's own `addopts` is the production shape being proven here --
    the fixture suite has no `pyproject.toml` of its own, so it is passed
    explicitly on the command line, exactly as `addopts` would inject it."""

    def test_noconftest_alone_evades_the_gate_today(self, tmp_path: Path) -> None:
        """Baseline: without the forced plugin, `--noconftest` drops the
        sink entirely and the whole-suite-sized run is never refused."""
        _write_fixture_suite(tmp_path, file_count=4)
        result = _run_pytest_subprocess(tmp_path, ["--noconftest", "tests/"])
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" not in result.stdout

    def test_noconftest_with_the_forced_plugin_is_refused(self, tmp_path: Path) -> None:
        """The RED case this round closes: `--noconftest` can no longer
        drop the sink when it is also force-loaded via `-p`."""
        _write_fixture_suite(tmp_path, file_count=4)
        result = _run_pytest_subprocess(tmp_path, ["--noconftest", *_FORCED_PLUGIN_ARGS, "tests/"])
        assert result.returncode == 1
        assert "REFUSED" in result.stdout, result.stdout + result.stderr


class TestDoubleRegistrationIsANoOp:
    """When a project's own conftest.py imports the hook AND `addopts`
    force-loads the same module via `-p`, both plugin objects carry the
    hook -- the conftest-registered anchor must win cleanly rather than
    this module's own (test-file-less) source directory."""

    def test_under_threshold_selection_still_runs_normally(self, tmp_path: Path) -> None:
        _write_fixture_suite(tmp_path, file_count=4)
        result = _run_pytest_subprocess(tmp_path, [*_FORCED_PLUGIN_ARGS, "tests/test_f0.py"])
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" not in result.stdout
        # The conftest imported the sink first; the loader must not then ask
        # pytest to rewrite an already-imported module.
        assert "PytestAssertRewriteWarning" not in result.stdout + result.stderr

    def test_whole_suite_selection_is_refused_with_the_real_percentage(
        self, tmp_path: Path
    ) -> None:
        """Must show the ordinary `whole_suite_refusal_message` (naming the
        real N of M files) -- not the anchor-could-not-be-found message,
        which is what a wrong (self) anchor pick would produce."""
        _write_fixture_suite(tmp_path, file_count=4)
        result = _run_pytest_subprocess(tmp_path, [*_FORCED_PLUGIN_ARGS, "tests/"])
        assert result.returncode == 1
        assert "4 of 4 test files" in result.stdout, result.stdout + result.stderr
        assert "could not establish" not in result.stdout


class TestRunCollectedOutsideTheSuiteIsJudgedOnItsOwnSize:
    """CI's `pytest .claude/project-handlers`: no `tests/conftest.py` is
    loaded, so only the forced plugin registers the hook and its own source
    directory holds no test files. The suite size then comes from the
    invocation directory's `tests/`, which no pytest flag can move."""

    @staticmethod
    def _write_outside_tests(root: Path, count: int) -> None:
        outside = root / "handlers"
        outside.mkdir()
        for i in range(count):
            (outside / f"test_h{i}.py").write_text(
                f"def test_h_{i}() -> None:\n    assert {i} == {i}\n"
            )

    def test_a_small_run_outside_tests_is_allowed(self, tmp_path: Path) -> None:
        _write_fixture_suite(tmp_path, file_count=8)
        self._write_outside_tests(tmp_path, count=1)
        result = _run_pytest_subprocess(tmp_path, [*_FORCED_PLUGIN_ARGS, "handlers"])
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" not in result.stdout

    def test_a_whole_suite_sized_run_outside_tests_is_still_refused(self, tmp_path: Path) -> None:
        _write_fixture_suite(tmp_path, file_count=4)
        self._write_outside_tests(tmp_path, count=4)
        result = _run_pytest_subprocess(tmp_path, [*_FORCED_PLUGIN_ARGS, "handlers"])
        assert result.returncode == 1
        assert "REFUSED" in result.stdout, result.stdout + result.stderr

    def test_with_no_tests_directory_at_all_it_still_refuses(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        self._write_outside_tests(tmp_path, count=1)
        result = _run_pytest_subprocess(tmp_path, [*_FORCED_PLUGIN_ARGS, "handlers"])
        assert result.returncode == 1
        assert "could not establish" in result.stdout, result.stdout + result.stderr

    def test_rootdir_pointed_away_cannot_shrink_the_suite(self, tmp_path: Path) -> None:
        _write_fixture_suite(tmp_path, file_count=4)
        self._write_outside_tests(tmp_path, count=4)
        empty = tmp_path.parent / f"{tmp_path.name}-empty3"
        empty.mkdir()
        result = _run_pytest_subprocess(
            tmp_path, [*_FORCED_PLUGIN_ARGS, f"--rootdir={empty}", "handlers"]
        )
        assert result.returncode == 1
        assert "REFUSED" in result.stdout, result.stdout + result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
