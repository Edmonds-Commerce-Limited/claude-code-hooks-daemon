"""Every handler's reachable decisions must serialise to a valid response.

``CLAUDE/CodeLifecycle/Features.md`` names
``tests/integration/test_all_handlers_response_validation.py`` as MANDATORY for
every new handler, and that file does perform genuine validation — it calls
``result.to_json(event)`` and asserts against the real schema via the
``response_validator`` fixture. What it does not do is grow. It is a hand-written
test class per handler, so it covers **12 of 84** concrete handler classes while
its own docstring says "ALL built-in handlers" and a section header says
"(17 handlers)". A list that must be remembered is blind to exactly the handler
this check exists to catch.

This file derives the population instead, so a new handler is covered on the
commit that adds it.

**What it can catch that a hand-written case cannot.** ``HookResult`` is a
Pydantic model, so field TYPES are validated at runtime — but it is
event-agnostic: one type serves all event types, and nothing at the type level
ties a handler to the decisions its event can express. ``SessionStart``,
``SessionEnd``, ``PreCompact``, ``Notification`` and both worktree events route
through ``_format_system_message_response``, which cannot express DENY or ASK. It
signals that by DELIBERATELY emitting ``{"decision": ...}`` so schema validation
rejects it — "This will fail schema validation as expected", in its own words.

That tripwire only ever fires where validation runs. ``validate_response`` was
not called in production at all — only ``server.py``'s docstring mentioned the
module — so a handler returning DENY on such an event was silently DOWNGRADED:
the deny dropped from the wire response, the handler believing it blocked, and
nothing blocked. That is the same class as the fixed defect where five blocking
handlers advertised themselves as advisory, pointed at the wire format instead of
at the docs.

``to_json`` now enforces the contract at runtime, so that particular downgrade
can no longer reach Claude Code silently. **This test is not thereby redundant**:
runtime enforcement fires when the response is already being built for a live
event, which is far too late to be a development signal, and its substitute —
though never weaker than what the handler asked for — is still not what the
handler intended. A failure here is a real defect to fix in the handler.

**Method.** Decisions are read from the class's own AST by
``core.decision_capability``, so a handler cannot pass by describing itself
accurately while doing something else. That module is shared with
``validate-project-handlers``, which applies the same question to a CLIENT's
project handlers — the one population no test in this repository can sweep.
``get_acceptance_tests`` is excluded there: its ``expected_decision=`` values are
assertions about behaviour, not decisions the handler returns — both worktree
handlers name ``Decision.ALLOW`` only there.

**Known limit, stated rather than hidden.** A decision reached through a helper
defined OUTSIDE the class body is not seen. The scan covers every method of the
class, which is where these handlers build their results; a module-level factory
would evade it. That is a narrower gap than a 12-entry list, not the absence of
one.
"""

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.constants.events import (
    STATUS_LINE_JSON_KEY,
    STATUS_SCHEMA_KEY,
    EventID,
    EventIDMeta,
)
from claude_code_hooks_daemon.core.decision_capability import decisions_referenced_by
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS, validate_response


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Several handlers resolve config during construction."""
    if not getattr(ProjectContext, "_initialized", False):
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


def _event_name_for_config_key(config_key: str) -> str | None:
    """Wire event name for a handler package directory, via the registry."""
    for meta in vars(EventID).values():
        if isinstance(meta, EventIDMeta) and meta.config_key == config_key:
            # Status is the one event whose schema key differs from its json_key.
            if meta.json_key == STATUS_LINE_JSON_KEY:
                return str(STATUS_SCHEMA_KEY)
            return str(meta.json_key)
    return None


def _handlers_with_event_names() -> list[tuple[str, type[Handler], str]]:
    """Every concrete handler paired with the wire event name it answers."""
    collected: list[tuple[str, type[Handler], str]] = []
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        # claude_code_hooks_daemon.handlers.<event_dir>.<module> — the length
        # guard skips the event PACKAGE itself, which has no module component.
        parts = module_name.split(".")
        if len(parts) < 4:
            continue
        event_name = _event_name_for_config_key(parts[2])
        if event_name is None or event_name not in RESPONSE_SCHEMAS:
            continue
        module = importlib.import_module(module_name)
        for attribute_name, attribute in vars(module).items():
            if (
                inspect.isclass(attribute)
                and issubclass(attribute, Handler)
                and attribute is not Handler
                and attribute.__module__ == module.__name__
                and not getattr(attribute, "__abstractmethods__", None)
            ):
                collected.append((attribute_name, attribute, event_name))
    return collected


def _handler_ids() -> list[str]:
    return [f"{name}[{event}]" for name, _cls, event in _handlers_with_event_names()]


class TestDiscoveryIsNotVacuous:
    """Every assertion below passes trivially on an empty sweep."""

    def test_the_sweep_reaches_the_shipped_handlers(self) -> None:
        discovered = _handlers_with_event_names()

        assert len(discovered) > 60, (
            f"only {len(discovered)} handler/event pairs discovered; the sweep is "
            "not reaching the shipped handlers so the checks below prove nothing"
        )

    def test_decisions_are_actually_extracted(self) -> None:
        """A broken AST scan would find no decisions and pass everything."""
        with_decisions = [
            name
            for name, cls, _event in _handlers_with_event_names()
            if decisions_referenced_by(cls)
        ]

        assert len(with_decisions) > 40, (
            f"only {len(with_decisions)} handlers yielded any decision; the AST "
            "scan is broken, so no handler is really being checked"
        )


class TestEveryReachableDecisionSerialisesValidly:
    """The property the hand-written suite covers for 12 of 84 handlers."""

    @pytest.mark.parametrize(
        "handler_name,handler_class,event_name",
        _handlers_with_event_names(),
        ids=_handler_ids(),
    )
    def test_each_decision_produces_a_schema_valid_response(
        self, handler_name: str, handler_class: type[Handler], event_name: str
    ) -> None:
        """Every decision the handler can return must serialise validly.

        A failure here means the handler returns a decision its event type
        cannot express. Because validation does not run in production, the live
        effect is not an error — it is the decision being silently dropped.
        """
        failures: list[str] = []

        for decision in sorted(decisions_referenced_by(handler_class), key=lambda d: d.value):
            result = HookResult(
                decision=decision,
                reason=f"{handler_name} reason" if decision != Decision.ALLOW else None,
            )
            response = result.to_json(event_name)
            errors = validate_response(event_name, response)
            if errors:
                failures.append(f"{decision.value} -> {response} :: {errors}")

        assert not failures, (
            f"{handler_name} answers {event_name}, which cannot express these "
            "decisions. The wire response is invalid, and since validate_response "
            "is not called in production the decision is silently DROPPED:\n  "
            + "\n  ".join(failures)
        )
