"""Locating a real interpreter below the declared minimum, for entry-point tests.

``python3.N`` on PATH wins; otherwise ``uv python find`` resolves one, and when
``uv`` has none it installs it (``uv python install N``, the call
``run_test_matrix.py`` already makes). A test skips only when ``uv`` itself is
absent, and the skip reason says so. A failed install is a test failure: a
standing gate must not pass by silently not running.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

#: Interpreters below the minimum that the entry-point tests run under.
OLD_VERSIONS = ("3.8", "3.9")

#: The oldest interpreter the stdlib-only forwarder snippets in ``init.sh`` must parse under.
FORWARDER_PYTHON_FLOOR = (3, 6)


class OldPythonProvisionError(RuntimeError):
    """``uv`` is present but could not provide the requested interpreter."""


def _uv_python(uv: str, action: str, version: str) -> subprocess.CompletedProcess[str]:
    args = [uv, "python", action]
    if action == "find":
        args.append("--no-project")
    args.append(version)
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd="/")


def find_old_python(version: str) -> str | None:
    """Path to a ``version`` interpreter; None only when neither PATH nor ``uv`` can look.

    Raises:
        OldPythonProvisionError: ``uv`` is present but could not install ``version``.
    """
    on_path = shutil.which(f"python{version}")
    if on_path:
        return on_path
    uv = shutil.which("uv")
    if uv is None:
        return None
    found = _uv_python(uv, "find", version)
    if found.returncode != 0 or not found.stdout.strip():
        installed = _uv_python(uv, "install", version)
        if installed.returncode != 0:
            raise OldPythonProvisionError(
                f"uv python install {version} failed (exit {installed.returncode}): "
                f"{installed.stderr.strip()}"
            )
        found = _uv_python(uv, "find", version)
    path = found.stdout.strip()
    if found.returncode != 0 or not path:
        raise OldPythonProvisionError(
            f"uv installed Python {version} but cannot find it: {found.stderr.strip()}"
        )
    return path


def old_python_or_skip(version: str) -> str:
    """Path to a ``version`` interpreter; skip when ``uv`` is absent, fail when it cannot install."""
    try:
        path = find_old_python(version)
    except OldPythonProvisionError as error:
        pytest.fail(f"Python {version} could not be provisioned: {error}")
    if path is None:
        pytest.skip(
            f"uv is not installed and there is no python{version} on PATH; "
            f"install uv (https://docs.astral.sh/uv/) so this test can provision Python {version}"
        )
    return path
