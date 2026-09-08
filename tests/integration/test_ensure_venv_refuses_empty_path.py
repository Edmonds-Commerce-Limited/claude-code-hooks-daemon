"""``ensure_venv`` must refuse an empty ``VENV_DIR`` instead of polluting the cwd.

Found by causing it. A test stubbed ``uv`` onto ``PATH`` before sourcing
``venv-include.bash``; that broke venv resolution, ``VENV_DIR`` came back empty,
and ``ensure_venv`` then did this:

    mkdir -p "$(dirname "")"      # -> mkdir -p .
    python3 -m venv ""            # -> creates a venv in the CURRENT directory
    [[ -f "${VENV_PYTHON}" ]]     # -> VENV_PYTHON is "/bin/python3", which
                                  #    exists on any Linux, so this PASSES

It reported ``✓ Created venv:`` with nothing after the colon and returned 0,
having written ``bin/``, ``lib/``, ``lib64``, ``include/`` and ``pyvenv.cfg``
into the repository root — alongside the tracked ``bin/hooks-daemon``.

Two things make this worse than a crash. The success check reads a path that is
guaranteed to exist when the variable is empty, so the failure authenticates
itself. And the damage lands wherever the caller happened to be standing, which
for a QA script is the checkout.

This mirrors the legacy-path refusal already in ``ensure_venv``: some venv
targets are not merely wrong but unsafe to create, and the guard belongs before
the ``mkdir``.
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

_TIMEOUT_SECONDS: Final[int] = 120

#: What `python3 -m venv .` drops into whatever directory it is pointed at.
_VENV_ARTEFACTS: Final[tuple[str, ...]] = ("pyvenv.cfg", "lib64", "include", "lib")


def _setup_fake_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "scripts" / "lib").mkdir(parents=True)
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    (project / "scripts" / "lib" / "resolve_venv.sh").symlink_to(CANONICAL_LIB)
    (project / "scripts" / "lib" / "python_discovery.sh").symlink_to(PYTHON_DISCOVERY_LIB)
    ssot_parent = project / "src" / "claude_code_hooks_daemon" / "daemon"
    ssot_parent.mkdir(parents=True)
    (ssot_parent / "paths.py").symlink_to(PATHS_SSOT)
    return project


def _call_ensure_venv_with_empty_dir(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Source the real script, blank ``VENV_DIR``, and call ``ensure_venv``.

    Assigning the variable directly reproduces the observed end state (an empty
    resolution) without needing to break the resolver, which is a separate
    concern with its own tests.
    """
    project = _setup_fake_project(tmp_path)
    cwd = tmp_path / "somewhere-else"
    cwd.mkdir()

    env = os.environ.copy()
    env["HOOKS_DAEMON_PYTHON"] = sys.executable
    env.pop("HOOKS_DAEMON_VENV_PATH", None)

    script = (
        f'source "{project}/scripts/venv-include.bash" >/dev/null 2>&1\n'
        'VENV_DIR=""\n'
        'VENV_PYTHON="/bin/python3"\n'
        "ensure_venv\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestEnsureVenvRefusesAnEmptyTarget:
    def test_it_fails_rather_than_reporting_success(self, tmp_path: Path) -> None:
        """An empty target is a resolution failure, and must read as one.

        The pre-fix behaviour returned 0: ``VENV_PYTHON`` was ``/bin/python3``,
        which exists, so the "did the venv get created" check passed on the
        system interpreter.
        """
        result = _call_ensure_venv_with_empty_dir(tmp_path)

        assert result.returncode != 0, (
            "ensure_venv reported success with an empty VENV_DIR — the check "
            "that is supposed to catch this reads /bin/python3, which exists. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_it_writes_nothing_into_the_working_directory(self, tmp_path: Path) -> None:
        """The damage this guard exists to prevent, asserted directly.

        Separate from the exit-code test because they fail independently: a
        guard placed AFTER the ``python3 -m venv`` would return non-zero while
        the directory had already been polluted.
        """
        result = _call_ensure_venv_with_empty_dir(tmp_path)
        cwd = tmp_path / "somewhere-else"

        strays = sorted(p.name for p in cwd.iterdir())
        assert not strays, (
            "ensure_venv created a venv in the current working directory. In "
            "the real checkout this lands beside tracked files: "
            f"{strays}. stderr={result.stderr!r}"
        )
        for artefact in _VENV_ARTEFACTS:
            assert not (cwd / artefact).exists(), f"{artefact} was written to the cwd"
