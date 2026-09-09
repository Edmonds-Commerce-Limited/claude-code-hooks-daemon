"""The QA runner must find the interpreter the same way everything else does.

`llm_qa.py` hardcoded `untracked/venv/bin/python`, a path the project's own
venv layout stopped creating at v3.7.0: `venv-include.bash` REFUSES to create
anything there, and the canonical resolver (`scripts/lib/resolve_venv.sh`)
looks for the fingerprint-keyed `untracked/venv-<fingerprint>/`. The main
checkout only satisfied the hardcoded path because a symlink happened to sit
at it, so every fresh worktree needed that symlink made by hand before
`./scripts/qa/llm_qa.py all` could start at all (Plan 00364 Task 5.5).

Resolution order pinned here: the resolver is authoritative whenever it is
present. The legacy path is consulted ONLY when the resolver is absent (a
partial deployment), never as a rescue for a resolver that ran and failed —
that would reintroduce the silent fallback whose removal is the whole point
of the fingerprint layout. Either way a failure names both places that were
tried, because "cannot find python" with no path in it is the report that
cost a previous agent an hour.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Captured at import, BEFORE the autouse `isolate_daemon_path_overrides`
# fixture unsets them for every test. `TestThisCheckoutResolves` asks whether
# the runner resolves an interpreter when invoked from the shell it was
# invoked from, and on CI that shell supplies the venv (`.venv`, via
# HOOKS_DAEMON_VENV_PATH) — the fingerprint glob cannot see it. Restoring the
# ambient values is the honest question; asking with them stripped is not.
_AMBIENT_VENV_ENV = {
    key: value
    for key, value in os.environ.items()
    if key in ("HOOKS_DAEMON_VENV_PATH", "HOOKS_DAEMON_PYTHON")
}


def _load_llm_qa() -> Any:
    """Import `scripts/qa/llm_qa.py`, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_venv_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()


def _fake_resolver(root: Path, *, answer: str, exit_code: int = 0, stderr: str = "") -> Path:
    """Write a stand-in `scripts/lib/resolve_venv.sh` for `root`."""
    resolver = root / "scripts" / "lib" / "resolve_venv.sh"
    resolver.parent.mkdir(parents=True, exist_ok=True)
    resolver.write_text(
        f'#!/bin/bash\nprintf "%s" "{stderr}" >&2\necho "{answer}"\nexit {exit_code}\n'
    )
    resolver.chmod(resolver.stat().st_mode | stat.S_IXUSR)
    return resolver


def _legacy_python(root: Path) -> Path:
    legacy = root / "untracked" / "venv" / "bin" / "python"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("#!/bin/bash\nexit 0\n")
    legacy.chmod(legacy.stat().st_mode | stat.S_IXUSR)
    return legacy


class TestTheResolverIsAuthoritative:
    def test_its_answer_is_used(self, tmp_path: Path) -> None:
        _fake_resolver(tmp_path, answer="/opt/venv-abc123/bin/python")
        assert llm_qa.resolve_venv_python(tmp_path) == Path("/opt/venv-abc123/bin/python")

    def test_its_answer_wins_over_a_legacy_path_that_also_exists(self, tmp_path: Path) -> None:
        """The main checkout has both; the fingerprint venv is the real one."""
        _fake_resolver(tmp_path, answer="/opt/venv-abc123/bin/python")
        _legacy_python(tmp_path)
        assert llm_qa.resolve_venv_python(tmp_path) == Path("/opt/venv-abc123/bin/python")

    def test_a_failing_resolver_is_an_error_not_a_fallback(self, tmp_path: Path) -> None:
        _fake_resolver(tmp_path, answer="", exit_code=5, stderr="no usable venv found")
        _legacy_python(tmp_path)
        with pytest.raises(llm_qa.VenvResolutionError) as excinfo:
            llm_qa.resolve_venv_python(tmp_path)
        message = str(excinfo.value)
        assert "resolve_venv.sh" in message
        assert "untracked/venv/bin/python" in message
        assert "no usable venv found" in message


