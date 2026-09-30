"""`_resolve_python_cmd` reports the resolver's failure, not success (ledger N277).

The function ended with ``if PYTHON_CMD="$(resolve_venv_python ...)"; then return 0; fi``
followed by ``local rv=$?``. An ``if`` with no ``else`` whose condition fails leaves
``$?`` at 0, so ``rv`` was always 0: a failed resolve returned success with
``PYTHON_CMD`` empty, and any caller trusting the status went on to run an empty
interpreter.

The existing resolver tests only reach the library-missing ``return 5`` branch. These
reach the other one, with the canonical library present and its resolver failing.
"""

from __future__ import annotations

import subprocess  # nosec B404 - runs the trusted system `bash`
from pathlib import Path
from typing import Final

from tests.integration.test_init_sh_venv_resolution import _extract_resolver

_FAILURE_STATUS: Final[int] = 7
_TIMEOUT_SECONDS: Final[int] = 30


def _root_whose_resolver_fails(tmp_path: Path, status: int) -> Path:
    """A daemon root whose canonical library is present but cannot resolve a venv."""
    root = tmp_path / "project"
    lib_dir = root / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "resolve_venv.sh").write_text(
        f"resolve_venv_python() {{ return {status}; }}\n", encoding="utf-8"
    )
    return root


def _run(tmp_path: Path, root: Path) -> subprocess.CompletedProcess[str]:
    helper = _extract_resolver(tmp_path)
    return subprocess.run(  # nosec B603 - fixed argv, no shell, trusted input
        [
            "bash",
            "-c",
            f'source "{helper}"\n'
            "rc=0\n"
            "_resolve_python_cmd || rc=$?\n"
            'echo "rc=$rc python_cmd=[$PYTHON_CMD]"',
        ],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env={"PATH": "/usr/bin:/bin", "HOOKS_DAEMON_ROOT_DIR": str(root)},
        check=False,
    )


class TestAFailedResolveIsAFailure:
    def test_the_resolvers_status_is_returned(self, tmp_path: Path) -> None:
        result = _run(tmp_path, _root_whose_resolver_fails(tmp_path, _FAILURE_STATUS))
        assert f"rc={_FAILURE_STATUS} python_cmd=[]" in result.stdout, result.stderr

    def test_the_interpreter_is_left_empty(self, tmp_path: Path) -> None:
        result = _run(tmp_path, _root_whose_resolver_fails(tmp_path, _FAILURE_STATUS))
        assert "python_cmd=[]" in result.stdout, result.stderr

    def test_a_successful_resolve_still_returns_zero_with_the_interpreter(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "project"
        lib_dir = root / "scripts" / "lib"
        lib_dir.mkdir(parents=True)
        (lib_dir / "resolve_venv.sh").write_text(
            "resolve_venv_python() { echo /some/venv/bin/python; }\n", encoding="utf-8"
        )
        result = _run(tmp_path, root)
        assert "rc=0 python_cmd=[/some/venv/bin/python]" in result.stdout, result.stderr
