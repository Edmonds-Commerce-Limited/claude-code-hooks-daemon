"""Integration tests: ``scripts/install/relay_provision.sh`` (Plan 00529 Task 2).

The install and upgrade scripts provision the relay binary through
``provision_relay_binary`` and repeat any failure banner through
``report_relay_provision_failure`` just before their final ``exit 0``, so a
missing relay cannot scroll away under the steps that follow. These tests
source the library on its own, drive it with a stub interpreter (exit codes
0, 3 and an unexpected one) and with the real CLI, and pin the call sites in
both scripts.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants import Timeout

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_RELAY_PROVISION_SH: Final[Path] = _REPO_ROOT / "scripts" / "install" / "relay_provision.sh"
_INSTALL_SH: Final[Path] = _REPO_ROOT / "scripts" / "install_version.sh"
_UPGRADE_SH: Final[Path] = _REPO_ROOT / "scripts" / "upgrade_version.sh"

_BANNER_HEAD: Final[str] = "WARNING: RELAY BINARY NOT PROVISIONED"
_REGEN_MARKER: Final[str] = "STUB-FORWARDER-GENERATOR-RAN"


def _stub_python(tmp_path: Path, *, provision_exit: int, provision_output: str) -> Path:
    """A fake venv python: answers the relay CLI and the forwarder generator."""
    stub = tmp_path / "stub-python"
    stub.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            case "$*" in
                *claude_code_hooks_daemon.install.relay_deploy*)
                    printf '%s\\n' "{provision_output}"
                    exit {provision_exit}
                    ;;
                *claude_code_hooks_daemon.install.forwarder_generator*)
                    echo "{_REGEN_MARKER}"
                    exit 0
                    ;;
            esac
            echo "unexpected stub call: $*" >&2
            exit 99
            """))
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def _run(
    venv_python: Path, project_root: Path, daemon_dir: Path
) -> subprocess.CompletedProcess[str]:
    script = f"""
set -euo pipefail
source "{_RELAY_PROVISION_SH}"
provision_relay_binary "{venv_python}" "{daemon_dir}" "{project_root}" "v9.9.9"
echo "STEP-RETURNED failed=$RELAY_PROVISION_FAILED"
echo "---- later steps ----"
report_relay_provision_failure
echo "END"
"""
    bash = shutil.which("bash") or "/bin/bash"
    return subprocess.run(
        [bash, "-c", script],
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        env={**os.environ, "NO_COLOR": "1"},
    )


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    (project_root / ".claude" / "hooks").mkdir(parents=True)
    daemon_dir = project_root / ".claude" / "hooks-daemon"
    daemon_dir.mkdir()
    return project_root, daemon_dir


class TestProvisioned:
    def test_success_prints_once_and_report_is_silent(self, tmp_path: Path) -> None:
        project_root, daemon_dir = _dirs(tmp_path)
        stub = _stub_python(tmp_path, provision_exit=0, provision_output="Relay binary deployed")

        result = _run(stub, project_root, daemon_dir)

        assert result.returncode == 0, result.stderr
        assert "STEP-RETURNED failed=0" in result.stdout
        assert result.stdout.count("Relay binary deployed") == 1
        assert _BANNER_HEAD not in result.stdout
        after = result.stdout.split("---- later steps ----", 1)[1]
        assert after.strip() == "END"

    def test_forwarders_are_regenerated_after_provisioning(self, tmp_path: Path) -> None:
        project_root, daemon_dir = _dirs(tmp_path)
        stub = _stub_python(tmp_path, provision_exit=0, provision_output="Relay binary deployed")

        result = _run(stub, project_root, daemon_dir)

        assert result.returncode == 0, result.stderr
        assert result.stdout.index("Relay binary deployed") < result.stdout.index(_REGEN_MARKER)


