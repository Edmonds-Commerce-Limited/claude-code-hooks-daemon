"""health_check.sh and detect_location.sh read the config with the RESOLVED interpreter.

Both used to run a bare ``python3`` from PATH, which can be older than the
daemon's floor or lack PyYAML. They now resolve the project's venv interpreter
(``resolve_existing_venv_python``) and, when none resolves, say so loudly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
HEALTH_CHECK: Final[Path] = REPO_ROOT / "scripts" / "health_check.sh"
DETECT_LOCATION: Final[Path] = REPO_ROOT / "scripts" / "detect_location.sh"

_TIMEOUT_SECONDS: Final[int] = 60


def _venv_dir() -> Path:
    """The venv this test run uses, handed to the resolver as the venv override."""
    return Path(sys.prefix)


def _project(tmp_path: Path, self_install: bool) -> Path:
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "hooks-daemon.yaml").write_text(
        f"daemon:\n  self_install_mode: {'true' if self_install else 'false'}\n",
        encoding="utf-8",
    )
    return project


def _fake_python3(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    marker = tmp_path / "fake-python3-ran"
    fake = fake_bin / "python3"
    fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    return fake_bin, marker


def _env(fake_bin: Path, resolvable: bool) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_PYTHON", None)
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    if resolvable:
        env["HOOKS_DAEMON_PYTHON"] = sys.executable
        env["HOOKS_DAEMON_VENV_PATH"] = str(_venv_dir())
    return env


def _run(
    script: Path, args: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestHealthCheckUsesTheResolvedInterpreter:
    def test_yaml_checks_pass_without_running_the_python3_on_path(self, tmp_path: Path) -> None:
        project = _project(tmp_path, self_install=False)
        fake_bin, marker = _fake_python3(tmp_path)

        result = _run(HEALTH_CHECK, ["--project-root", str(project)], project, _env(fake_bin, True))

        assert "2. Config file is valid... ✓" in result.stdout, result.stdout
        assert not marker.exists(), "health_check.sh ran the bare python3 from PATH"

    def test_invalid_yaml_is_reported_by_the_resolved_interpreter(self, tmp_path: Path) -> None:
        project = _project(tmp_path, self_install=False)
        (project / ".claude" / "hooks-daemon.yaml").write_text("a: [unclosed\n", encoding="utf-8")
        fake_bin, _ = _fake_python3(tmp_path)

        result = _run(HEALTH_CHECK, ["--project-root", str(project)], project, _env(fake_bin, True))

        assert "Invalid YAML syntax" in result.stdout
        assert result.returncode == 1

    def test_no_resolved_interpreter_fails_loudly(self, tmp_path: Path) -> None:
        project = _project(tmp_path, self_install=False)
        fake_bin, marker = _fake_python3(tmp_path)

        result = _run(
            HEALTH_CHECK, ["--project-root", str(project)], project, _env(fake_bin, False)
        )

        assert "No resolved Python interpreter to validate the config" in result.stdout
        assert "No resolved Python interpreter to read self_install_mode" in result.stdout
        assert result.returncode == 1
        assert not marker.exists(), "health_check.sh fell back to the bare python3 from PATH"


class TestDetectLocationUsesTheResolvedInterpreter:
    def test_self_install_is_read_without_running_the_python3_on_path(self, tmp_path: Path) -> None:
        project = _project(tmp_path, self_install=True)
        fake_bin, marker = _fake_python3(tmp_path)

        result = _run(DETECT_LOCATION, [], project, _env(fake_bin, True))

        assert result.stdout.strip() == "project_root"
        assert "Mode: self-install" in result.stderr, result.stderr
        assert not marker.exists(), "detect_location.sh ran the bare python3 from PATH"

    def test_no_resolved_interpreter_warns_loudly_but_still_reports_the_location(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path, self_install=True)
        fake_bin, marker = _fake_python3(tmp_path)

        result = _run(DETECT_LOCATION, [], project, _env(fake_bin, False))

        assert result.stdout.strip() == "project_root"
        assert "no resolved Python interpreter" in result.stderr
        assert not marker.exists(), "detect_location.sh fell back to the bare python3 from PATH"
