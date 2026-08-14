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


class TestThisProjectHasNotFallenIntoTheTrap:
    """Proving the hazard exists is not the same as checking the floor.

    The probe tests above establish that a Stop handler above priority 10 is
    unreachable. They say nothing about whether THIS repository has one — and
    it did. `ReleaseBlockerHandler`, a project handler whose job is to block
    the Stop event during a release until acceptance testing is done, was
    registered at priority 12 and had never fired.

    Its own docstring records why, and it was not a mistake by its author:

        Priority: 12 (before AutoContinueStop at 15)

    It WAS before AutoContinueStop. The daemon still ships 15 in its config
    template. This project's `.claude/hooks-daemon.yaml` later set it to 10,
    and that edit silently disabled a guard on the release process. Nothing
    noticed, because a shadowed handler and a handler that did not match
    produce identical output: nothing at all.

    So this reads the project's REAL Stop registrations — config plus project
    handlers — and fails by name on anything the terminal handler would
    swallow. A guard that documents a trap without checking the floor is half
    a guard.
    """

    def teardown_method(self) -> None:
        ProjectContext.reset()

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    def _registered_stop_handlers(self) -> list[Handler]:
        """Every Stop handler this project actually registers, in chain order.

        Built from the project's OWN config file, including
        ``project_handlers_config`` — omitting that made the first draft of
        this check pass vacuously against the very handler it was written for,
        because project handlers are only loaded when that argument is passed.
        A guard whose fixture cannot produce the failure is not a guard.
        """
        from claude_code_hooks_daemon.config.models import Config
        from claude_code_hooks_daemon.core.claude_md_injector import ClaudeMdInjector

        workspace = self._project_root()
        config = Config.load(workspace / ".claude" / "hooks-daemon.yaml")

        controller = DaemonController()
        # `initialise()` runs ClaudeMdInjector as a SIDE EFFECT, and this
        # fixture deliberately points workspace_root at the REAL repository so
        # it sees this project's own handlers. Left unpatched, the injector
        # rewrites the tracked CLAUDE.md from the handler set assembled here —
        # which omits pseudo_events_config, so it silently deleted both nitpick
        # handlers' guidance on every QA run. The chain is what this test wants;
        # the file write is not.
        with _mock_git_subprocess(), patch.object(ClaudeMdInjector, "inject", lambda _self: None):
            controller.initialise(
                handler_config=config.handlers.model_dump(),
                workspace_root=workspace,
                project_handlers_config=config.project_handlers,
            )

        return list(controller.get_router().get_chain(EventType.STOP).handlers)

    def test_the_fixture_sees_the_project_handlers(self) -> None:
        """Vacuity guard for the check below.

        The shadowing check is an absence assertion over a list. If that list
        silently excluded project handlers — as it did on the first draft —
        the check would pass while looking at half the chain.
        """
        names = {h.name for h in self._registered_stop_handlers()}

        assert len(names) > 1, (
            f"Only {names} registered on Stop. The fixture is not loading this "
            "project's handlers, so the shadowing check below has nothing to find."
        )

    def test_nothing_is_registered_after_the_handler_that_breaks_the_chain(self) -> None:
        """Shadowing is BEHAVIOURAL: only a terminal handler that MATCHES breaks it.

        "Anything after the lowest-numbered terminal handler" is the wrong
        test, and the first draft of this check used it and was wrong in the
        opposite direction — it flagged `auto_continue_stop` as shadowed by
        `release_blocker`, which sits at 8 and is terminal but matches only
        when release files are dirty. A narrowly-matching terminal handler is
        exactly how you place a guard AHEAD of the catch-all, and the check
        must not forbid the correct pattern while hunting the broken one.

        So the chain is walked in real priority order against an ordinary Stop
        event, with git stubbed to a clean tree so the release guard's own
        `matches()` is deterministic rather than depending on whatever happens
        to be uncommitted when the suite runs.
        """
        handlers = self._registered_stop_handlers()
        hook_input: dict[str, Any] = {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "session_id": "shadow-audit",
            "cwd": str(self._project_root()),
        }

        breaker: Handler | None = None
        after: list[tuple[str, int]] = []
        with patch("subprocess.run", return_value=Mock(returncode=0, stdout="", stderr="")):
            for handler in handlers:
                if breaker is not None:
                    after.append((handler.name, handler.priority))
                elif handler.terminal and handler.matches(hook_input):
                    breaker = handler

        assert breaker is not None, (
            "No terminal Stop handler matched an ordinary stop, so this check has "
            "nothing to measure against. If auto_continue_stop was deliberately "
            "removed, delete this test with it rather than leaving it green."
        )

        assert not after, (
            f"These Stop handlers are registered AFTER {breaker.name!r} (priority "
            f"{breaker.priority}), which is terminal and matches an ordinary stop, so "
            f"they can never run: {sorted(after)}.\n\n"
            "A handler in this state is silently disabled and indistinguishable from "
            "one that simply did not match — no error, no log, nothing. Either give it "
            "a priority below the breaking handler, or move its work to the `nitpick` "
            "pseudo-event, which fires per turn and is not shadowed.\n\n"
            "If a PROJECT handler is involved, check its priority against the value "
            "THIS project's config sets, not the value the daemon's template ships — "
            "that disagreement is what disabled release-blocker (Plan 00237)."
        )
