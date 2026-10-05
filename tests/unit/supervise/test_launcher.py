"""The ccy launcher gates the supervisor on a supported Python.

``.claude/ccy/claude-supervise`` is a POSIX shell script, so it runs before any
Python parses ``claude-supervise.py`` (3.10+ syntax fails at parse time, which a
version check inside the .py can never catch). On an unsupported Python it must
print a loud warning and exec the wrapped ``claude`` unsupervised: an old
Python must never stop Claude Code from opening.

The tests run the real launcher with PATH confined to a temp directory holding
fake ``python3*`` and ``claude`` scripts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_LAUNCHER_SOURCE: Final[Path] = _REPO_ROOT / ".claude" / "ccy" / "claude-supervise"

_FAKE_CLAUDE: Final[str] = '#!/bin/sh\necho "CLAUDE-RAN $*"\n'


def _fake_python(version_ok: bool, version: str = "3.9.18") -> str:
    """A fake interpreter: answers the version probes, else reports its argv."""
    status = 0 if version_ok else 1
    return (
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then\n'
        '  case "$2" in\n'
        f'    *print*) echo "{version}"; exit 0;;\n'
        f"    *) exit {status};;\n"
        "  esac\n"
        "fi\n"
        'echo "SUPERVISOR-RAN $*"\n'
    )


class Sandbox:
    """A launcher copy beside a fake supervisor, with a confined PATH."""

    def __init__(self, root: Path) -> None:
        self.ccy = root / "ccy"
        self.bin = root / "bin"
        self.ccy.mkdir()
        self.bin.mkdir()
        self.launcher = self.ccy / "claude-supervise"
        shutil.copy2(_LAUNCHER_SOURCE, self.launcher)
        (self.ccy / "claude-supervise.py").write_text("# fake\n", encoding="utf-8")
        self.add("claude", _FAKE_CLAUDE)

    def add(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def run(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {"PATH": str(self.bin), "CCY_UNSUPPORTED_PYTHON_PAUSE": "0"}
        env.update(extra_env or {})
        return subprocess.run(
            ["/bin/sh", str(self.launcher), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=30,
        )


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


class TestSupportedPython:
    def test_execs_the_supervisor_with_every_argument(self, sandbox: Sandbox) -> None:
        sandbox.add("python3", _fake_python(True, "3.12.1"))
        result = sandbox.run("--arm", "--", "claude", "--resume", "abc")
        assert result.returncode == 0
        expected = f"SUPERVISOR-RAN {sandbox.ccy}/claude-supervise.py --arm -- claude --resume abc"
        assert result.stdout.strip() == expected
        assert "NOT SUPPORTED" not in result.stderr

    def test_prefers_a_newer_versioned_interpreter_over_python3(self, sandbox: Sandbox) -> None:
        sandbox.add("python3", _fake_python(False))
        sandbox.add("python3.12", _fake_python(True, "3.12.1"))
        result = sandbox.run("--arm", "--", "claude")
        assert "SUPERVISOR-RAN" in result.stdout
        assert "CLAUDE-RAN" not in result.stdout

    def test_ccy_python_is_tried_first(self, sandbox: Sandbox, tmp_path: Path) -> None:
        sandbox.add("python3", _fake_python(True))
        chosen = tmp_path / "mypy"
        chosen.write_text(_fake_python(True).replace("SUPERVISOR-RAN", "CHOSEN-RAN"))
        chosen.chmod(0o755)
        result = sandbox.run("--arm", "--", "claude", extra_env={"CCY_PYTHON": str(chosen)})
        assert "CHOSEN-RAN" in result.stdout

    def test_unsupported_ccy_python_falls_through_to_the_next(
        self, sandbox: Sandbox, tmp_path: Path
    ) -> None:
        sandbox.add("python3", _fake_python(True))
        old = tmp_path / "oldpy"
        old.write_text(_fake_python(False))
        old.chmod(0o755)
        result = sandbox.run("--arm", "--", "claude", extra_env={"CCY_PYTHON": str(old)})
        assert "SUPERVISOR-RAN" in result.stdout


class TestUnsupportedPython:
    def test_old_python_runs_claude_unsupervised_with_a_loud_warning(
        self, sandbox: Sandbox
    ) -> None:
        sandbox.add("python3", _fake_python(False, "3.9.18"))
        result = sandbox.run("--arm", "--", "claude", "--resume", "abc")
        assert result.returncode == 0
        assert result.stdout.strip() == "CLAUDE-RAN --resume abc"
        assert "NOT SUPPORTED" in result.stderr
        assert "3.9.18" in result.stderr
        assert "3.11" in result.stderr
        assert "OFF" in result.stderr
        assert "CCY_PYTHON" in result.stderr

    def test_no_python_at_all_still_runs_claude(self, sandbox: Sandbox) -> None:
        result = sandbox.run("--arm", "--", "claude", "hello")
        assert result.returncode == 0
        assert result.stdout.strip() == "CLAUDE-RAN hello"
        assert "NOT SUPPORTED" in result.stderr
        assert "no python3" in result.stderr.lower()

    def test_missing_supervisor_file_still_runs_claude(self, sandbox: Sandbox) -> None:
        sandbox.add("python3", _fake_python(True))
        (sandbox.ccy / "claude-supervise.py").unlink()
        result = sandbox.run("--arm", "--", "claude")
        assert result.stdout.strip() == "CLAUDE-RAN"
        assert "claude-supervise.py" in result.stderr

    def test_arguments_with_spaces_survive_the_pass_through(self, sandbox: Sandbox) -> None:
        result = sandbox.run("--", "claude", "a b", "c")
        assert result.stdout.strip() == "CLAUDE-RAN a b c"

    def test_no_separator_is_an_error_not_a_hang(self, sandbox: Sandbox) -> None:
        sandbox.add("python3", _fake_python(False))
        result = sandbox.run("--arm")
        assert result.returncode == 2
        assert "CLAUDE-RAN" not in result.stdout


class TestRealInterpreters:
    def test_real_python_3_9_leaves_claude_usable(self, sandbox: Sandbox) -> None:
        """Runs the launcher against a genuine 3.9 interpreter when one is installed."""
        found = shutil.which("python3.9") or _uv_python("3.9")
        if found is None:
            pytest.skip("no Python 3.9 interpreter available")
        (sandbox.bin / "python3").symlink_to(found)
        result = sandbox.run("--arm", "--", "claude", "x")
        assert result.stdout.strip() == "CLAUDE-RAN x"
        assert "3.9." in result.stderr
        assert "NOT SUPPORTED" in result.stderr


def _uv_python(version: str) -> str | None:
    """Path of a uv-managed interpreter, without installing anything."""
    uv = shutil.which("uv")
    if uv is None:
        return None
    result = subprocess.run(
        [uv, "python", "find", version], capture_output=True, text=True, check=False
    )
    path = result.stdout.strip()
    return path if result.returncode == 0 and path.startswith("/") else None


class TestMinimumVersionIsSingleSourced:
    def test_launcher_minimum_equals_pyproject_requires_python(self) -> None:
        pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^requires-python\s*=\s*">=(\d+)\.(\d+)"', pyproject, re.MULTILINE)
        assert match, "pyproject.toml has no `requires-python = \">=X.Y\"`"
        launcher = _LAUNCHER_SOURCE.read_text(encoding="utf-8")
        assert f"MIN_MAJOR={match.group(1)}\n" in launcher
        assert f"MIN_MINOR={match.group(2)}\n" in launcher


class TestLauncherFile:
    def test_is_executable_posix_shell_with_ownership_banner(self) -> None:
        assert os.access(_LAUNCHER_SOURCE, os.X_OK)
        text = _LAUNCHER_SOURCE.read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh\n")
        assert "DAEMON-OWNED FILE - do not edit" in text

    def test_parses_as_posix_shell(self) -> None:
        result = subprocess.run(
            ["/bin/sh", "-n", str(_LAUNCHER_SOURCE)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
