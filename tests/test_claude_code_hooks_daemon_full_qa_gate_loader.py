"""The full-QA sink is force-loaded without importing the package early (Plan 00463).

``addopts`` must force-load the sink so ``--noconftest`` cannot drop it (round
10 M1), but a ``-p`` plugin is imported while pytest parses its arguments,
before pytest-cov starts. Naming ``claude_code_hooks_daemon.qa.full_qa_gate``
there ran the package ``__init__`` unmeasured (00466 N110 round 3). The
top-level loader is what ``-p`` names instead: importing it imports nothing
from the package, and it registers the sink in ``pytest_configure``, after
coverage has started.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout

LOADER = "claude_code_hooks_daemon_full_qa_gate_loader"
PACKAGE = "claude_code_hooks_daemon"
GATE = f"{PACKAGE}.qa.full_qa_gate"


def _forced_plugins(config: pytest.Config) -> list[str]:
    addopts: list[str] = config.getini("addopts")
    return [addopts[index + 1] for index, arg in enumerate(addopts) if arg == "-p"]


class TestTheLoaderImportsNothingEarly:
    def test_importing_the_loader_imports_no_package_module(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys, {LOADER}\n"
                f"print(sorted(m for m in sys.modules if m.split('.')[0] == {PACKAGE!r}))",
            ],
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_LONG,
            check=True,
        )

        assert completed.stdout.strip() == "[]"


def _run_one_test_without_conftest(tmp_path: Path, *plugin_args: str) -> str:
    (tmp_path / "test_one.py").write_text("def test_one() -> None:\n    assert True\n")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--noconftest", *plugin_args, "test_one.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    return completed.stdout + completed.stderr


class TestTheLoaderRegistersTheSink:
    def test_the_sink_is_active_under_noconftest(self, tmp_path: Path) -> None:
        """With no conftest the sink anchors on its own test-less directory and refuses."""
        assert "REFUSED" in _run_one_test_without_conftest(tmp_path, "-p", LOADER)

    def test_blocking_the_sink_by_name_still_unloads_it(self, tmp_path: Path) -> None:
        """`hooks-daemon test-project-handlers` relies on `-p no:<sink>`."""
        output = _run_one_test_without_conftest(tmp_path, "-p", LOADER, "-p", f"no:{GATE}")
        assert "REFUSED" not in output
        assert "1 passed" in output, output

    def test_naming_the_sink_directly_as_well_does_not_register_it_twice(
        self, tmp_path: Path
    ) -> None:
        output = _run_one_test_without_conftest(tmp_path, "-p", GATE, "-p", LOADER)
        assert "already registered" not in output
        assert "REFUSED" in output, output


class TestAddoptsForceLoadsOnlyTheLoader:
    def test_addopts_names_the_loader(self, pytestconfig: pytest.Config) -> None:
        assert LOADER in _forced_plugins(pytestconfig)

    def test_addopts_names_no_module_inside_the_package(self, pytestconfig: pytest.Config) -> None:
        inside = [name for name in _forced_plugins(pytestconfig) if name.startswith(f"{PACKAGE}.")]
        assert inside == []

    def test_the_loader_registered_the_sink_in_this_run(self, pytestconfig: pytest.Config) -> None:
        assert pytestconfig.pluginmanager.get_plugin(GATE) is not None
