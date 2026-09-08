"""An ALLOW never ends the chain — for ANY handler (Plan 00242).

Plan 00241 found four handlers that were terminal while carrying an advisory
path, so their ALLOW ended dispatch and silently disabled every handler with a
higher priority number. Its guard (an AST rule: "a handler with a configurable
warn mode must not be terminal") covered the place the damage was
concentrated, but it was a narrow rule over a structural problem, and
``Handler.__init__`` still defaults ``terminal=True``.

Plan 00242 replaced the rule with an invariant in ``core/chain.py``:
terminality belongs to the DECISION. A deny from a terminal handler may end
the chain; an ALLOW continues to the next handler with its context kept. This
module proves the defect class cannot recur by dispatching a REAL PreToolUse
event through the real controller with a synthetic terminal-ALLOW probe
registered ahead of a real blocking handler, and asserting the block lands.

The probe is synthetic on purpose (see ``test_stop_chain_terminal_shadowing``
for the reasoning): the hazard is a property of the chain, not of any handler
that happens to exhibit it today.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController

_PROBE_SENTINEL = "TERMINAL-ALLOW-PROBE-DID-RUN-4c0b2e"
_PROBE_NAME = "terminal-allow-probe"
# Ahead of destructive_git (priority 10) — the region a terminal ALLOW used
# to shadow everything behind.
_PROBE_PRIORITY = 1


class _TerminalAllowProbe(Handler):
    """Terminal handler that matches everything and ALLOWs with context.

    Exactly the shape of the Plan 00241 defect: ``terminal=True`` (the
    default a handler acquires by saying nothing) with an ALLOW as its normal
    outcome.
    """

    def __init__(self) -> None:
        super().__init__(name=_PROBE_NAME, priority=_PROBE_PRIORITY, terminal=True)

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
        "  pre_tool_use:\n"
        "    destructive_git:\n"
        "      enabled: true\n"
        "      priority: 10\n"
    )
    return workspace


def _dispatch(tmp_path: Path, command: str) -> dict[str, Any]:
    """Dispatch a real Bash PreToolUse through the real chain, plus the probe."""
    workspace = _make_workspace(tmp_path)

    controller = DaemonController()
    # ``return_value`` (not ``side_effect``): initialise() resolves the git
    # remote through subprocess and fails fast on an empty answer.
    with patch("subprocess.run", return_value=Mock(returncode=0, stdout="/tmp/test\n")):
        controller.initialise(
            handler_config={"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
            workspace_root=workspace,
        )

    # Registered AFTER initialise, into the real router, so the probe is sorted
    # ahead of destructive_git in the same chain the daemon dispatches through.
    controller.get_router().register(EventType.PRE_TOOL_USE, _TerminalAllowProbe())

    return controller.process_request(
        {
            "event": "PreToolUse",
            "hook_input": {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "session_id": "allow-never-ends-the-chain",
                "cwd": str(workspace),
            },
        }
    )


class TestAllowNeverEndsTheChain:
    def teardown_method(self) -> None:
        ProjectContext.reset()

    def test_a_terminal_allow_ahead_of_a_blocker_does_not_disable_it(self, tmp_path: Path) -> None:
        """The Plan 00241 defect class, generalised: the later deny still lands."""
        response = _dispatch(tmp_path, "git reset --hard HEAD~1")

        output = response["hookSpecificOutput"]
        assert output["permissionDecision"] == "deny", response
        assert "destructive_git" in output["permissionDecisionReason"], (
            "The deny is not attributed to destructive_git — a terminal ALLOW at "
            f"priority {_PROBE_PRIORITY} disabled the blocker behind it. Response: {response}"
        )

    def test_the_probe_context_survives_alongside_the_deny(self, tmp_path: Path) -> None:
        """Continuing past the ALLOW keeps its context in the merged response."""
        response = _dispatch(tmp_path, "git reset --hard HEAD~1")

        assert _PROBE_SENTINEL in response["hookSpecificOutput"].get(
            "additionalContext", ""
        ), f"The probe's context was dropped from the merged response: {response}"

    def test_the_probe_runs_and_allows_a_benign_command(self, tmp_path: Path) -> None:
        """Vacuity guard: the probe is registered, matches, and ran."""
        response = _dispatch(tmp_path, "git status")

        output = response.get("hookSpecificOutput", {})
        assert output.get("permissionDecision") != "deny", response
        assert _PROBE_SENTINEL in output.get(
            "additionalContext", ""
        ), f"The probe never fired, so the tests above prove nothing: {response}"
