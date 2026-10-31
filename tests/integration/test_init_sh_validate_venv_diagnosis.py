"""Plan 00555 Task 2.4: init.sh's start-failure message carries the diagnosis.

``validate_venv`` used to say "Venv may be broken ... Run: uv sync". It now
prints the interpreter version, the ``pyvenv.cfg`` version, whether the venv's
site-packages is on ``sys.path``, and the one fix (``bin/hooks-daemon repair``),
produced by ``paths.py diagnose-venv`` which needs no importable daemon.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
PATHS_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1)


def _function_text(text: str, name: str) -> str:
    """The brace-balanced source of shell function ``name`` in ``text``."""
    start = text.index(f"{name}() {{")
    depth = 0
    for index in range(text.index("{", start), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise RuntimeError(f"unbalanced braces in {name}")


def _drifted_root(tmp_path: Path) -> tuple[Path, Path]:
    """A daemon root with one drifted venv; returns (root, venv python)."""
    root = tmp_path / "root"
    ssot = root / "src" / "claude_code_hooks_daemon" / "daemon"
    ssot.mkdir(parents=True)
    (ssot / "paths.py").symlink_to(PATHS_PY)
    venv = root / "untracked" / "venv-drifted"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.symlink_to(os.path.realpath(sys.executable))
    (venv / "pyvenv.cfg").write_text(f"version_info = {_OTHER[0]}.{_OTHER[1]}.5\n")
    (venv / "lib" / f"python{_OTHER[0]}.{_OTHER[1]}" / "site-packages").mkdir(parents=True)
    return root, python


def _run_validate(tmp_path: Path, root: Path, python_cmd: str) -> str:
    text = INIT_SH.read_text()
    helper = tmp_path / "helper.sh"
    helper.write_text(
        "#!/bin/bash\n"
        + _function_text(text, "_venv_start_diagnosis")
        + "\n"
        + _function_text(text, "validate_venv")
        + "\n"
    )
    env = {**os.environ, "HOOKS_DAEMON_ROOT_DIR": str(root), "PYTHON_CMD": python_cmd}
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{helper}"; validate_venv; echo "rc=$?"; printf "%s" "$VENV_ERROR"',
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert "rc=1" in result.stdout
    return result.stdout


def test_import_failure_message_carries_the_diagnosis_and_not_uv_sync(tmp_path: Path) -> None:
    root, python = _drifted_root(tmp_path)
    out = _run_validate(tmp_path, root, str(python))
    assert f"interpreter version: {_RUNNING[0]}.{_RUNNING[1]}" in out
    assert f"pyvenv.cfg version_info: {_OTHER[0]}.{_OTHER[1]}" in out
    assert "site-packages on sys.path: no" in out
    assert f"{root}/bin/hooks-daemon repair" in out
    assert "uv sync" not in out


def test_missing_interpreter_message_names_repair_not_uv_sync(tmp_path: Path) -> None:
    root, _ = _drifted_root(tmp_path)
    out = _run_validate(tmp_path, root, str(root / "untracked" / "gone" / "bin" / "python"))
    assert f"{root}/bin/hooks-daemon repair" in out
    assert "uv sync" not in out
