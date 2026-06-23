"""Plan 00137 F-PYFLOOR — ``check_python3`` must honour the pyproject floor.

``scripts/install/prerequisites.sh::check_python3`` historically called
``find_latest_python 3.11`` with NO pyproject argument, so it ignored the
authoritative ``requires-python`` floor in ``pyproject.toml``. At the next
floor bump that would silently accept a too-old interpreter that the daemon
itself cannot run. The SSoT for the minimum is ``pyproject.toml``; the bare
``3.11`` literal must only ever be the floor-of-last-resort when no pyproject
is supplied.

These tests source the real ``prerequisites.sh`` in an isolated subshell
(PATH points only at fake ``python3.N`` interpreters plus symlinks to the two
external tools the libs need — ``dirname`` and ``sort``) and assert
``check_python3`` raises its floor from the pyproject and that its failure
diagnostic names the EFFECTIVE (parsed) floor, not a hardcoded ``3.11``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PREREQ = REPO_ROOT / "scripts" / "install" / "prerequisites.sh"
BASH = shutil.which("bash") or "/bin/bash"

_FAKE_PYTHON_TEMPLATE = """\
#!/bin/sh
case "$1" in
    --version) echo "Python {version}" ;;
    -c) shift; eval "echo 'Python {version}'" ;;
    *) echo "Python {version}" ;;
esac
"""

# External tools the sourced libs invoke (everything else is a bash builtin).
_REQUIRED_TOOLS = ("dirname", "sort")


def _make_fake_python(bin_dir: Path, command_name: str, version: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / command_name
    path.write_text(_FAKE_PYTHON_TEMPLATE.format(version=version))
    path.chmod(0o755)
    return path


def _make_tools_dir(tmp_path: Path) -> Path:
    """A bin dir holding ONLY symlinks to the externals the libs need, so the
    interpreter glob never sees the host's real ``python3.N`` binaries.
    """
    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for tool in _REQUIRED_TOOLS:
        real = shutil.which(tool)
        assert real, f"required tool {tool!r} not found on host"
        (tools / tool).symlink_to(real)
    return tools


def _invoke_check_python3(
    pyproject: Path,
    *,
    bin_dir: Path,
    tmp_path: Path,
) -> subprocess.CompletedProcess[str]:
    tools = _make_tools_dir(tmp_path)
    env = {
        "PATH": f"{bin_dir}:{tools}",
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    script = (
        f'set -u; . "{PREREQ}"; '
        f'check_python3 "{pyproject}" && printf "CHOSEN=%s\\n" "$HOOKS_DAEMON_PYTHON"'
    )
    return subprocess.run(
        [BASH, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_python3_fails_when_only_interpreter_below_pyproject_floor(
    tmp_path: Path,
) -> None:
    """Only python3.11 on PATH but pyproject requires >=3.13 → MUST fail.

    Pre-fix, check_python3 used the bare 3.11 floor and happily accepted
    python3.11 even though the project requires 3.13. This is the regression.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nrequires-python = ">=3.13"\n')

    result = _invoke_check_python3(pyproject, bin_dir=bin_dir, tmp_path=tmp_path)

    assert result.returncode != 0, (
        "check_python3 must reject python3.11 when pyproject requires >=3.13. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_check_python3_failure_diagnostic_names_parsed_floor(tmp_path: Path) -> None:
    """The failure message must name the EFFECTIVE floor (3.13), not a hardcoded 3.11."""
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nrequires-python = ">=3.13"\n')

    result = _invoke_check_python3(pyproject, bin_dir=bin_dir, tmp_path=tmp_path)

    assert "3.13" in result.stderr, (
        "diagnostic must derive the floor from the parsed pyproject (3.13), "
        f"got: {result.stderr!r}"
    )


def test_check_python3_selects_interpreter_meeting_pyproject_floor(tmp_path: Path) -> None:
    """python3.14 present, pyproject requires >=3.13 → succeeds and picks 3.14."""
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nrequires-python = ">=3.13"\n')

    result = _invoke_check_python3(pyproject, bin_dir=bin_dir, tmp_path=tmp_path)

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    chosen = ""
    for line in result.stdout.splitlines():
        if line.startswith("CHOSEN="):
            chosen = line.split("=", 1)[1]
    assert chosen.endswith("/python3.14"), f"expected python3.14, got {chosen!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
