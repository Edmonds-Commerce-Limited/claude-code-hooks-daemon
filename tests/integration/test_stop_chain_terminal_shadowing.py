"""What actually runs on a Stop event (Plan 00236, DBF guard).

``auto_continue_stop`` sits at priority 10, is ``terminal=True``, and its
``matches()`` returns True for every Stop event except two narrow cases
(confirmed re-entry, and an AskUserQuestion turn). ``HandlerChain`` breaks the
moment a terminal handler matches, **regardless of the decision it returns** —
so an ordinary ALLOW shadows the rest of the chain just as completely as a
deny. EVERY Stop handler registered above priority 10 is therefore dead on the
ordinary stop and runs only in that minority.

That is not obvious from the config, where the handlers under ``stop:`` all
look equally live, and it is invisible to unit tests, which call each handler
directly. It cost a whole audit cohort a wrong verdict: Plan 00234 reported
``dismissive_language``/``hedging_language`` as "double-firing" with their Stop
twins, when a live chain trace showed only the ``nitpick`` pseudo-event leg
running and the Stop twins never executing at all. The prescribed fix — drop
the ``stop:1/1`` nitpick trigger — would have deleted the copy that works and
kept the copy that does not. Plan 00237 deleted the Stop twins instead.

**This guard uses a synthetic probe, on purpose.** It was first written around
the two real shadowed handlers, which made it die with them: removing the dead
handlers would have removed the only evidence that the hazard exists, at
exactly the moment the tree looked clean. The hazard is a property of the
CHAIN, not of any handler, and it outlives every particular occupant — so the
probe is defined here, owned here, and cannot be deleted by tidying ``stop:``.
Do not "simplify" this file by pointing it at whatever real handlers happen to
be registered.

If you are adding a Stop handler and expecting it to fire, read
``test_a_probe_below_the_terminal_handler_does_run`` first: below priority 10
is the only place a Stop handler is reachable, and per-turn message auditing
belongs on the ``nitpick`` pseudo-event rather than here at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController

# A valid stop explanation, so auto_continue_stop ALLOWS. The point of the
# guard is that a benign ALLOW terminates the chain exactly as a deny does.
_TRANSCRIPT_TEXT = "STOPPING BECAUSE: work complete."

# Unique enough that it cannot collide with any real handler's output, so
# finding it in the response means the probe ran and nothing else can.
_PROBE_SENTINEL = "STOP-CHAIN-PROBE-DID-RUN-9d41f7"

# Deliberately NOT a HandlerID constant. The probe is a test fixture, not a
# shipped handler, and giving it an entry in constants/handlers.py would put a
# fake handler into the registry's known-keys set — where the config validator,
# the docs generator and the guidance-coverage table would all treat it as real.
_PROBE_NAME = "stop-chain-probe"

# Above auto_continue_stop's 10 — the shadowed region.
_SHADOWED_PRIORITY = 30
# Below it — the only reachable region for a Stop handler.
_REACHABLE_PRIORITY = 5


class _ProbeStopHandler(Handler):
    """Non-terminal Stop handler that matches everything and shouts.

    Deliberately has no matching logic of its own: a probe that could fail to
    match would turn a real shadowing regression into a green test. If this
    handler is silent, the chain is why.
    """

    def __init__(self, priority: int) -> None:
        super().__init__(name=_PROBE_NAME, priority=priority, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=[_PROBE_SENTINEL])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".claude").mkdir(parents=True)
    (workspace / ".git").mkdir()
    (workspace / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '1.0'\n"
        "daemon:\n"
        "  idle_timeout_seconds: 600\n"
        "  log_level: INFO\n"
        "handlers:\n"
        "  stop:\n"
        "    auto_continue_stop:\n"
        "      enabled: true\n"
        "      priority: 10\n"
    )
    return workspace


def _make_transcript(tmp_path: Path) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": _TRANSCRIPT_TEXT}],
                },
            }
        )
        + "\n"
    )
    return transcript


def _mock_git_subprocess() -> Any:
    """Stub git for initialise(). ``return_value``, not ``side_effect``.

    A fixed side_effect list runs out and raises StopIteration if initialise
    makes one more call than expected — a fixture failure that looks like a
    behavioural one.
    """
    return patch(
        "subprocess.run",
        return_value=Mock(returncode=0, stdout=b"/tmp/test\n"),
    )


class TestStopChainTerminalShadowing:
    """A Stop handler above priority 10 does not run. One below it does."""

    def teardown_method(self) -> None:
        ProjectContext.reset()

    def _dispatch(
        self,
        tmp_path: Path,
        *,
        probe_priority: int,
        terminal_enabled: bool = True,
    ) -> dict[str, Any]:
        """Dispatch a real Stop event through the real chain, plus the probe."""
        workspace = _make_workspace(tmp_path)
        transcript = _make_transcript(tmp_path)

        controller = DaemonController()
        with _mock_git_subprocess():
            controller.initialise(
                handler_config={
                    "stop": {
                        "auto_continue_stop": {"enabled": terminal_enabled, "priority": 10},
                    }
                },
                workspace_root=workspace,
            )

        # Registered AFTER initialise, into the real router, so the probe is
        # sorted into the same chain as the production handler and executed by
        # the same dispatch path. Nothing about the chain is simulated here.
        controller.get_router().register(EventType.STOP, _ProbeStopHandler(probe_priority))

        return controller.process_request(
            {
                "event": "Stop",
                "hook_input": {
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "transcript_path": str(transcript),
                    "session_id": "shadowing-test",
                    "cwd": str(workspace),
                },
            }
        )

    def test_a_stop_handler_above_priority_10_is_shadowed(self, tmp_path: Path) -> None:
        """Enabled, matching unconditionally, and still silent."""
        response = self._dispatch(tmp_path, probe_priority=_SHADOWED_PRIORITY)

        rendered = json.dumps(response)
        assert _PROBE_SENTINEL not in rendered, (
            f"A non-terminal Stop handler at priority {_SHADOWED_PRIORITY} reached the "
            "response, so the chain no longer breaks at auto_continue_stop. If that is "
            "intended, every handler moved off the Stop event on the strength of this "
            "shadowing (Plan 00237) can come back — read this module's docstring first."
        )

    def test_the_probe_does_run_once_the_shadow_is_removed(self, tmp_path: Path) -> None:
        """Proves the test above fails for the right reason.

        An absence assertion is worthless if the fixture could never produce
        the thing it asserts is absent — a broken dispatch or a probe that
        never registered would pass it just as happily. Same probe, same
        priority, terminal handler disabled.
        """
        response = self._dispatch(
            tmp_path, probe_priority=_SHADOWED_PRIORITY, terminal_enabled=False
        )

        rendered = json.dumps(response)
        assert _PROBE_SENTINEL in rendered, (
            "The probe did not fire even with the terminal handler disabled — the "
            f"fixture no longer exercises the Stop chain at all. Response: {rendered[:400]}"
        )

    def test_a_probe_below_the_terminal_handler_does_run(self, tmp_path: Path) -> None:
        """The shadow is about ORDERING, not about Stop handlers being broken.

        Same probe, same enabled terminal handler, priority 5 instead of 30.
        It runs, and its context survives into the response — so a Stop handler
        genuinely can work, and the boundary is exactly priority 10. Without
        this, the other two tests are consistent with 'Stop dispatch is simply
        broken', which would send the next reader hunting the wrong bug.
        """
        response = self._dispatch(tmp_path, probe_priority=_REACHABLE_PRIORITY)

        rendered = json.dumps(response)
        assert _PROBE_SENTINEL in rendered, (
            f"A Stop handler at priority {_REACHABLE_PRIORITY} — BELOW the terminal "
            "auto_continue_stop — did not reach the response. Its context should survive "
            f"the terminal handler's result. Response: {rendered[:400]}"
        )
