"""Plan 00416 Task 2.3 — one collector, two callers.

`hooks-daemon session-actions` prints the must-do list; the
`session_actions_directive` SessionStart handler counts it to decide whether
the supervisor should type a directive at all. Those two answers MUST agree:
the directive's whole content is "run that command", so a directive that
fires while the command reports nothing would teach the agent to ignore the
next one — the precise failure Plan 00416 exists to fix.

They agree by construction rather than by review: both call the function
below, and this file pins that the CLI has no collector of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils.session_action_items import (
    SessionActionItem,
    collect_session_action_items,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestTheCliUsesThisCollector:
    def test_the_cli_delegates_rather_than_duplicating(self) -> None:
        from claude_code_hooks_daemon.daemon import cli

        assert cli._collect_session_action_entries is collect_session_action_items


class TestAgainstTheRealHandlerPackage:
    """The anti-inflation guarantee, end to end.

    A handler earns ACTION_REQUIRED only by implementing a verifier that is
    CURRENTLY failing. This repository's own session is healthy, so the
    honest answer here is an empty list — and an empty list is the result
    that proves the mechanism is not simply tagging everything.
    """

    def test_a_healthy_repo_has_nothing_to_action(self) -> None:
        assert collect_session_action_items(_REPO_ROOT) == []

    def test_an_unresolvable_project_root_is_not_an_error(self) -> None:
        assert collect_session_action_items(None) == []


class TestTheItemShape:
    def test_it_carries_what_a_report_needs_and_no_prose(self) -> None:
        item = SessionActionItem(
            config_key="some_handler",
            class_name="SomeHandler",
            handler_name="some-handler",
        )
        assert (item.config_key, item.class_name, item.handler_name) == (
            "some_handler",
            "SomeHandler",
            "some-handler",
        )

    def test_a_failing_verifier_is_collected(self, monkeypatch: Any) -> None:
        # Monkeypatch a real shipped handler's verifier to fail, the same way
        # the CLI's own test drives the positive case, and assert it surfaces.
        from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
            ProjectHandlerLoadCheckerHandler,
        )

        monkeypatch.setattr(
            ProjectHandlerLoadCheckerHandler, "verify_still_needed", lambda _self: True
        )
        items = collect_session_action_items(_REPO_ROOT)
        assert [item.config_key for item in items] == ["project_handler_load_checker"]
