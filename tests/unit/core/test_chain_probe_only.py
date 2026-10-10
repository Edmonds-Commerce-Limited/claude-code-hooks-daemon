"""A probe can restrict the chain to one handler (Plan 00484 G11).

``hooks-daemon probe --only <handler>`` runs a single handler, so a detector can
be exercised without every other guard answering first. The restriction is
honoured only for a probe-class source: a real agent's payload cannot carry it,
because a field that switches guards off must not be reachable from traffic.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.result_types import Decision
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    PROBE_ONLY_FIELD,
    SYNTHETIC_SOURCE_FIELD,
)


class _Recorder(Handler):
    def __init__(self, handler_id: str) -> None:
        super().__init__(handler_id=handler_id, priority=Priority.DEFAULT, terminal=False)
        self.matches_called = False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        self.matches_called = True
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=[f"ran:{self.name}"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


def _event(**extra: Any) -> dict[str, Any]:
    return {"hook_event_name": "PreToolUse", "session_id": "s", **extra}


def _run(hook_input: dict[str, Any]) -> tuple[_Recorder, _Recorder]:
    wanted, other = _Recorder("wanted-handler"), _Recorder("other-handler")
    chain = HandlerChain()
    chain.add(wanted)
    chain.add(other)
    chain.execute(hook_input)
    return wanted, other


class TestProbeOnly:
    def test_only_the_named_handler_is_consulted(self) -> None:
        wanted, other = _run(
            _event(**{SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE, PROBE_ONLY_FIELD: "wanted_handler"})
        )
        assert wanted.matches_called
        assert not other.matches_called

    def test_without_the_field_every_handler_is_consulted(self) -> None:
        wanted, other = _run(_event(**{SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE}))
        assert wanted.matches_called
        assert other.matches_called

    def test_a_dashed_name_selects_the_handler_with_the_underscored_key(self) -> None:
        wanted, other = _run(
            _event(**{SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE, PROBE_ONLY_FIELD: "wanted-handler"})
        )
        assert wanted.matches_called
        assert not other.matches_called

    def test_real_traffic_cannot_restrict_the_chain(self) -> None:
        wanted, other = _run(_event(**{PROBE_ONLY_FIELD: "wanted_handler"}))
        assert wanted.matches_called
        assert other.matches_called

    def test_a_non_probe_synthetic_source_cannot_restrict_the_chain(self) -> None:
        wanted, other = _run(
            _event(**{SYNTHETIC_SOURCE_FIELD: "playbook-probe", PROBE_ONLY_FIELD: "wanted_handler"})
        )
        assert wanted.matches_called
        assert other.matches_called
