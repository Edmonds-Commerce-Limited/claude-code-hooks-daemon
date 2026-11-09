"""``_target_release`` never reads a commit ref made only of digits as a release.

Ledger 00474 N598: main CI upgraded a fixture project to its own short SHA,
``965951009``. ``scripts/upgrade_version.sh``'s ``_target_release`` matched
that stamp against a version pattern that accepted a bare run of digits, so
the pre-deploy gate was told the target was release 965951009, a MAJOR change
from v3, and stopped the upgrade (exit 3). About 1.5% of 9-character short
SHAs are all decimal digits. A ref with a letter in it already fell through to
the checkout's own ``version.py``; an all-digit one must do the same.

The function's real body is extracted from the script and run in bash, with
``_gate_trusted_path`` stubbed and ``DAEMON_DIR`` pointing at a fixture whose
``version.py`` says ``3.73.0``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "upgrade_version.sh"
CHECKOUT_VERSION = "3.73.0"


def _function_body(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index(f"{name}() {{")
    match = re.compile(r"\n[ \t]*\}\n").search(text, start)
    assert match is not None, f"no closing brace found for {name}"
    return text[start : match.end()]


def _target_release(tmp_path: Path, stamp: str) -> str:
    version_py = tmp_path / "src" / "claude_code_hooks_daemon" / "version.py"
    version_py.parent.mkdir(parents=True)
    version_py.write_text(f'__version__ = "{CHECKOUT_VERSION}"\n', encoding="utf-8")
    program = "\n".join(
        [
            '_gate_trusted_path() { echo "/usr/bin:/bin"; }',
            _function_body("_target_release"),
            "_target_release",
        ]
    )
    result = subprocess.run(
        ["bash", "-c", program],
        env={"INSTALL_STAMP": stamp, "DAEMON_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("stamp", ["965951009", "1234567", "0123456789012"])
def test_an_all_digit_commit_ref_falls_back_to_the_checkout_version(
    tmp_path: Path, stamp: str
) -> None:
    assert _target_release(tmp_path, stamp) == CHECKOUT_VERSION


def test_a_lettered_commit_ref_falls_back_as_before(tmp_path: Path) -> None:
    assert _target_release(tmp_path, "0123abc") == CHECKOUT_VERSION


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("v3.74.0", "v3.74.0"),
        ("3.74.0", "3.74.0"),
        ("3.74.0+main.abc1234", "3.74.0"),
        ("v4", "v4"),
    ],
)
def test_a_release_stamp_is_still_the_release(tmp_path: Path, stamp: str, expected: str) -> None:
    assert _target_release(tmp_path, stamp) == expected
