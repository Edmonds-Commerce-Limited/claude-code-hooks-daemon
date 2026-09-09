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
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
        "#!/bin/bash\n"
        f'printf "%s" "{stderr}" >&2\n'
        f'echo "{answer}"\n'
        f"exit {exit_code}\n"
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

    def test_the_resolved_interpreter_exists_and_is_executable(self) -> None:
        resolved = llm_qa.resolve_venv_python(PROJECT_ROOT)
        assert resolved.is_file(), f"resolved interpreter does not exist: {resolved}"
        assert os.access(resolved, os.X_OK), f"resolved interpreter is not executable: {resolved}"

    def test_the_module_constant_agrees_with_the_resolver(self) -> None:
        """`TOOL_REGISTRY` is built at import, so the constant is what runs."""
        assert llm_qa.VENV_PYTHON == llm_qa.resolve_venv_python(PROJECT_ROOT)
