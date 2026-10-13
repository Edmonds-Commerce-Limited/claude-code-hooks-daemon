"""Plan 00517 Task 3.2: the evidence shown for a venv the code cannot prove stale.

The running agent decides whether an UNPROVEN venv is safe to remove, so each
one is reported with the facts that decide it: the processes using it, its
interpreter and version, when it last changed, its slug and the view it
belongs to.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    VenvEvidence,
    VenvProcess,
    gather_venv_evidence,
    processes_using_venvs,
)


def _venv(root: Path, name: str, cfg: str | None = None) -> Path:
    venv = root / name
    (venv / "bin").mkdir(parents=True)
    if cfg is not None:
        (venv / "pyvenv.cfg").write_text(cfg)
    return venv


def _fake_process(
    proc_root: Path,
    pid: int,
    *,
    exe: Path | None = None,
    cwd: Path | None = None,
    argv: list[str] | None = None,
) -> None:
    proc = proc_root / str(pid)
    proc.mkdir(parents=True)
    if exe is not None:
        (proc / "exe").symlink_to(exe)
    if cwd is not None:
        (proc / "cwd").symlink_to(cwd)
    if argv is not None:
        (proc / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


class TestProcessesUsingVenvs:
    def test_exe_inside_the_venv_is_a_user(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-a-py311-aaaaaaaa")
        interpreter = venv / "bin" / "python"
        interpreter.write_text("")
        proc_root = tmp_path / "proc"
        _fake_process(proc_root, 4242, exe=interpreter, argv=["python", "-m", "x"])

        scan = processes_using_venvs([venv], proc_root)

        assert scan.users[venv] == [VenvProcess(pid=4242, via="exe", detail=str(interpreter))]

    def test_cwd_inside_the_venv_is_a_user(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-a-py311-aaaaaaaa")
        proc_root = tmp_path / "proc"
        _fake_process(proc_root, 7, cwd=venv / "bin")

        scan = processes_using_venvs([venv], proc_root)

        assert [(p.pid, p.via) for p in scan.users[venv]] == [(7, "cwd")]

    def test_argv0_naming_the_venv_is_a_user_though_exe_is_the_system_python(
        self, tmp_path: Path
    ) -> None:
        # A venv's bin/python is a symlink, so /proc/<pid>/exe shows the system
        # interpreter; argv[0] still names the venv path it was started by.
        venv = _venv(tmp_path, "venv-a-py311-aaaaaaaa")
        proc_root = tmp_path / "proc"
        _fake_process(
            proc_root,
            9,
            exe=Path(sys.executable).resolve(),
            argv=[str(venv / "bin" / "python"), "-m", "daemon"],
        )

        scan = processes_using_venvs([venv], proc_root)

        assert [(p.pid, p.via) for p in scan.users[venv]] == [(9, "argv0")]

    def test_a_path_only_in_a_later_argument_is_not_a_user(self, tmp_path: Path) -> None:
        # `prune-venvs --unproven <path>` itself names the venv; it must not
        # count as the venv being used or the command could never succeed.
        venv = _venv(tmp_path, "venv-a-py311-aaaaaaaa")
        proc_root = tmp_path / "proc"
        _fake_process(proc_root, 11, argv=["bash", "-c", f"prune-venvs --unproven {venv}"])

        assert processes_using_venvs([venv], proc_root).users[venv] == []

    def test_unrelated_and_unreadable_processes(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-a-py311-aaaaaaaa")
        proc_root = tmp_path / "proc"
        _fake_process(proc_root, 20, exe=Path("/usr/bin/python3"), argv=["python3"])
        (proc_root / "21").mkdir()  # nothing readable: counted, not guessed at
        (proc_root / "self").mkdir()  # not a pid

        scan = processes_using_venvs([venv], proc_root)

        assert scan.users[venv] == []
        assert scan.unreadable == 1

    def test_a_sibling_venv_with_a_common_prefix_is_not_matched(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-a")
        sibling = _venv(tmp_path, "venv-a-py311-aaaaaaaa")
        proc_root = tmp_path / "proc"
        _fake_process(proc_root, 30, argv=[str(sibling / "bin" / "python")])

        assert processes_using_venvs([venv], proc_root).users[venv] == []

    def test_a_real_process_started_through_the_venv_is_found(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-a-py311-aaaaaaaa")
        (venv / "bin" / "python").symlink_to(Path(sys.executable).resolve())
        child = subprocess.Popen(
            [str(venv / "bin" / "python"), "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            scan = processes_using_venvs([venv])
        finally:
            child.terminate()
            child.wait(timeout=10)

        assert child.pid in {p.pid for p in scan.users[venv]}


class TestGatherVenvEvidence:
    def test_reports_interpreter_version_age_slug_and_view(self, tmp_path: Path) -> None:
        venv = _venv(
            tmp_path,
            "venv-me-py311-aaaaaaaa",
            cfg="home = /usr/local/bin\nversion = 3.11.9\ninclude-system-site-packages = false\n",
        )
        os.utime(venv, (1_700_000_000, 1_700_000_000))

        (evidence,) = gather_venv_evidence([venv], "me", tmp_path / "proc-missing")

        assert evidence.path == venv
        assert evidence.slug == "me"
        assert evidence.view == "this view"
        assert evidence.interpreter == "/usr/local/bin"
        assert evidence.python_version == "3.11.9"
        assert evidence.modified == "2023-11-14T22:13:20Z"
        assert evidence.processes == ()

    def test_another_views_slug_is_named(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-them-py311-aaaaaaaa")

        (evidence,) = gather_venv_evidence([venv], "me", tmp_path / "proc-missing")

        assert evidence.view == "another view (slug 'them'; this view is 'me')"

    def test_a_name_without_a_slug_is_this_views(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-py311-aaaaaaaa")

        (evidence,) = gather_venv_evidence([venv], "me", tmp_path / "proc-missing")

        assert evidence.slug is None
        assert evidence.view == "this view (name carries no slug)"

    def test_missing_pyvenv_cfg_is_reported_unknown(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-aaaaaaaa")

        (evidence,) = gather_venv_evidence([venv], "me", tmp_path / "proc-missing")

        assert evidence.interpreter == "unknown (no readable pyvenv.cfg)"
        assert evidence.python_version == "unknown"

    def test_describe_lists_every_fact_and_the_removal_command(self, tmp_path: Path) -> None:
        venv = _venv(
            tmp_path, "venv-them-py311-aaaaaaaa", cfg="home = /usr/bin\nversion = 3.11.2\n"
        )
        proc_root = tmp_path / "proc"
        _fake_process(proc_root, 5, argv=[str(venv / "bin" / "python")])

        (evidence,) = gather_venv_evidence([venv], "me", proc_root)
        text = "\n".join(evidence.describe())

        assert str(venv) in text
        assert "pid 5" in text
        assert "3.11.2" in text
        assert "/usr/bin" in text
        assert "another view" in text
        assert "last modified" in text

    def test_describe_says_when_no_process_uses_it(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-aaaaaaaa")

        (evidence,) = gather_venv_evidence([venv], "me", tmp_path / "proc-missing")

        assert any("no process" in line for line in evidence.describe())

    def test_unreadable_processes_are_disclosed(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-aaaaaaaa")
        proc_root = tmp_path / "proc"
        (proc_root / "21").mkdir(parents=True)

        (evidence,) = gather_venv_evidence([venv], "me", proc_root)

        assert any("could not be read" in line for line in evidence.describe())

    def test_to_dict_is_json_ready(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-aaaaaaaa")
        (evidence,) = gather_venv_evidence([venv], "me", tmp_path / "proc-missing")

        payload = evidence.to_dict()

        assert payload["path"] == str(venv)
        assert payload["processes"] == []
        assert isinstance(evidence, VenvEvidence)


@pytest.mark.parametrize("pid_name", ["abc", "1x", ""])
def test_non_pid_entries_are_ignored(tmp_path: Path, pid_name: str) -> None:
    venv = _venv(tmp_path, "venv-me-py311-aaaaaaaa")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    if pid_name:
        (proc_root / pid_name).mkdir()

    scan = processes_using_venvs([venv], proc_root)

    assert scan.users[venv] == []
    assert scan.unreadable == 0
