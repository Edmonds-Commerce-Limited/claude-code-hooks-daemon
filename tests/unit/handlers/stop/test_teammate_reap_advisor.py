"""Unit tests for the Stop-time teammate-reap advisory (Plan 00419 Task 1.7).

**These fixtures are reconstructed from a CAPTURED payload, not invented.**
Plan 00419's N4 lesson was a handler written against an assumed payload shape,
so the ``background_tasks`` shape below was read off the real session record
before a line of handler existed. The observation is in this plan's
``JOURNAL/00419-Journal-26-09-16.md``: the ``/goal`` evaluator is itself a
prompt-based Stop hook, and its ``goal_status`` attachments quote the Stop
payload it was handed on both sides of the transition that N5 describes --

- seven entries, ``status: "running"``, which the evaluator itself classified
  as "'teammate' type tasks (sub-agents or parallel work), not OS processes",
  at a moment when ``harvest-background``, ``ps`` and ``ListAgents`` all agreed
  nothing was running; then
- ``background_tasks: []`` once each idle teammate had been ``TaskStop``ped.

So a registered-but-idle teammate DOES occupy the list, and reaping it DOES
empty the list. Those two facts are the whole basis for this handler, and they
are what the first three tests pin.

Three constraints follow from the contract
(``contracts/claude-code-hooks/Stop.json``) and the decision document
(``fable-niggle-remedies-decision.md``, Task 1.7):

1. An ABSENT ``background_tasks`` means "unknown", never "no tasks running" --
   so silence, never an advisory guessing at a count it was not given.
2. A PRESENT-but-empty list is the post-reap state and needs no nudge.
3. This handler fires on EVERY stop, so it must be rate-limited the way
   ``background_process_tracker`` is, and it must never construct a deny --
   nothing here changes when Claude Code allows a stop.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.stop.teammate_reap_advisor import (
    ADVISE_INTERVAL,
    TeammateReapAdvisorHandler,
)

#: The observed count in the captured record. Seven idle teammates, seven
#: entries -- kept as a named constant so the assertions below cannot drift
#: apart from the fixture they describe.
_CAPTURED_TASK_COUNT = 7


def _captured_task(index: int) -> dict[str, Any]:
    """One ``background_tasks`` entry in the captured shape.

    Field names are the contract's (``Stop.json``'s ``input_example``); the
    ``type``/``status`` VALUES are the ones the ``/goal`` evaluator reported
    seeing on the real payload.
    """
    return {
        "id": f"task-{index:03d}",
        "type": "teammate",
        "status": "running",
        "description": f"teammate {index}",
        "command": "",
    }


def _stop_payload(
    background_tasks: Any = None,
    *,
    include_field: bool = True,
    session_id: str = "captured-session",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "session_id": session_id,
    }
    if include_field:
        payload["background_tasks"] = background_tasks
    return payload


def _captured_payload(session_id: str = "captured-session") -> dict[str, Any]:
    return _stop_payload(
        [_captured_task(index) for index in range(1, _CAPTURED_TASK_COUNT + 1)],
        session_id=session_id,
    )


class TestMatchesTheCapturedShape:
    """What the real payload looked like, before and after the reap."""

    def test_matches_the_captured_seven_teammate_entries(self) -> None:
        """The pre-reap capture: seven registered-but-idle teammates."""
        assert TeammateReapAdvisorHandler().matches(_captured_payload()) is True

    def test_silent_on_the_captured_post_reap_empty_list(self) -> None:
        """The post-reap capture: ``background_tasks: []``, nothing to say."""
        assert TeammateReapAdvisorHandler().matches(_stop_payload([])) is False

    def test_silent_when_the_field_is_absent(self) -> None:
        """An absent list is UNKNOWN, never empty -- Stop.json says so outright."""
        assert TeammateReapAdvisorHandler().matches(_stop_payload(include_field=False)) is False

    def test_silent_when_the_field_is_not_a_list(self) -> None:
        """A payload that disagrees with the contract is not information either."""
        assert TeammateReapAdvisorHandler().matches(_stop_payload("7")) is False


class TestTheAdvisory:
    """What it says, and the one thing it can never do."""

    def test_names_the_count_and_the_remedy(self) -> None:
        result = TeammateReapAdvisorHandler().handle(_captured_payload())

        context = "\n".join(result.context)
        assert str(_CAPTURED_TASK_COUNT) in context
        assert "TaskStop" in context
        assert "/goal" in context

    def test_never_denies(self) -> None:
        """It changes no stop control. Remedy (1) is upstream, not here."""
        result = TeammateReapAdvisorHandler().handle(_captured_payload())

        assert result.decision == Decision.ALLOW
        assert not result.reason

    def test_the_source_declares_no_deny_path_at_all(self) -> None:
        """Belt and braces: a deny must be unreachable, not merely untaken.

        An assertion about one call is satisfied by a handler that denies on
        some other input. This reads the module's own source, the same way
        ``test_rule_parity.py`` discovers deny paths, so a deny branch added
        later fails here rather than reaching a client.
        """
        import inspect

        from claude_code_hooks_daemon.handlers.stop import teammate_reap_advisor

        source = inspect.getsource(teammate_reap_advisor)
        assert "Decision.DENY" not in source
        assert ".deny(" not in source


class TestRateLimiting:
    """Fires on every stop, so it must not speak on every stop."""

    def test_advises_on_the_first_stop_then_every_nth(self) -> None:
        handler = TeammateReapAdvisorHandler()
        payload = _captured_payload()

        spoke = [bool(handler.handle(payload).context) for _ in range(ADVISE_INTERVAL * 2)]

        assert spoke[0] is True
        assert not any(spoke[1:ADVISE_INTERVAL])
        assert spoke[ADVISE_INTERVAL] is True

    def test_each_session_is_counted_separately(self) -> None:
        """One session's chatter must not silence another's first warning."""
        handler = TeammateReapAdvisorHandler()

        assert handler.handle(_captured_payload(session_id="one")).context
        assert handler.handle(_captured_payload(session_id="two")).context


class TestRegistration:
    """Placement on the Stop chain, and the resident-guidance verdict."""

    def test_runs_ahead_of_the_terminal_catch_all(self) -> None:
        """A Stop handler after ``auto_continue_stop`` never runs on a blocked stop.

        ``tests/integration/test_stop_chain_terminal_shadowing.py`` denies that
        placement outright rather than accepting "reachable eventually".
        """
        assert TeammateReapAdvisorHandler().priority < Priority.AUTO_CONTINUE_STOP

    def test_is_not_terminal(self) -> None:
        """An advisory must never end the chain for the handlers behind it."""
        assert TeammateReapAdvisorHandler().terminal is False

    def test_is_enabled_by_default(self) -> None:
        assert TeammateReapAdvisorHandler().get_default_enabled() is True

    def test_carries_no_resident_guidance(self) -> None:
        """T4: the fire-time message is the whole advice.

        Recorded with its reason in
        ``tests/integration/test_claude_md_guidance_coverage.py``; asserted here
        so the two cannot silently disagree.
        """
        assert TeammateReapAdvisorHandler().get_claude_md() is None
