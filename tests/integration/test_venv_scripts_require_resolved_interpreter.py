"""The venv helpers and their callers never fall back to a bare ``python3``.

Plan 00546 Task 3.1 (#130): ``ensure_venv``, ``ensure_venv_locked`` and
``python_venv_fingerprint`` take the interpreter as a REQUIRED argument, and
the scripts that call them resolve one (``find_latest_python`` /
``HOOKS_DAEMON_PYTHON``) or stop with a named reason.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPTS: Final[Path] = REPO_ROOT / "scripts"
VENV_SH: Final[Path] = SCRIPTS / "install" / "venv.sh"
FP_SH: Final[Path] = SCRIPTS / "install" / "python_fingerprint.sh"
DISCOVERY_SH: Final[Path] = SCRIPTS / "lib" / "python_discovery.sh"
UPGRADE_SH: Final[Path] = SCRIPTS / "upgrade_version.sh"
INSTALL_SH: Final[Path] = SCRIPTS / "install_version.sh"
SETUP_WT_SH: Final[Path] = SCRIPTS / "setup_worktree.sh"

#: Matches ``python3`` used as a command, a default value or an argument.
_BARE_PYTHON_USE: Final[re.Pattern[str]] = re.compile(r":-python3\}|\bpython3 -|\)\s+python3\)|\s+python3\)")


def _bash(script: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP")}
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", "-c", f'set -uo pipefail\nsource "{VENV_SH}"\nsource "{FP_SH}"\n{script}'],
        capture_output=True,
        text=True,
        env=env,
    )


class TestRequiredInterpreterArgument:
    """A missing interpreter argument fails loudly instead of defaulting."""

    def test_ensure_venv_without_python_fails_with_named_reason(self, tmp_path: Path) -> None:
        result = _bash(f'ensure_venv "{tmp_path}" "v1.0.0"')
        assert result.returncode != 0
        assert "ensure_venv: python_bin" in result.stderr + result.stdout
        assert "required" in result.stderr + result.stdout

    def test_ensure_venv_with_empty_python_fails(self, tmp_path: Path) -> None:
        result = _bash(f'ensure_venv "{tmp_path}" "v1.0.0" ""')
        assert result.returncode != 0

    def test_ensure_venv_locked_without_python_fails_with_named_reason(self, tmp_path: Path) -> None:
        result = _bash(f'ensure_venv_locked "{tmp_path}" "v1.0.0"')
        assert result.returncode != 0
        assert "ensure_venv_locked: python_bin" in result.stderr + result.stdout

    def test_python_venv_fingerprint_without_interpreter_fails(self) -> None:
        result = _bash("python_venv_fingerprint")
        assert result.returncode != 0
        assert "python_venv_fingerprint: interpreter" in result.stderr
        assert result.stdout == ""

    def test_python_venv_fingerprint_with_interpreter_still_works(self) -> None:
        result = _bash('python_venv_fingerprint "$(command -v python3)"')
        assert result.returncode == 0, result.stderr
        assert re.fullmatch(r"py\d+-[0-9a-f]{8}", result.stdout.strip())


class TestCallersResolveAnInterpreter:
    """No caller names ``python3`` as a default, argument or command."""

    @pytest.mark.parametrize("script", [INSTALL_SH, UPGRADE_SH, SETUP_WT_SH, VENV_SH, FP_SH])
    def test_no_bare_python3_default_or_invocation(self, script: Path) -> None:
        hits = [
            f"{n}: {line.strip()}"
            for n, line in enumerate(script.read_text().splitlines(), 1)
            if not line.lstrip().startswith("#") and _BARE_PYTHON_USE.search(line)
        ]
        assert hits == [], f"{script.name} still uses a bare python3: {hits}"

    def test_install_version_passes_hooks_daemon_python_after_guard(self) -> None:
        text = INSTALL_SH.read_text()
        assert '"$HOOKS_DAEMON_PYTHON")' in text
        assert 'if [ -z "${HOOKS_DAEMON_PYTHON:-}" ]' in text

    def test_upgrade_version_resolves_before_both_ensure_venv_calls(self) -> None:
        lines = UPGRADE_SH.read_text().splitlines()
        calls = [i for i, line in enumerate(lines) if "ensure_venv " in line and "VENV_PATH=$(" in line]
        assert len(calls) == 2
        for i in calls:
            assert '"$BUILD_PYTHON"' in lines[i]
            assert lines[i - 1].strip() == "_resolve_build_python"


def _function_source(script: Path, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", script.read_text(), re.S | re.M)
    assert match, f"{name} not found in {script.name}"
    return match.group(0)


class TestResolutionFailsLoudly:
    """With no usable interpreter the resolver stops; it never substitutes one."""

    def test_upgrade_build_python_fails_fast_on_invalid_override(self, tmp_path: Path) -> None:
        script = f"""
