"""Plan 00466 N59 — a heartbeat is stopped only while its pid is still the heartbeat.

``scripts/install/venv.sh``'s heartbeat ends on its own once the path it
touches is gone, and its pid is then free for any process to reuse, minutes
before ``venv_heartbeat_stop`` runs. The stop therefore signals only a pid
that still has the parent ``venv_heartbeat_start`` recorded.

``_venv_parent_of`` is the twin of ``resolve_venv.sh``'s ``_rv_parent_of``
(each library must stand alone), so this file also holds the two to the same
answer. Every process signalled here is one this harness started.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VENV_SH: Final[Path] = REPO_ROOT / "scripts" / "install" / "venv.sh"
RESOLVE_VENV_SH: Final[Path] = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 60
#: Above Linux's default pid_max, so no process can have it.
_NONEXISTENT_PID: Final[int] = 2**22 + 7


def _run(script: str) -> dict[str, str]:
    """Source venv.sh and resolve_venv.sh, run ``script``, parse its key=value lines."""
    ran = subprocess.run(
        [BASH, "-c", f'set -u\n. "{VENV_SH}"\n. "{RESOLVE_VENV_SH}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    fields = dict(line.split("=", 1) for line in ran.stdout.splitlines() if "=" in line)
    fields["stderr"] = ran.stderr
    return fields


class TestTheTwinParentReadersAgree:
    def test_both_name_this_shell_as_its_childs_parent(self) -> None:
        fields = _run(
            "sleep 30 & child=$!\n"
            'echo "venv=$(_venv_parent_of "$child")"\n'
            'echo "rv=$(_rv_parent_of "$child")"\n'
            'echo "shell=$$"\n'
            'kill "$child"'
        )

        assert fields["venv"] == fields["rv"] == fields["shell"], fields["stderr"]

    def test_both_fail_for_a_pid_with_no_process(self) -> None:
        fields = _run(
            f'if _venv_parent_of {_NONEXISTENT_PID}; then echo "venv=found"; '
            'else echo "venv=gone"; fi\n'
            f'if _rv_parent_of {_NONEXISTENT_PID}; then echo "rv=found"; '
            'else echo "rv=gone"; fi'
        )

        assert fields["venv"] == fields["rv"] == "gone"


class TestAHeartbeatIsStoppedOnlyWhileItIsStillTheHeartbeat:
    def test_a_running_heartbeat_is_stopped(self, tmp_path: Path) -> None:
        target = tmp_path / "lock"
        target.mkdir()

        fields = _run(
            f'venv_heartbeat_start "{target}" "{tmp_path / "hb.log"}"\n'
            'hb="$VENV_HEARTBEAT_PID"\n'
            'echo "recorded=$VENV_HEARTBEAT_PARENT"\n'
            'echo "shell=$$"\n'
            'venv_heartbeat_stop "$hb" "$VENV_HEARTBEAT_PARENT"\n'
            'if kill -0 "$hb" 2>&1; then echo "alive=yes"; else echo "alive=no"; fi'
        )

        assert fields["recorded"] == fields["shell"], fields["stderr"]
        assert fields["alive"] == "no"

    def test_a_pid_now_held_by_another_process_is_not_signalled(self, tmp_path: Path) -> None:
        # The stand-in for a process that reused the heartbeat's pid: a sleep
        # whose parent is another shell, not the one that recorded the parent.
        # Its keeper reports how it ended. The first fatal signal decides the
        # status, so 143 means the stop's SIGTERM reached it and 137 means only
        # this harness's own SIGKILL, sent after the stop, did.
        standin_file = tmp_path / "standin"
        status_file = tmp_path / "status"
        fields = _run(
            f'bash -c \'sleep 30 & s=$!; echo $s > "{standin_file}"; wait $s; '
            f'echo $? > "{status_file}"\' &\n'
            "keeper=$!\n"
            f'until [ -s "{standin_file}" ]; do sleep 0.05; done\n'
            f'standin="$(cat "{standin_file}")"\n'
            'venv_heartbeat_stop "$standin" "$$"\n'
            'kill -KILL "$standin"\n'
            'wait "$keeper"\n'
            f'echo "status=$(cat "{status_file}")"'
        )

        assert fields["status"] == "137", fields["stderr"]

    def test_a_heartbeat_with_no_recorded_parent_is_not_signalled(self, tmp_path: Path) -> None:
        fields = _run(
            "sleep 30 & child=$!\n"
            'venv_heartbeat_stop "$child" ""\n'
            'if kill -0 "$child" 2>&1; then echo "alive=yes"; else echo "alive=no"; fi\n'
            'kill "$child"'
        )

        assert fields["alive"] == "yes", fields["stderr"]