class TestTheLegacyPathIsTheDeploymentGapFallback:
    def test_it_is_used_when_the_resolver_is_absent(self, tmp_path: Path) -> None:
        legacy = _legacy_python(tmp_path)
        assert llm_qa.resolve_venv_python(tmp_path) == legacy

    def test_neither_present_names_both_attempts(self, tmp_path: Path) -> None:
        with pytest.raises(llm_qa.VenvResolutionError) as excinfo:
            llm_qa.resolve_venv_python(tmp_path)
        message = str(excinfo.value)
        assert str(tmp_path / "scripts" / "lib" / "resolve_venv.sh") in message
        assert str(tmp_path / "untracked" / "venv" / "bin" / "python") in message


class TestThisCheckoutResolves:
    """The defect itself: a worktree has no `untracked/venv`, only `venv-*`."""

    @pytest.fixture(autouse=True)
    def _ambient_venv_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in _AMBIENT_VENV_ENV.items():
            monkeypatch.setenv(key, value)

    def test_the_resolved_interpreter_exists_and_is_executable(self) -> None:
        resolved = llm_qa.resolve_venv_python(PROJECT_ROOT)
        assert resolved.is_file(), f"resolved interpreter does not exist: {resolved}"
        assert os.access(resolved, os.X_OK), f"resolved interpreter is not executable: {resolved}"

    def test_the_interpreter_the_tools_run_under_is_the_resolvers(self) -> None:
        """`venv_python()` is what every `_python(...)` command runs under."""
        assert llm_qa.venv_python() == llm_qa.resolve_venv_python(PROJECT_ROOT)
        command = llm_qa.resolved_command(llm_qa.TOOL_REGISTRY["magic_values"])
        assert command[0] == str(llm_qa.venv_python())
        assert llm_qa.VENV_PYTHON_PLACEHOLDER not in command


class TestImportingTheRunnerNeedsNoInterpreter:
    """Importing `llm_qa` must not depend on the environment it is imported in.

    The interpreter was resolved at import and baked into `TOOL_REGISTRY`, so
    a test that imported the module to inspect the registry inherited the
    shell's venv resolution. On CI the venv is `.venv`, visible only through
    HOOKS_DAEMON_VENV_PATH, and the autouse fixture unsets that for every
    test: the import raised `SystemExit` and a wiring test failed for a reason
    that had nothing to do with wiring. Resolution now happens when a tool
    RUNS, and the failure is reported then, by the same message.
    """

    def test_the_import_runs_no_resolver(self) -> None:
        """A subprocess call during import would be the resolver; forbid all of them."""
        snippet = (
            "import subprocess\n"
            "def boom(*args, **kwargs):\n"
            "    raise AssertionError('resolver ran at import: %r' % (args,))\n"
            "subprocess.run = boom\n"
            "import llm_qa\n"
            "print(llm_qa.TOOL_REGISTRY['magic_values'].command[0])\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=PROJECT_ROOT / "scripts" / "qa",
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == llm_qa.VENV_PYTHON_PLACEHOLDER

    @pytest.fixture
    def unresolvable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        """A fresh module whose checkout has a resolver that fails."""
        _fake_resolver(tmp_path, answer="", exit_code=5, stderr="no usable venv found")
        module = _load_llm_qa()
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
        return module

    def test_resolution_fails_at_run_time_with_the_same_message(self, unresolvable: Any) -> None:
        with pytest.raises(unresolvable.VenvResolutionError) as excinfo:
            unresolvable.resolved_command(unresolvable.TOOL_REGISTRY["magic_values"])
        assert "resolve_venv.sh" in str(excinfo.value)
        assert "no usable venv found" in str(excinfo.value)

    def test_main_reports_it_before_running_anything(
        self, unresolvable: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", "magic_values"])
        assert unresolvable.main() == unresolvable.EXIT_FAILURE
        captured = capsys.readouterr()
        assert "llm_qa: no QA interpreter" in captured.err
        assert "QA:" not in captured.out, "no tool may have run"
