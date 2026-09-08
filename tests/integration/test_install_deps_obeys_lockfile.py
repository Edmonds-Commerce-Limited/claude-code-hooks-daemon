"""``install_deps`` must provision the QA venv from ``uv.lock`` (Plan 00346).

This repository commits a lockfile and CI-gates it with ``uv lock --check``, and
``CONTRIBUTING.md`` describes it as one of the files ``scripts/qa/`` uses. It was
not: ``install_deps`` ran ``pip install -e ".[dev]"``, which never reads the lock
and resolves ``pyproject.toml``'s lower bounds against PyPI. The measured result
was two venvs with two toolchains in one checkout, the one running the tests
being off-lock by a whole major version of mypy.

``.pre-commit-config.yaml``'s header documents the identical failure from the
other direction -- mirror-repo pins as "a SECOND version source that drifts from
uv.lock", drifting for "two years of silent rot" -- and resolves it by deleting
the second source rather than synchronising it. These tests hold that resolution
in place for the provisioning path.

**Two fixture details are load-bearing, and both were found by a vacuous pass.**

The stub installers go on ``PATH`` only AFTER ``venv-include.bash`` is sourced.
Venv resolution shells out through ``scripts/lib/resolve_venv.sh``, and a stub
``uv`` visible during that step breaks resolution outright -- ``VENV_DIR`` came
back EMPTY, so ``VENV_PIP`` became ``/bin/pip``, the system pip ran, and the
assertion that pip had not resolved the dev extra passed while testing nothing.

The fake venv's ``bin/python3`` is a SYMLINK to the running interpreter, not an
empty file. The resolver validates the interpreter before honouring
``HOOKS_DAEMON_VENV_PATH``, so a touched placeholder is silently rejected and
resolution falls through to the real checkout's venv.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VENV_INCLUDE: Final[Path] = REPO_ROOT / "scripts" / "venv-include.bash"
CANONICAL_LIB: Final[Path] = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
PYTHON_DISCOVERY_LIB: Final[Path] = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"
PATHS_SSOT: Final[Path] = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"

#: Long enough for a stubbed run (no resolution, no downloads), short enough
#: that a hang fails the suite rather than stalling it.
_TIMEOUT_SECONDS: Final[int] = 120


def _stub(path: Path, log: Path) -> None:
    """Write an executable that records its argv and succeeds."""
    path.write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> "{log}"\nexit 0\n')
    path.chmod(0o755)


def _setup_fake_project(tmp_path: Path) -> Path:
    """A minimal tree `venv-include.bash` can be sourced from.

    Mirrors ``test_venv_include_resolution.py``'s helper: the script computes
    ``PROJECT_ROOT`` as its own parent's parent, so it has to be reached at
    ``{project}/scripts/venv-include.bash`` for the isolation to hold.
    """
    project = tmp_path / "project"
    (project / "scripts" / "lib").mkdir(parents=True)
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    (project / "scripts" / "lib" / "resolve_venv.sh").symlink_to(CANONICAL_LIB)
    (project / "scripts" / "lib" / "python_discovery.sh").symlink_to(PYTHON_DISCOVERY_LIB)
    ssot_parent = project / "src" / "claude_code_hooks_daemon" / "daemon"
    ssot_parent.mkdir(parents=True)
    (ssot_parent / "paths.py").symlink_to(PATHS_SSOT)
    return project


def _run_install_deps(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Call the real ``install_deps`` with stubbed installers."""
    project = _setup_fake_project(tmp_path)

    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python3").symlink_to(sys.executable)

    pip_log = tmp_path / "pip.log"
    uv_log = tmp_path / "uv.log"
    _stub(venv_dir / "bin" / "pip", pip_log)

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    _stub(stub_bin / "uv", uv_log)

    env = os.environ.copy()
    env["HOOKS_DAEMON_VENV_PATH"] = str(venv_dir)
    env["HOOKS_DAEMON_PYTHON"] = sys.executable

    script = (
        f'source "{project}/scripts/venv-include.bash" >/dev/null 2>&1\n'
        # Only now: a stub uv visible during sourcing breaks venv resolution.
        f'export PATH="{stub_bin}:$PATH"\n'
        "install_deps\n"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(project),
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    return result, uv_log, pip_log


class TestTheFixtureIsNotVacuous:
    def test_the_stub_venv_is_the_one_resolved(self, tmp_path: Path) -> None:
        """Guards every assertion below from passing on an empty ``VENV_DIR``.

        Without this, a resolution failure makes ``VENV_PIP`` the SYSTEM pip:
        the stub is never called, its log never appears, and "pip did not
        resolve the dev extra" passes for the worst possible reason.
        """
        project = _setup_fake_project(tmp_path)
        venv_dir = tmp_path / "venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python3").symlink_to(sys.executable)

        env = os.environ.copy()
        env["HOOKS_DAEMON_VENV_PATH"] = str(venv_dir)
        env["HOOKS_DAEMON_PYTHON"] = sys.executable
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{project}/scripts/venv-include.bash" >/dev/null 2>&1; '
                'echo "$VENV_DIR"',
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(project),
            timeout=_TIMEOUT_SECONDS,
            check=True,
        )
        assert result.stdout.strip() == str(venv_dir), (
            "the fake venv was not the resolved one, so the install assertions "
            f"below would exercise something else entirely: {result.stdout!r}"
        )


class TestInstallDepsUsesTheLockfile:
    def test_the_lockfile_is_what_gets_installed(self, tmp_path: Path) -> None:
        """A provisioning run must go through uv against the committed lock.

        Asserting on ``--frozen`` specifically: a plain ``uv sync`` UPDATES the
        lock to satisfy pyproject when the two disagree, which re-resolves
        against PyPI and reintroduces exactly the drift this removes. The point
        is to install what the lock already says, not to make the lock say
        whatever is newest.
        """
        result, uv_log, _pip_log = _run_install_deps(tmp_path)

        assert uv_log.exists(), (
            "install_deps never invoked uv, so it cannot have consulted "
            f"uv.lock. stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        invocation = uv_log.read_text()
        assert "sync" in invocation, f"uv was called but not to sync: {invocation!r}"
        assert "--frozen" in invocation, (
            "uv sync ran without --frozen, so a pyproject/lock disagreement "
            f"would silently re-resolve against PyPI: {invocation!r}"
        )

    def test_pip_does_not_resolve_the_dev_extra(self, tmp_path: Path) -> None:
        """The bypass itself: ``pip install -e '.[dev]'`` ignores the lockfile.

        Separate from the test above because the two fail independently --
        adding a uv call while leaving the pip call in place would satisfy the
        first assertion and change nothing, since the pip resolution is still
        what lands in the venv.
        """
        result, _uv_log, pip_log = _run_install_deps(tmp_path)

        invocations = pip_log.read_text() if pip_log.exists() else ""
        assert "[dev]" not in invocations, (
            "install_deps still resolves the dev extra through pip, which never "
            f"reads uv.lock: {invocations!r}. stderr={result.stderr!r}"
        )
