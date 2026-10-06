"""Plan 00495 Task 2.7: the status line shows "loading" while the daemon starts.

Real status-line forwarder runs against a real daemon whose controller init is
slowed (as in ``test_a_retried_hook_never_restarts_a_slow_start``), in a
throwaway project with its own socket and PID file: the first run starts the
daemon and must answer at once with the loading line; a retry while the daemon
is still initialising shows loading too; once it is up the real status path
answers. A start that has genuinely failed is never shown as loading.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.synthetic_traffic import SYNTHETIC_SOURCE_FIELD, TEST_PROBE
from tests.daemon_teardown import stop_daemons_of
from tests.integration.test_a_retried_hook_never_restarts_a_slow_start import (
    _INIT_DELAY_SECONDS,
    _slow_project,
)
from tests.integration.test_init_sh_pretooluse_fail_closed import BASH, _stdin_text

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOADING = "⏳ hooks daemon loading…"

#: Well under the 15 s start deadline, and under the slowed init.
_FIRST_ANSWER_BUDGET_SECONDS = 4.0


@pytest.fixture
def sandbox() -> Iterator[Path]:
    """A directory short enough for AF_UNIX paths; its project's daemons are
    stopped through the verified path afterwards."""
    base = Path(tempfile.mkdtemp(prefix="hd-status-"))
    try:
        yield base
    finally:
        project = base / "p"
        if project.exists():
            stop_daemons_of(project, grace_seconds=Timeout.PROCESS_DEATH_WAIT)
        shutil.rmtree(base)


def _status_hook_body() -> str:
    """The tracked status-line forwarder minus its ``source init.sh`` line."""
    text = (_REPO_ROOT / ".claude" / "hooks" / "status-line").read_text()
    marker = 'source "$SCRIPT_DIR/../init.sh"\n'
    return text.split(marker, 1)[1]


def _status_hook(
    project: Path, env: dict[str, str], python: Path, prelude: str = ""
) -> tuple[str, int, float]:
    """One status-line run; returns its stdout, exit code and elapsed seconds."""
    script = (
        f"source .claude/init.sh\nPYTHON_CMD={python}\n"
        "validate_venv() { return 0; }\n"
        "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
        f"{prelude}{_status_hook_body()}"
    )
    began = time.monotonic()
    result = subprocess.run(
        [BASH, "-c", script],
        cwd=project,
        env=env,
        input=_stdin_text({"hook_event_name": "Status", SYNTHETIC_SOURCE_FIELD: TEST_PROBE}),
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    return result.stdout.strip(), result.returncode, time.monotonic() - began


def test_status_line_answers_loading_at_once_while_the_daemon_starts(sandbox: Path) -> None:
    project, python, pid_path, env = _slow_project(sandbox, in_container=False)

    out, code, elapsed = _status_hook(project, env, python)
    assert (out, code) == (_LOADING, 0)
    assert elapsed < _FIRST_ANSWER_BUDGET_SECONDS, elapsed

    retry_out, retry_code, retry_elapsed = _status_hook(project, env, python)
    assert (retry_out, retry_code) == (_LOADING, 0)
    assert retry_elapsed < _FIRST_ANSWER_BUDGET_SECONDS, retry_elapsed

    # The daemon finishes starting in the background; the line then stops
    # being the loading line.
    end = time.monotonic() + _INIT_DELAY_SECONDS + Timeout.DAEMON_START_BUDGET_SEC
    answered = _LOADING
    while answered == _LOADING and time.monotonic() < end:
        time.sleep(0.5)
        answered, _code, _elapsed = _status_hook(project, env, python)
    assert answered != _LOADING
    assert pid_path.exists()


def test_a_start_that_failed_is_not_shown_as_loading(sandbox: Path) -> None:
    """A launcher that has finished with no daemon alive is a failure."""
    project, _python, _pid_path, env = _slow_project(sandbox, in_container=False)
    failing = sandbox / "failing-python"
    failing.write_text("#!/bin/bash\necho 'launcher failed' >&2\nexit 1\n")
    failing.chmod(0o755)

    out, code, _elapsed = _status_hook(project, env, failing)

    assert out == "⚠️ DAEMON FAILED"
    assert code == 1


def test_init_sh_can_name_the_loading_text(sandbox: Path) -> None:
    project, python, _pid_path, env = _slow_project(sandbox, in_container=False)

    out, code, _elapsed = _status_hook(
        project, env, python, prelude='_HOOKS_DAEMON_STATUS_LOADING_TEXT="custom loading"\n'
    )

    assert (out, code) == ("custom loading", 0)
