"""Locating a real interpreter below the declared minimum, for entry-point tests.

``python3.N`` on PATH wins; otherwise ``uv python find`` (which resolves one
that ``uv python install N`` fetched). Tests skip when neither exists.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

#: Interpreters below the minimum that the entry-point tests run under.
OLD_VERSIONS = ("3.8", "3.9")


def find_old_python(version: str) -> str | None:
    """Path to a ``version`` interpreter, or None when this host has none."""
    on_path = shutil.which(f"python{version}")
    if on_path:
        return on_path
    uv = shutil.which("uv")
    if uv is None:
        return None
    found = subprocess.run(
        [uv, "python", "find", "--no-project", version],
        capture_output=True,
        text=True,
        check=False,
        cwd="/",
    )
    path = found.stdout.strip()
    return path if found.returncode == 0 and path else None


def old_python_or_skip(version: str) -> str:
    """Path to a ``version`` interpreter, skipping the test when there is none."""
    path = find_old_python(version)
    if path is None:
        pytest.skip(f"no Python {version} interpreter available")
    return path
