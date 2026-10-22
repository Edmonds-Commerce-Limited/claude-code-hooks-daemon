"""``scripts/debug_info.py`` refuses an old interpreter in one line (Plan 00546 Task 3.1).

Its shebang is ``python3``, and ``from datetime import UTC`` (3.11+) ran before
any guard, so an older ``python3`` died on an ImportError traceback. It now
calls the shared floor guard first.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.old_python import OLD_VERSIONS, old_python_or_skip

REPO_ROOT = Path(__file__).resolve().parents[2]
DEBUG_INFO = REPO_ROOT / "scripts" / "debug_info.py"


@pytest.mark.parametrize("version", OLD_VERSIONS)
def test_old_interpreter_gets_one_line_not_a_traceback(version: str) -> None:
    python = old_python_or_skip(version)
    result = subprocess.run(
        [python, str(DEBUG_INFO)], capture_output=True, text=True, check=False, cwd="/"
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert f"needs Python 3.11 or newer, but this is Python {version}" in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1
