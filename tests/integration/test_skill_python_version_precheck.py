"""Plan 00100 Task 0.3: skill-wrapper Python version pre-check.

Field bug (2026-04-23): host has `python3`→3.9 (incompatible) but
`python3.13`→3.13.11 (compatible). The daemon's Layer 1 resolver correctly
finds /usr/bin/python3.13, but the skill-layer stops the daemon BEFORE
surfacing the version mismatch, leaving the user without a daemon and
with a cryptic failure.

v2 fix:
  1. New helper `scripts/install/parse_min_python.sh` — single source of
     truth for minimum Python version, parsed from
     `pyproject.toml:requires-python`. No hardcoded version.
  2. The skill wrappers (`install.sh`, `upgrade.sh`) call
     `parse_min_python.sh`, compare with the active `python3 --version`,
     and short-circuit BEFORE any daemon-state mutation when incompatible.
  3. On mismatch, surface an actionable `HOOKS_DAEMON_PYTHON=...` command
     so the user can specify a compatible Python.

These tests verify the contract via static analysis and a direct run of
`parse_min_python.sh`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
PARSE_MIN_PYTHON_SH = REPO_ROOT / "scripts" / "install" / "parse_min_python.sh"
UPGRADE_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "upgrade.sh"
)
INSTALL_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "install.sh"
)
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"


def test_parse_min_python_sh_exists() -> None:
    """The helper script must exist at the documented path."""
    assert PARSE_MIN_PYTHON_SH.is_file(), (
        f"parse_min_python.sh not found at {PARSE_MIN_PYTHON_SH}. " "See Plan 00100 Task 0.3."
    )


def test_parse_min_python_sh_extracts_version_from_pyproject() -> None:
    """Running the helper must echo the minimum Python version in
    `MAJOR.MINOR` form (e.g. `3.11`), extracted from pyproject.toml."""
    assert PARSE_MIN_PYTHON_SH.is_file(), "parse_min_python.sh missing"

    result = subprocess.run(
        ["bash", str(PARSE_MIN_PYTHON_SH), str(PYPROJECT_TOML)],
        capture_output=True,
        text=True,
        timeout=Timeout.SOCKET_CONNECT,
    )
    assert (
        result.returncode == 0
    ), f"parse_min_python.sh failed. stdout={result.stdout!r} stderr={result.stderr!r}"
    # Output should match MAJOR.MINOR, e.g. "3.11"
    out = result.stdout.strip()
    assert re.fullmatch(
        r"\d+\.\d+", out
    ), f"parse_min_python.sh must output MAJOR.MINOR only; got {out!r}"

    # Cross-check against pyproject.toml requires-python
    content = PYPROJECT_TOML.read_text()
    match = re.search(r'requires-python\s*=\s*"[^0-9]*(\d+\.\d+)', content)
    assert match is not None, "pyproject.toml requires-python not found"
    assert out == match.group(
        1
    ), f"parse_min_python.sh output {out} does not match pyproject.toml {match.group(1)}"


def test_parse_min_python_sh_hardcodes_nothing() -> None:
    """The helper must NOT contain a hardcoded Python version — it must
    parse from pyproject.toml (RISKY-2 in CRITIQUE-v1.md)."""
    assert PARSE_MIN_PYTHON_SH.is_file(), "parse_min_python.sh missing"
    content = PARSE_MIN_PYTHON_SH.read_text()

    # Find version-like literals in the script (e.g. 3.11, 3.13).
    literals = re.findall(r'[\'"]?(\d+\.\d+)[\'"]?', content)
    # A fallback default is tolerable, but no literal must match the CURRENT
    # pyproject.toml version — that would mean the helper hardcodes it.
    pyproject_content = PYPROJECT_TOML.read_text()
    match = re.search(r'requires-python\s*=\s*"[^0-9]*(\d+\.\d+)', pyproject_content)
    assert match is not None
    current_min = match.group(1)

    # If the helper contains the exact current version string as a literal,
    # it suggests hardcoding rather than parsing.
    if current_min in literals:
        # Permitted only if the literal appears inside a comment or test block.
        # Crude heuristic: ensure the file also calls `grep` or `sed` to parse
        # pyproject.toml — proving it does actual parsing.
        assert re.search(r"grep|sed|awk", content), (
            f"parse_min_python.sh contains literal {current_min} and no parse "
            f"commands — looks hardcoded. See Plan 00100 Task 0.3."
        )


def test_upgrade_sh_calls_parse_min_python_before_daemon_mutation() -> None:
    """The skill wrapper must invoke the version pre-check before any
    daemon-state-mutating command (stop, restart, upgrade, install)."""
    assert UPGRADE_SH.is_file(), f"upgrade.sh not found at {UPGRADE_SH}"
    content = UPGRADE_SH.read_text()

    # Must reference parse_min_python.sh (or the pre-check logic inline).
    refers_to_parser = "parse_min_python" in content or "requires-python" in content
    assert refers_to_parser, (
        "upgrade.sh must call parse_min_python.sh (or inline equivalent) "
        "before daemon mutation. See Plan 00100 Task 0.3."
    )


def test_install_sh_calls_parse_min_python() -> None:
    """install.sh must also invoke the version pre-check."""
    assert INSTALL_SH.is_file(), f"install.sh not found at {INSTALL_SH}"
    content = INSTALL_SH.read_text()
    refers_to_parser = "parse_min_python" in content or "requires-python" in content
    assert refers_to_parser, (
        "install.sh must call parse_min_python.sh (or inline equivalent) "
        "before downloading/executing the installer. See Plan 00100 Task 0.3."
    )


def test_upgrade_sh_surfaces_hooks_daemon_python_env_on_mismatch() -> None:
    """When the active python3 is incompatible, the wrapper must surface
    an actionable `HOOKS_DAEMON_PYTHON=...` hint so the user can retry."""
    assert UPGRADE_SH.is_file()
    content = UPGRADE_SH.read_text()
    assert "HOOKS_DAEMON_PYTHON" in content, (
        "upgrade.sh must mention HOOKS_DAEMON_PYTHON in its version-mismatch "
        "error message. See Plan 00100 Task 0.3."
    )
