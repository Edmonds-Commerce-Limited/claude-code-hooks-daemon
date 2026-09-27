r"""A fingerprint venv must be built on the interpreter it was fingerprinted from.

Ledger 00466 N114. ``ensure_venv`` computes the venv's name from ``python3``
(``venv-<slug>-py311-<hash>`` when PATH's ``python3`` is 3.11), then asks
``create_venv_at_path`` to build it with ``HOOKS_DAEMON_PYTHON=python3``. That
bare name went straight to ``uv sync --python python3``, and uv reads a bare
``python3`` as a VERSION request ("any 3.x"), not as the executable on PATH.
So uv built the venv on its own preferred interpreter: measured in this
container, a ``py311`` venv came out as 3.12 (worktree n110) or 3.13
(worktrees n101 and n105). The daemon, and every QA run in the checkout, then
ran on a Python the venv's name denied.

Two properties are pinned:

- uv is handed the RESOLVED path of the requested interpreter, never a bare
  name it can reinterpret.
- The built venv's version is checked against the requested interpreter's,
  and a mismatch fails the build loudly instead of being used.

Stubs ``uv``, ``python3`` and ``stat`` on PATH, as
``test_venv_sh_sync_is_frozen.py`` does: what matters is what the function
asks uv for and what it does with the result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Final, NamedTuple

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VENV_SH: Final[Path] = REPO_ROOT / "scripts" / "install" / "venv.sh"
BASH: Final[str] = shutil.which("bash") or "/bin/bash"

_TIMEOUT_SECONDS: Final[int] = 30
_REQUESTED_VERSION: Final[str] = "3.11"


class _Run(NamedTuple):
    result: subprocess.CompletedProcess[str]
    uv_calls: list[str]
    stub_dir: Path


def _version_stub(path: Path, version: str) -> None:
    """An 'interpreter' that answers any `-c` probe with ``version``."""
    path.write_text(f"#!/bin/bash\nprintf '%s\\n' '{version}'\n")
    path.chmod(0o755)


def _run_create_venv(
    tmp_path: Path, *, requested: str = "python3", built_version: str = _REQUESTED_VERSION
) -> _Run:
    """Run ``create_venv_at_path`` the way ``_ensure_venv_build`` does.

    The stub ``uv`` builds a venv whose ``bin/python`` reports
    ``built_version``, standing in for uv choosing an interpreter.
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    (daemon_dir / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n')
    venv_path = daemon_dir / "untracked" / "venv-test-py311-00000000"

    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    uv_log = tmp_path / "uv_calls.log"
    uv_log.write_text("")
    built_python = tmp_path / "built-python"
    _version_stub(built_python, built_version)
    uv_stub = stub_dir / "uv"
    uv_stub.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        printf '%s\\n' "$*" >> "{uv_log}"
        if [ -n "${{UV_PROJECT_ENVIRONMENT:-}}" ]; then
            mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
            cp "{built_python}" "$UV_PROJECT_ENVIRONMENT/bin/python"
        fi
        exit 0
        """))
    uv_stub.chmod(0o755)
    _version_stub(stub_dir / "python3", _REQUESTED_VERSION)
    stat_stub = stub_dir / "stat"
    stat_stub.write_text("#!/bin/bash\nprintf '%s\\n' 'ext2/ext3'\nexit 0\n")
    stat_stub.chmod(0o755)

    # PATH is exported AFTER sourcing: venv.sh prepends the daemon's own tool
    # directory, which would otherwise shadow the stubs.
    harness = textwrap.dedent(f"""\
        set -euo pipefail
        . "{VENV_SH}"
        export PATH="{stub_dir}:$PATH"
        HOOKS_DAEMON_PYTHON="{requested}" create_venv_at_path "{daemon_dir}" "{venv_path}"
        """)
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env.pop("UV_LINK_MODE", None)
    env.pop("HOOKS_DAEMON_PYTHON", None)

    result = subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    calls = [line for line in uv_log.read_text().splitlines() if line.strip()]
    return _Run(result, calls, stub_dir)


def _python_arg(call: str) -> str:
    words = call.split()
    assert "--python" in words, f"uv was not told which interpreter to use: {call!r}"
    return words[words.index("--python") + 1]


class TestTheFixtureIsNotVacuous:
    def test_a_matching_build_succeeds_and_reaches_uv(self, tmp_path: Path) -> None:
        run = _run_create_venv(tmp_path)

        assert run.result.returncode == 0, (
            f"create_venv_at_path failed: stdout={run.result.stdout!r} "
            f"stderr={run.result.stderr!r}"
        )
        assert run.uv_calls, "the stub uv was never called"


class TestUvIsGivenTheResolvedInterpreter:
    def test_a_bare_name_is_resolved_to_the_executable_on_path(self, tmp_path: Path) -> None:
        """`--python python3` means "any 3.x" to uv, not PATH's python3."""
        run = _run_create_venv(tmp_path)

        syncs = [call for call in run.uv_calls if "sync" in call.split()]
        assert syncs, f"no uv sync recorded: {run.uv_calls!r}"
        for call in syncs:
            assert _python_arg(call) == str(run.stub_dir / "python3"), (
                "uv was handed the bare name instead of the interpreter the "
                f"fingerprint was computed from: {call!r}"
            )

    def test_an_interpreter_that_does_not_exist_fails_before_uv_runs(self, tmp_path: Path) -> None:
        run = _run_create_venv(tmp_path, requested="python3.99-not-installed")

        assert run.result.returncode != 0
        assert "python3.99-not-installed" in run.result.stderr + run.result.stdout
        assert not run.uv_calls, "uv must not be asked to pick an interpreter of its own"


class TestAVersionSwapFailsLoudly:
    def test_a_venv_built_on_another_version_is_refused(self, tmp_path: Path) -> None:
        run = _run_create_venv(tmp_path, built_version="3.13")

        output = run.result.stderr + run.result.stdout
        assert run.result.returncode != 0, (
            "a venv named for 3.11 but built on 3.13 was accepted: " f"{output!r}"
        )
        assert "3.13" in output and _REQUESTED_VERSION in output

    def test_the_refused_venv_is_not_left_for_the_resolver_to_find(self, tmp_path: Path) -> None:
        """resolve_venv.sh globs untracked/venv-*; a leftover would still be run."""
        _run_create_venv(tmp_path, built_version="3.13")

        assert not list((tmp_path / "daemon" / "untracked").glob("venv-*"))
