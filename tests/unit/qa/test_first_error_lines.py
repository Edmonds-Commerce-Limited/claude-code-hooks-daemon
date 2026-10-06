"""The QA tests stage names each failed or errored test's first error line (00466 N196).

The gate's summary named ten errored acceptance tests and nothing else: the
cause (no daemon was running) was only in the shard's raw log. The
``first_error_lines`` pytest plugin records the first line of every red
test's error as it happens, and the report attaches it to that test's record,
so the summary line for a failure says what went wrong.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, cast

import pytest

from claude_code_hooks_daemon.qa import first_error_lines
from claude_code_hooks_daemon.qa.first_error_lines import (
    OPTION,
    PLUGIN,
    attach_first_error_lines,
    first_error_line,
    read_first_error_lines,
)


class _Crash:
    def __init__(self, message: str) -> None:
        self.message = message


class _LongRepr:
    """The shape of a traceback longrepr: its crash carries the message."""

    def __init__(self, message: str) -> None:
        self.reprcrash = _Crash(message)

    def __str__(self) -> str:
        return "a whole traceback that is not the message"


class TestTheFirstErrorLine:
    def test_a_traceback_gives_its_crash_message_not_its_first_frame(self) -> None:
        longrepr = _LongRepr("AssertionError: 2 != 3\nassert 2 == 3")
        assert first_error_line(longrepr) == "AssertionError: 2 != 3"

    def test_a_string_longrepr_gives_its_first_non_blank_line(self) -> None:
        assert first_error_line("\n\n  Daemon not running  \nmore") == "Daemon not running"

    def test_an_empty_longrepr_gives_an_empty_line(self) -> None:
        assert first_error_line("") == ""
        assert first_error_line(None) == ""


class TestReadingTheRecords:
    def test_a_missing_file_has_no_lines(self, tmp_path: Path) -> None:
        assert read_first_error_lines(tmp_path / "never-written.jsonl") == {}

    def test_the_first_record_for_a_test_wins(self, tmp_path: Path) -> None:
        """A test that fails its call and then its teardown is named by the call."""
        path = tmp_path / "lines.jsonl"
        records = [
            {"nodeid": "t.py::a", "when": "call", "line": "first"},
            {"nodeid": "t.py::a", "when": "teardown", "line": "second"},
            {"nodeid": "t.py::b", "when": "setup", "line": "other"},
        ]
        path.write_text("\n".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

        assert read_first_error_lines(path) == {"t.py::a": "first", "t.py::b": "other"}

    def test_attaching_sets_a_reason_only_on_the_tests_that_have_one(self, tmp_path: Path) -> None:
        path = tmp_path / "lines.jsonl"
        path.write_text(
            json.dumps({"nodeid": "t.py::a", "when": "setup", "line": "why"}) + "\n",
            encoding="utf-8",
        )
        tests = [
            {"name": "t.py::a", "outcome": "failed"},
            {"name": "t.py::b", "outcome": "failed"},
        ]

        attach_first_error_lines(tests, path)

        assert tests == [
            {"name": "t.py::a", "outcome": "failed", "reason": "why"},
            {"name": "t.py::b", "outcome": "failed"},
        ]


class _Report:
    def __init__(self, *, failed: bool, longrepr: object) -> None:
        self.failed = failed
        self.nodeid = "t.py::a"
        self.when = "call"
        self.longrepr = longrepr


class _PluginManager:
    def __init__(self) -> None:
        # Any: the recorder class is private to the module under test.
        self.registered: list[Any] = []

    def register(self, plugin: object, name: str) -> None:
        self.registered.append(plugin)


class _Config:
    def __init__(self, target: str | None) -> None:
        self._target = target
        self.pluginmanager = _PluginManager()

    def getoption(self, name: str) -> str | None:
        return self._target


class TestTheHooksInProcess:
    def test_without_the_option_no_recorder_is_registered(self) -> None:
        config = _Config(None)
        first_error_lines.pytest_configure(cast("pytest.Config", config))
        assert config.pluginmanager.registered == []

    def test_the_recorder_writes_a_failed_phase_and_skips_a_passing_one(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "lines.jsonl"
        config = _Config(str(path))
        first_error_lines.pytest_configure(cast("pytest.Config", config))
        (recorder,) = config.pluginmanager.registered

        recorder.pytest_runtest_logreport(_Report(failed=False, longrepr=None))
        assert not path.exists()
        recorder.pytest_runtest_logreport(_Report(failed=True, longrepr=_LongRepr("Boom: x")))

        assert read_first_error_lines(path) == {"t.py::a": "Boom: x"}


class TestThePluginInARealRun:
    """The plugin is loaded by name in a project without this suite's conftest."""

    def test_every_failed_and_errored_test_is_recorded_and_nothing_else(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "test_sample.py").write_text(
            textwrap.dedent("""
                import pytest


                @pytest.fixture
                def broken():
                    raise RuntimeError("fixture exploded\\nsecond line")


                def test_fails():
                    assert 1 == 2, "one is not two"


                def test_errors(broken):
                    pass


                def test_passes():
                    pass


                def test_skips():
                    pytest.skip("not here")
                """).lstrip(),
            encoding="utf-8",
        )
        lines_path = tmp_path / "lines.jsonl"
        env = os.environ.copy()
        env.pop("PYTEST_ADDOPTS", None)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-p",
                PLUGIN,
                f"{OPTION}={lines_path}",
                f"--rootdir={tmp_path}",
                str(tmp_path),
            ],
            cwd=tmp_path,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1, f"{result.stdout}\n{result.stderr}"
        lines = read_first_error_lines(lines_path)
        assert lines == {
            "test_sample.py::test_fails": "AssertionError: one is not two",
            "test_sample.py::test_errors": "RuntimeError: fixture exploded",
        }

    def test_without_the_option_nothing_is_written(self, tmp_path: Path) -> None:
        (tmp_path / "test_sample.py").write_text("def test_fails():\n    assert False\n")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-p",
                PLUGIN,
                f"--rootdir={tmp_path}",
                str(tmp_path),
            ],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".jsonl") == []

    def test_the_plugin_name_is_this_module(self) -> None:
        assert PLUGIN == first_error_lines.__name__
