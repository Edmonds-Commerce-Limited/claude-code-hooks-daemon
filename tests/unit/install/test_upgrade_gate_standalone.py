"""The venv-free entry point of the upgrade gate (Plan 00376 Tasks 1.2 and 3.1).

Layer 2 runs the gate BEFORE the target's venv is built, so that a stopped
upgrade has changed nothing but the checkout it then restores. That needs an
entry point any python3 can run: no venv, no third-party package, and no
``claude_code_hooks_daemon/__init__.py`` (which imports pydantic). The loader
is the ``signal_standalone.py`` pattern: each module is loaded by file path
under its real dotted name.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE = REPO_ROOT / "src" / "claude_code_hooks_daemon"
SCRIPT_PATH = _PACKAGE / "install" / "upgrade_gate_standalone.py"
_SYSTEM_PYTHON = Path("/usr/bin/python3")
#: ``one_shot_approval.py`` imports ``datetime.UTC`` (3.11); the daemon's own
#: floor is the same.
_SYNTAX_FLOOR = (3, 11)
_NEEDS_ACKNOWLEDGEMENT = 3

pytestmark = pytest.mark.skipif(
    not _SYSTEM_PYTHON.exists(), reason=f"{_SYSTEM_PYTHON} unavailable in this environment"
)


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    return env


class TestNoThirdPartyImports:
    def test_running_it_loads_nothing_outside_the_stdlib_and_never_the_package_init(
        self,
    ) -> None:
        code = (
            "import runpy, sys\n"
            "before = set(sys.modules)\n"
            f"runpy.run_path({str(SCRIPT_PATH)!r}, run_name='not_main')\n"
            "after = set(sys.modules)\n"
            "stdlib = set(sys.stdlib_module_names)\n"
            "offenders = sorted(\n"
            "    m for m in (after - before)\n"
            "    if m.split('.')[0] not in stdlib\n"
            "    and not m.startswith('claude_code_hooks_daemon.')\n"
            ")\n"
            "print('OFFENDERS=' + ','.join(offenders))\n"
            "print('PACKAGE_INIT=' + str('claude_code_hooks_daemon' in sys.modules))\n"
        )
        result = subprocess.run(
            [str(_SYSTEM_PYTHON), "-I", "-c", code],
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "OFFENDERS=\n" in result.stdout + "\n", result.stdout
        assert "PACKAGE_INIT=False" in result.stdout

    @pytest.mark.parametrize(
        "relative_path",
        [
            "install/upgrade_gate_standalone.py",
            "install/upgrade_gate.py",
            "install/upgrade_tasks.py",
            "install/upgrade_guides.py",
            "install/install_stamp.py",
            "install/version_parse.py",
            "utils/one_shot_approval.py",
            "utils/path_containment.py",
            "daemon/install_layout.py",
        ],
    )
    def test_every_loaded_file_parses_at_the_floor(self, relative_path: str) -> None:
        path = _PACKAGE / relative_path
        ast.parse(path.read_text(encoding="utf-8"), feature_version=_SYNTAX_FLOOR)

    def test_every_package_import_of_a_loaded_file_is_itself_loaded(self) -> None:
        """A file the loader forgets would fall through to a real package import."""
        loader_text = SCRIPT_PATH.read_text(encoding="utf-8")
        for relative in (
            "install/upgrade_gate.py",
            "install/upgrade_tasks.py",
            "install/upgrade_guides.py",
        ):
            tree = ast.parse((_PACKAGE / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "claude_code_hooks_daemon."
                ):
                    assert f'"{node.module}"' in loader_text, (
                        f"{relative} imports {node.module}, which the standalone loader "
                        "does not load"
                    )


class TestEndToEndWithoutVenv:
    def test_a_crossed_guide_stops_with_the_needs_acknowledgement_code(
        self, tmp_path: Path
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        guide = daemon_dir / "CLAUDE" / "UPGRADES" / "v3" / "v3.64.0-to-v3.65.0"
        guide.mkdir(parents=True)
        (guide / "v3.64.0-to-v3.65.0.md").write_text("# guide\n")
        project = tmp_path / "project"
        project.mkdir()
        argv = [
            str(_SYSTEM_PYTHON),
            str(SCRIPT_PATH),
            "--daemon-dir",
            str(daemon_dir),
            "--project-root",
            str(project),
            "--installed-stamp",
            "v3.64.0",
            "--to",
            "3.65.0",
        ]
        stopped = subprocess.run(
            argv, capture_output=True, text=True, env=_clean_env(), check=False
        )
        assert stopped.returncode == _NEEDS_ACKNOWLEDGEMENT, stopped.stderr
        assert "REQUIRED READING" in stopped.stderr
        digest = re.search(r"--skip-reading-confirmation=(\w+)", stopped.stderr)
        assert digest is not None, stopped.stderr
        bare = subprocess.run(
            [*argv, "--acknowledgement", ""],
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert bare.returncode == _NEEDS_ACKNOWLEDGEMENT, bare.stderr
        passed = subprocess.run(
            [*argv, "--acknowledgement", digest.group(1)],
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert passed.returncode == 0, passed.stderr

    def test_approve_refuses_without_a_terminal_and_writes_nothing(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        untracked = tmp_path / "untracked"
        result = subprocess.run(
            [
                str(_SYSTEM_PYTHON),
                str(SCRIPT_PATH),
                "approve",
                "--daemon-dir",
                str(tmp_path / "daemon"),
                "--project-root",
                str(project),
                "--from",
                "3.66.0",
                "--to",
                "4.0.0",
                "--untracked-dir",
                str(untracked),
            ],
            input="approve upgrade from v3.66.0 to v4.0.0\n",
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert result.returncode == 1
        assert "terminal" in result.stdout
        assert not untracked.exists()


class TestRecordInstallWithoutVenv:
    def test_record_install_writes_the_receipt_the_gate_then_accepts(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        untracked = tmp_path / "untracked"
        common = ["--daemon-dir", str(daemon_dir), "--project-root", str(project)]
        recorded = subprocess.run(
            [
                str(_SYSTEM_PYTHON),
                str(SCRIPT_PATH),
                "record-install",
                *common,
                "--untracked-dir",
                str(untracked),
                "--stamp",
                "v3.68.0",
            ],
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert recorded.returncode == 0, recorded.stderr
        rerun = subprocess.run(
            [
                str(_SYSTEM_PYTHON),
                str(SCRIPT_PATH),
                *common,
                "--untracked-dir",
                str(untracked),
                "--installed-stamp",
                "v3.68.0",
                "--to",
                "3.68.0",
                "--target-stamp",
                "v3.68.0",
            ],
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )
        assert rerun.returncode == 0, rerun.stderr
        assert "already installed" in rerun.stderr
