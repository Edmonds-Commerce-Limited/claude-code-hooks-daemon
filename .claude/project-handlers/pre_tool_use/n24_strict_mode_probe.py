"""N24 strict_mode acceptance probe — PROJECT-ONLY (Plan 00466 N24).

`daemon.strict_mode` used to read `self._config.strict_mode` in
`DaemonController.process_event`, and `self._config` is never populated by
the real daemon startup path (`_build_initialised_controller` builds a bare
`DaemonController()` and threads config slices into `initialise()` instead)
— so `strict_mode: true` in `hooks-daemon.yaml` never reached a live daemon.
That is fixed at the source (`daemon/controller.py`, `daemon/cli.py`), and
covered at the unit level by `tests/unit/daemon/test_controller.py` and
`tests/unit/daemon/test_cli_strict_mode_wiring.py`.

This handler exists so the fix can ALSO be proven against a real, running
daemon process end to end, without depending on an unrelated bug's
lifecycle: it deliberately raises, but only for a payload no real Claude
Code session ever sends (`synthetic_source: n24-probe`) — see
`daemon/synthetic_traffic.py` for the marker convention. The live check
itself is `tests/acceptance/test_n24_strict_mode_probe_socket.py`.

Deliberately NOT tagged `SAFETY`+`BLOCKING`: this probe isolates the
strict_mode plumbing (Part 1) from the independent SAFETY+BLOCKING
fail-closed-on-raise policy (Part 2, `core/chain.py`), which has its own
unit coverage and does not need a live probe to prove wiring.
"""

from typing import Any

from claude_code_hooks_daemon.core import (
    AcceptanceTest,
    Decision,
    GatingResult,
    RecommendedModel,
    TestType,
)
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.daemon.synthetic_traffic import event_synthetic_source

_PROBE_MARKER = "n24-probe"


class N24StrictModeProbeHandler(PreToolUseHandlerBase):
    """Deliberately raise for a payload only this project's own test suite sends."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="n24-strict-mode-probe",
            # PriorityRange.TEST_MIN..TEST_MAX (0-9) — reserved for exactly
            # this kind of test-only handler, unused by any library or
            # project handler in this project's own config.
            priority=5,
            terminal=False,
            tags=["project", "test"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match only the exact probe marker — never a real session."""
        return event_synthetic_source(hook_input) == _PROBE_MARKER

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Raise unconditionally, so the daemon's own exception path runs."""
        raise RuntimeError(
            "n24 probe: deliberate crash to verify daemon.strict_mode plumbing " "(Plan 00466 N24)"
        )

    def get_claude_md(self) -> str | None:
        return (
            "## n24_strict_mode_probe — deliberate crash for strict_mode acceptance testing\n\n"
            "Raises unconditionally for a PreToolUse payload carrying "
            "`synthetic_source: n24-probe`. No real Claude Code session ever "
            "sends that field, so this never fires in ordinary use. It exists "
            "to prove `daemon.strict_mode` reaches the live daemon "
            "end-to-end (Plan 00466 N24)."
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="N24 strict_mode probe (live-socket only)",
                command=(
                    "Send a PreToolUse Bash event carrying "
                    "synthetic_source: 'n24-probe' directly on the daemon socket."
                ),
                description=(
                    "Deliberately crashes to verify daemon.strict_mode plumbing "
                    "(Plan 00466 N24). With this project's own strict_mode: true, "
                    "the daemon denies rather than skipping the crashed handler."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"SYSTEM ERROR", r"n24-strict-mode-probe"],
                safety_notes=(
                    "matches() requires synthetic_source=='n24-probe', a field no "
                    "real Claude Code session sends -- a normal playbook dispatch "
                    "can never trigger the raise."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
                harness_cannot_produce=(
                    "Claude Code never sets synthetic_source on a real tool call; "
                    "see tests/acceptance/test_n24_strict_mode_probe_socket.py "
                    "for the live-socket coverage this replaces."
                ),
            ),
            AcceptanceTest(
                title="An ordinary command without the probe marker is unaffected",
                command="echo 'ordinary command'",
                dispatch_as_bash=True,
                description=(
                    "Near-miss negative case: matches() requires "
                    "synthetic_source=='n24-probe' exactly, so any real tool "
                    "call -- which never carries that field -- never reaches "
                    "the deliberate raise."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="echo only -- nothing executed depends on this handler.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