source "{DISCOVERY_SH}"
fail_fast() {{ echo "FAIL_FAST: $*" >&2; exit 1; }}
print_info() {{ echo "INFO: $*"; }}
GATE_PYTHON_FLOOR="3.11"
DAEMON_DIR="{tmp_path}"
BUILD_PYTHON=""
{_function_source(UPGRADE_SH, "_resolve_build_python")}
_resolve_build_python
echo "PICKED=$BUILD_PYTHON"
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "HOOKS_DAEMON_PYTHON": str(tmp_path / "no-such-python")},
        )
        assert result.returncode != 0
        assert "FAIL_FAST: No Python >= 3.11" in result.stderr
        assert "PICKED=" not in result.stdout

    def test_upgrade_build_python_reports_the_interpreter_it_picked(
        self, tmp_path: Path
    ) -> None:
        import sys

        script = f"""
source "{DISCOVERY_SH}"
fail_fast() {{ echo "FAIL_FAST: $*" >&2; exit 1; }}
print_info() {{ echo "INFO: $*"; }}
GATE_PYTHON_FLOOR="3.11"
DAEMON_DIR="{tmp_path}"
BUILD_PYTHON=""
{_function_source(UPGRADE_SH, "_resolve_build_python")}
_resolve_build_python
echo "PICKED=$BUILD_PYTHON"
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "HOOKS_DAEMON_PYTHON": sys.executable},
        )
        assert result.returncode == 0, result.stderr
        assert f"PICKED={sys.executable}" in result.stdout
        assert "Building the venv with" in result.stdout

    def _run_setup_resolver(
        self, project_root: Path, override: str
    ) -> subprocess.CompletedProcess[str]:
        script = f"""
source "{DISCOVERY_SH}"
RED=""; NC=""
PROJECT_ROOT="{project_root}"
SETUP_PYTHON_FLOOR="3.11"
SETUP_PYTHON=""
{_function_source(SETUP_WT_SH, "_resolve_setup_python")}
_resolve_setup_python || exit 1
echo "PICKED=$SETUP_PYTHON"
"""
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "HOOKS_DAEMON_PYTHON": override},
        )

    def test_setup_worktree_resolver_fails_on_invalid_override(self, tmp_path: Path) -> None:
        result = self._run_setup_resolver(tmp_path, str(tmp_path / "no-such-python"))
        assert result.returncode != 0
        assert "no Python >= 3.11 found" in result.stderr
        assert "PICKED=" not in result.stdout

    def test_setup_worktree_resolver_picks_the_valid_override(self, tmp_path: Path) -> None:
        import sys

        result = self._run_setup_resolver(tmp_path, sys.executable)
        assert result.returncode == 0, result.stderr
        assert f"PICKED={sys.executable}" in result.stdout

    def test_setup_worktree_resolves_before_the_first_interpreter_use(self) -> None:
        text = SETUP_WT_SH.read_text()
        resolve_call = text.index("if ! _resolve_setup_python; then")
        assert resolve_call < text.index("if ! preflight_socket_path")
        assert resolve_call < text.index('DAEMON_VERSION="$(_read_daemon_version')
        assert '"v${DAEMON_VERSION}" "${SETUP_PYTHON}")' in text
