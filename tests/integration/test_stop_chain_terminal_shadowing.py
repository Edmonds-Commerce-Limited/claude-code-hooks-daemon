"""What actually runs on a Stop event (Plan 00236, DBF guard).

``auto_continue_stop`` sits at priority 10, is ``terminal=True``, and its
``matches()`` returns True for every Stop event except two narrow cases
(confirmed re-entry, and an AskUserQuestion turn). ``HandlerChain`` breaks the
moment a terminal handler matches, regardless of the decision it returns. So
EVERY Stop handler registered above priority 10 is shadowed on the ordinary
stop and runs only in that minority.

That is not obvious from the config, where five handlers appear under ``stop:``
looking equally live, and it is not visible in unit tests, which call each
handler directly. It cost a whole audit cohort a wrong verdict: Plan 00234
reported ``dismissive_language``/``hedging_language`` as "double-firing" with
their Stop twins, when a live chain trace showed only the nitpick pseudo-event
leg running and the Stop twins never executing at all. The prescribed fix —
drop the ``stop:1/1`` nitpick trigger — would have deleted the copy that works
and kept the copy that does not.

So this file pins the reachable set as OBSERVABLE BEHAVIOUR. If a future change
makes a Stop advisory reachable (or unreachable), a test fails and says which.
Adding a Stop handler above priority 10 and expecting it to fire is the mistake
this guard exists to surface at test time rather than in production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController

# Text that BOTH language detectors match: "pre-existing"/"out of scope" are
# dismissive, "probably" is hedging. Prefixed with a valid stop explanation so
# auto_continue_stop ALLOWS — the point is that it still terminates the chain.
_TRANSCRIPT_TEXT = (
    "STOPPING BECAUSE: work complete. The remaining failure is probably "
    "pre-existing and out of scope."
)

# The Stop-event detectors shout in capitals; the nitpick pseudo-event handlers
# use sentence case. That difference is how a response reveals which leg ran.
_STOP_HANDLER_SIGNATURES = ("DISMISSIVE LANGUAGE DETECTED", "HEDGING LANGUAGE DETECTED")


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
    """The advisory handlers behind auto_continue_stop do not run."""

    def teardown_method(self) -> None:
        ProjectContext.reset()

    def _dispatch(self, tmp_path: Path, *, terminal_enabled: bool = True) -> dict[str, Any]:
        workspace = _make_workspace(tmp_path)
        transcript = _make_transcript(tmp_path)

        controller = DaemonController()
        with _mock_git_subprocess():
            controller.initialise(
                handler_config={
                    "stop": {
                        "auto_continue_stop": {"enabled": terminal_enabled, "priority": 10},
                        "dismissive_language_detector": {"enabled": True, "priority": 58},
                        "hedging_language_detector": {"enabled": True, "priority": 30},
                    }
                },
                workspace_root=workspace,
            )

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

    def test_stop_advisories_above_priority_10_are_shadowed(self, tmp_path: Path) -> None:
        """Enabled, matching, and silent — because a terminal handler ran first.

        Both detectors are enabled and the transcript contains phrases each of
        them matches. Neither reaches the response.
        """
        response = self._dispatch(tmp_path)

        rendered = json.dumps(response)
        for signature in _STOP_HANDLER_SIGNATURES:
            assert signature not in rendered, (
                f"{signature!r} appeared, so a Stop advisory above priority 10 now runs. "
                "If that is intended, the nitpick pseudo-event's stop:1/1 trigger now "
                "genuinely duplicates it and one of the two must go — see this module's "
                "docstring before deleting either."
            )

    def test_the_advisories_do_fire_once_the_shadow_is_removed(self, tmp_path: Path) -> None:
        """Proves the test above fails for the right reason.

        An absence assertion is worthless if the fixture could never produce
        the thing it asserts is absent — a typo'd transcript or a broken
        dispatch would pass it just as happily. Removing the terminal handler
        and watching the very same transcript produce the signatures shows the
        shadowing is what suppresses them.
        """
        response = self._dispatch(tmp_path, terminal_enabled=False)

        rendered = json.dumps(response)
        assert any(signature in rendered for signature in _STOP_HANDLER_SIGNATURES), (
            "Neither detector fired even with the terminal handler disabled — "
            f"the fixture no longer exercises them. Response: {rendered[:400]}"
        )