class TestNotProvisioned:
    def test_exit_3_prints_banner_at_step_and_again_at_report(self, tmp_path: Path) -> None:
        project_root, daemon_dir = _dirs(tmp_path)
        stub = _stub_python(tmp_path, provision_exit=3, provision_output=_BANNER_HEAD)

        result = _run(stub, project_root, daemon_dir)

        assert result.returncode == 0, result.stderr
        assert "STEP-RETURNED failed=1" in result.stdout
        before, after = result.stdout.split("---- later steps ----", 1)
        assert _BANNER_HEAD in before
        assert _BANNER_HEAD in after
        assert after.index(_BANNER_HEAD) < after.index("END")

    def test_forwarders_are_still_regenerated_when_provisioning_fails(self, tmp_path: Path) -> None:
        project_root, daemon_dir = _dirs(tmp_path)
        stub = _stub_python(tmp_path, provision_exit=3, provision_output=_BANNER_HEAD)

        result = _run(stub, project_root, daemon_dir)

        assert _REGEN_MARKER in result.stdout

    def test_unexpected_exit_code_is_a_loud_failure_naming_the_code(self, tmp_path: Path) -> None:
        project_root, daemon_dir = _dirs(tmp_path)
        stub = _stub_python(tmp_path, provision_exit=1, provision_output="Traceback: boom")

        result = _run(stub, project_root, daemon_dir)

        assert result.returncode == 0, result.stderr
        assert "STEP-RETURNED failed=1" in result.stdout
        after = result.stdout.split("---- later steps ----", 1)[1]
        assert "exit 1" in after
        assert "Traceback: boom" in after


class TestRealCli:
    """The library against the real ``relay_deploy`` CLI (no network, no build)."""

    @staticmethod
    def _config(project_root: Path, transport: str) -> None:
        body = "version: '2.0'\ndaemon:\n  transport:\n" + textwrap.indent(transport, "    ")
        (project_root / ".claude" / "hooks-daemon.yaml").write_text(body)

    def test_disabled_relay_does_nothing_and_reports_nothing(self, tmp_path: Path) -> None:
        project_root, daemon_dir = _dirs(tmp_path)
        self._config(project_root, "relay_enabled: false\n")

        result = _run(Path(sys.executable), project_root, daemon_dir)

        assert result.returncode == 0, result.stderr
        assert "Relay disabled" in result.stdout
        assert "STEP-RETURNED failed=0" in result.stdout
        assert _BANNER_HEAD not in result.stdout

    def test_enabled_relay_with_no_source_and_no_binary_banners_twice(self, tmp_path: Path) -> None:
        project_root, daemon_dir = _dirs(tmp_path)
        self._config(project_root, "relay_enabled: true\n")

        result = _run(Path(sys.executable), project_root, daemon_dir)

        assert result.returncode == 0, result.stderr
        assert result.stdout.count(_BANNER_HEAD) == 2
        assert "transport on" in result.stdout.split("---- later steps ----", 1)[1]


def _final_exit_line(lines: list[str]) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == "exit 0":
            return index
    raise AssertionError("no final exit 0")


class TestCallSites:
    def test_no_inline_relay_heredoc_remains(self) -> None:
        for script in (_INSTALL_SH, _UPGRADE_SH):
            assert "deploy_relay_if_configured" not in script.read_text(encoding="utf-8"), script

    def test_install_sources_and_calls_the_library(self) -> None:
        body = _INSTALL_SH.read_text(encoding="utf-8")
        assert 'source "$INSTALL_LIB_DIR/relay_provision.sh"' in body
        assert len(re.findall(r"^\s*provision_relay_binary ", body, re.MULTILINE)) == 1

    def test_upgrade_sources_and_calls_the_library_on_both_paths(self) -> None:
        body = _UPGRADE_SH.read_text(encoding="utf-8")
        assert 'source "$INSTALL_LIB_DIR/relay_provision.sh"' in body
        assert len(re.findall(r"^\s*provision_relay_binary ", body, re.MULTILINE)) == 2

    def test_install_repeats_the_banner_just_before_its_final_exit(self) -> None:
        lines = _INSTALL_SH.read_text(encoding="utf-8").splitlines()
        final = _final_exit_line(lines)
        window = [line.strip() for line in lines[max(0, final - 4) : final]]
        assert "report_relay_provision_failure" in window

    def test_upgrade_repeats_the_banner_before_both_exits(self) -> None:
        lines = _UPGRADE_SH.read_text(encoding="utf-8").splitlines()
        exits = [i for i, line in enumerate(lines) if line.strip() == "exit 0"]
        assert len(exits) >= 2
        for index in (exits[-2], exits[-1]):
            window = [line.strip() for line in lines[max(0, index - 4) : index]]
            assert "report_relay_provision_failure" in window, lines[index - 4 : index + 1]
