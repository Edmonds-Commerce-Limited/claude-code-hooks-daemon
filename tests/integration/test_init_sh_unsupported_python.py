"""An unsupported system Python is named, not reported as "not installed".

A client's container had python3 3.9. The hooks daemon cannot run on it, and
init.sh answered a bare "HOOKS DAEMON: Not installed" whose advice (install the
daemon) cannot succeed there. The answer must instead name the Python found, the
version required and the fix (upgrade Python), and stay fail-open: Claude Code
must still open, and a non-Stop event must never be denied.

The Python is faked on a curated PATH: the version probe answers as an old
interpreter, everything else is handed to the real one so the encoders work.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / "init.sh"
_RUN_TIMEOUT_SECONDS = 30

_ESSENTIAL_TOOLS = (
    "sh",
    "bash",
    "env",
    "cat",
    "dirname",
    "basename",
    "tr",
    "hostname",
    "stat",
    "date",
    "mkdir",
    "touch",
    "chmod",
    "rm",
    "ls",
    "grep",
    "sed",
    "awk",
    "uname",
    "head",
    "cut",
    "sort",
    "wc",
    "jq",
)


def _fake_python3(bindir: Path, version: str | None) -> None:
    """Install a python3 that reports `version` to the version probe (real otherwise)."""
    real = sys.executable
    body = "#!/bin/sh\n"
    if version is not None:
        body += f'case "$2" in *version_info*) echo "{version}"; exit 0;; esac\n'
    body += f'exec "{real}" "$@"\n'
    path = bindir / "python3"
    path.write_text(body)
    path.chmod(0o755)


def _answer(tmp_path: Path, event: str, state: str, version: str | None) -> dict[str, object]:
    """The parsed JSON init.sh emits for `event` in `state` under a python3 `version`."""
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed on this machine")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in _ESSENTIAL_TOOLS:
        real = shutil.which(tool)
        if real is not None:
            (bindir / tool).symlink_to(real)
    _fake_python3(bindir, version)
    checkout = tmp_path / "client"
    (checkout / ".claude").mkdir(parents=True)
    (checkout / ".claude" / "init.sh").write_text(_INIT_SH.read_text())
    script = (
        f'source "{checkout}/.claude/init.sh" >/dev/null 2>/dev/null\n'
        f"{state}=true\n"
        'emit_hook_error "$1" "daemon_not_installed" "no daemon here"\n'
    )
    result = subprocess.run(
        ["bash", "-c", script, "bash", event],
        capture_output=True,
        text=True,
        env={"PATH": str(bindir), "HOME": str(tmp_path)},
        timeout=_RUN_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


def _context(answer: dict[str, object]) -> str:
    output = answer["hookSpecificOutput"]
    assert isinstance(output, dict)
    context = output["additionalContext"]
    assert isinstance(context, str)
    return context


@pytest.mark.parametrize("state", ["_HOOKS_DAEMON_NOT_INSTALLED", "_HOOKS_DAEMON_VENV_MISSING"])
class TestUnsupportedPythonIsNamed:
    def test_names_found_version_required_version_and_the_fix(
        self, tmp_path: Path, state: str
    ) -> None:
        context = _context(_answer(tmp_path, "SessionStart", state, "3.9.18"))
        assert "UNSUPPORTED PYTHON" in context
        assert "3.9.18" in context
        assert "3.11" in context
        assert "upgrade" in context.lower()
        assert "Not installed" not in context

    def test_stays_fail_open_for_every_non_stop_event(self, tmp_path: Path, state: str) -> None:
        for event in ("SessionStart", "PreToolUse", "UserPromptSubmit"):
            workdir = tmp_path / event
            workdir.mkdir()
            answer = _answer(workdir, event, state, "3.9.18")
            assert "permissionDecision" not in json.dumps(answer)
            assert "decision" not in answer

    def test_a_supported_python_keeps_the_existing_answer(self, tmp_path: Path, state: str) -> None:
        context = _context(_answer(tmp_path, "SessionStart", state, None))
        assert "UNSUPPORTED PYTHON" not in context


class TestMinimumIsSingleSourced:
    def test_fallback_minimum_equals_pyproject_requires_python(self) -> None:
        pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        wanted = re.search(r'^requires-python\s*=\s*">=(\d+\.\d+)"', pyproject, re.MULTILINE)
        assert wanted
        init_sh = _INIT_SH.read_text(encoding="utf-8")
        fallback = re.search(r'^_HOOKS_DAEMON_MIN_PYTHON_FALLBACK="(\d+\.\d+)"', init_sh, re.M)
        assert fallback
        assert fallback.group(1) == wanted.group(1)
