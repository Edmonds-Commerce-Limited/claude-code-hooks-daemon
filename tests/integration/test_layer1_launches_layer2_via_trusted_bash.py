"""Plan 00376 review3 — Layer 1 launches Layer 2 on a TRUSTED `bash` (Plan
00376 review2 MAJOR 1's residual).

``upgrade.sh`` (Layer 1) used to run `bash "$LAYER2_SCRIPT" ...`, resolving
`bash` from the caller's own `PATH`. A caller able to plant a fake `bash`
ahead of the real one on `PATH` therefore controlled what interpreted Layer 2
before Layer 2's own `_sanitise_layer2_env` ever got a chance to run --
sanitising Layer 2's OWN environment (the fix in the same plan) does nothing
about what LAUNCHES it.

The fix: Layer 1 sources `env_sanitise.sh` from the target it just checked
out and resolves `bash` via `_gate_tool`, a fixed, root-owned,
non-group/world-writable system location -- never the caller's `PATH`. These
tests drive the REAL `scripts/upgrade.sh` against a REAL git fixture (a bare
daemon "origin" carrying a stub Layer 2 and a real copy of
`env_sanitise.sh`), with a hostile `bash` planted early on `PATH`, and prove
it never runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
ENV_SANITISE_SH = REPO_ROOT / "scripts" / "install" / "env_sanitise.sh"
GIT = shutil.which("git") or "/usr/bin/git"
REAL_BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 120

# The stub Layer 2 committed into the fixture daemon repository. `$BASH` is
# the bash builtin naming the interpreter CURRENTLY running this script --
# exactly the fact these tests need to pin down which `bash` Layer 1 chose.
_STUB_LAYER2 = """\
#!/bin/bash
set -euo pipefail
echo "STUB_LAYER2_ARGS: $*"
echo "STUB_LAYER2_INTERPRETER: $BASH"
"""


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GIT, *args], cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
    )


def _require_ok(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        raise AssertionError(f"fixture setup failed ({what}): {result.stderr.strip()}")


def _commit_all(work: Path, message: str) -> str:
    _require_ok(_git("add", "-A", cwd=work), f"add ({message})")
    _require_ok(_git("commit", "-qm", message, cwd=work), f"commit ({message})")
    return _git("rev-parse", "HEAD", cwd=work).stdout.strip()


@pytest.fixture
def daemon_remote(tmp_path: Path) -> Path:
    """A bare daemon "origin" tagged v1.0.0: a stub Layer 2 plus a real
    `env_sanitise.sh`, the same tree `$LAYER2_SCRIPT` itself is read from.
    """
    remote = tmp_path / "daemon-origin.git"
    work = tmp_path / "daemon-work"
    _require_ok(_git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path), "bare")
    _require_ok(_git("clone", "-q", str(remote), str(work), cwd=tmp_path), "clone work")
    _require_ok(_git("config", "user.email", "test@example.com", cwd=work), "email")
    _require_ok(_git("config", "user.name", "Test", cwd=work), "name")
    _require_ok(_git("checkout", "-q", "-b", "main", cwd=work), "main branch")

    (work / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "1.0.0"\n')
    scripts = work / "scripts"
    scripts.mkdir()
    stub = scripts / "upgrade_version.sh"
    stub.write_text(_STUB_LAYER2)
    stub.chmod(0o755)
    install_dir = scripts / "install"
    install_dir.mkdir()
    shutil.copy(ENV_SANITISE_SH, install_dir / "env_sanitise.sh")

    _commit_all(work, "release v1.0.0")
    _require_ok(_git("tag", "v1.0.0", cwd=work), "tag")
    _require_ok(_git("push", "-q", "origin", "main", cwd=work), "push main")
    _require_ok(_git("push", "-q", "origin", "v1.0.0", cwd=work), "push tag")
    return remote


@pytest.fixture
def client_project(tmp_path: Path, daemon_remote: Path) -> Path:
    """A client project whose daemon dir is a clone sitting on ``v1.0.0``."""
    project = tmp_path / "client"
    (project / ".claude").mkdir(parents=True)
    _require_ok(_git("init", "-q", str(project), cwd=tmp_path), "client init")
    (project / ".claude" / "hooks-daemon.yaml").write_text("version: '1.0'\n")
    daemon_dir = project / ".claude" / "hooks-daemon"
    _require_ok(_git("clone", "-q", str(daemon_remote), str(daemon_dir), cwd=tmp_path), "daemon clone")
    _require_ok(_git("checkout", "-q", "v1.0.0", cwd=daemon_dir), "checkout tag")
    return project


@pytest.fixture
def hostile_bash(tmp_path: Path) -> tuple[Path, Path]:
    """An executable named `bash`, ahead of the real one on `PATH`.

    Returns (its directory, the marker file it touches if ever run). It
    execs the real bash afterwards so that IF it were ever invoked, the
    command it was asked to run still completes -- this is a detector, not a
    saboteur, so a false negative here cannot be mistaken for the fix simply
    crashing the upgrade.
    """
    marker = tmp_path / "hostile_bash_ran"
    bin_dir = tmp_path / "hostile-bin"
    bin_dir.mkdir()
    hostile = bin_dir / "bash"
    hostile.write_text(f'#!/bin/sh\ntouch "{marker}"\nexec {REAL_BASH} "$@"\n')
    hostile.chmod(0o755)
    return bin_dir, marker


def _run_layer1(project: Path, path_prefix: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
    env["NO_COLOR"] = "1"
    env.pop("HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION", None)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [REAL_BASH, str(LAYER1_UPGRADE_SH), "--project-root", str(project), "v1.0.0"],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestLayer2IsLaunchedOnATrustedBash:
    def test_a_hostile_bash_planted_ahead_on_path_never_runs(
        self, client_project: Path, hostile_bash: tuple[Path, Path]
    ) -> None:
        bin_dir, marker = hostile_bash
        result = _run_layer1(client_project, path_prefix=bin_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert not marker.exists(), "the hostile bash on PATH ran Layer 2"
        assert "STUB_LAYER2_ARGS:" in result.stdout

    def test_layer2_runs_on_the_gate_trusted_interpreter_not_a_bare_path_lookup(
        self, client_project: Path, hostile_bash: tuple[Path, Path]
    ) -> None:
        bin_dir, _marker = hostile_bash
        result = _run_layer1(client_project, path_prefix=bin_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        interpreter_line = next(
            line for line in result.stdout.splitlines() if line.startswith("STUB_LAYER2_INTERPRETER:")
        )
        interpreter = interpreter_line.split(": ", 1)[1].strip()
        assert interpreter != str(bin_dir / "bash")
        assert interpreter.startswith(("/usr/bin/", "/bin/", "/usr/sbin/", "/sbin/", "/usr/local/bin/", "/opt/homebrew/bin/"))

    def test_without_a_hostile_path_the_upgrade_still_succeeds(self, client_project: Path) -> None:
        """The fix must not break the ordinary, non-hostile case."""
        result = _run_layer1(client_project)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STUB_LAYER2_ARGS:" in result.stdout
