"""The Stop probe the debugging docs teach is blocked, as they say it is (Plan 00466 N12).

``CLAUDE/DEBUGGING_STOP_HOOK.md`` and the ``transcript-inspector`` agent tell a
reader to pipe a Stop payload into ``.claude/hooks/stop`` and expect
``{"decision":"block"}`` from ``auto_continue_stop``. That handler is scoped
MAIN, and a probe marked ``synthetic_source`` is refused by every MAIN- or
SUB-scoped handler unless it names its thread with ``probe_as``. Measured
before the fix: the marked payload answered ``{}``, and the docs read ``{}``
as "the hook is broken". Leaving the payload unmarked instead put a
fabricated stop in the verdict log as a real agent's.

So this test takes the payload out of each document, rather than a copy of it,
and sends it through the production wrapper. A document that drops the
marker fails the guard in ``tests/integration``. A document that drops
``probe_as`` fails here.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    PROBE_AS_FIELD,
    SYNTHETIC_SOURCE_FIELD,
)
from tests.acceptance.conftest import wrapper_subprocess_env

REPO_ROOT = Path(__file__).resolve().parents[2]
STOP_HOOK = REPO_ROOT / ".claude" / "hooks" / "stop"

#: Every document that teaches the Stop probe.
DOCUMENTS = (
    REPO_ROOT / "CLAUDE" / "DEBUGGING_STOP_HOOK.md",
    REPO_ROOT / ".claude" / "agents" / "transcript-inspector.md",
)

#: `echo '<payload>' | [bash ]<path>/.claude/hooks/stop` on one line.
_STOP_PROBE = re.compile(
    r"echo '(?P<payload>\{[^']*\})'\s*\|\s*(?:bash\s+)?\S*\.claude/hooks/stop\b"
)

_EXIT_HARD_BLOCK = 2

#: auto_continue_stop's rule for a stop with no STOPPING BECAUSE: explanation.
_NO_REASON_RULE = "R-STOP-NO-REASON"


def _documented_payload(document: Path) -> dict[str, object]:
    match = _STOP_PROBE.search(document.read_text(encoding="utf-8"))
    assert match is not None, f"{document} no longer shows the Stop probe this test runs"
    payload: dict[str, object] = json.loads(match.group("payload"))
    return payload


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_the_documented_payload_is_a_marked_main_thread_probe(document: Path) -> None:
    """Cheap, and says which half is missing before the live run does."""
    payload = _documented_payload(document)
    assert payload[SYNTHETIC_SOURCE_FIELD] == MANUAL_PROBE
    assert payload[PROBE_AS_FIELD] == "main"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_the_documented_stop_probe_is_blocked_by_auto_continue_stop(
    document: Path, daemon_socket: Path, tmp_path: Path
) -> None:
    """The documented payload, plus an isolated ``cwd`` and nothing else.

    The ``cwd`` is the one addition, for the reason
    ``test_stop_hook_hard_block`` gives: ``release_blocker`` sits ahead of
    ``auto_continue_stop`` and matches a modified release file, so a
    repo-rooted ``cwd`` would hand this block to a different handler whenever
    the tree is dirty. The rule id pins the handler.
    """
    hook_input = {**_documented_payload(document), "cwd": str(tmp_path)}

    result = subprocess.run(
        ["bash", str(STOP_HOOK)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC,
        check=False,
        env=wrapper_subprocess_env(daemon_socket),
    )

    response = json.loads(result.stdout.strip() or "{}")
    assert response.get("decision") == "block", (
        f"the documented Stop probe must be blocked; got exit={result.returncode}, "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert _NO_REASON_RULE in str(response.get("reason", ""))
    assert result.returncode == _EXIT_HARD_BLOCK
