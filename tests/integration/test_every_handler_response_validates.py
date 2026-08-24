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
from claude_code_hooks_daemon.core.decision_capability import (
    decisions_referenced_by,
    undeliverable_decisions,
)
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


#: Handler directories deliberately outside the wire-event sweep, with the
#: reason. Pseudo-event handlers answer no event of their own; their decisions
#: are merged into the REAL triggering event, so they are swept against their
#: configured trigger events instead.
_NON_EVENT_PACKAGES = {"nitpick"}


def _concrete_handlers_in(package_dir: str) -> list[tuple[str, type[Handler]]]:
    """Every concrete handler class under one ``handlers/<dir>/`` package."""
    found: list[tuple[str, type[Handler]]] = []
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        parts = module_name.split(".")
        if len(parts) < 4 or parts[2] != package_dir:
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
                found.append((attribute_name, attribute))
    return found


def _handler_package_dirs() -> set[str]:
    """Every ``handlers/<dir>/`` package that contains a concrete handler."""
    return {
        module_name.split(".")[2]
        for _finder, module_name, _ispkg in pkgutil.walk_packages(
            handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
        )
        if len(module_name.split(".")) >= 4 and _concrete_handlers_in(module_name.split(".")[2])
    }


def _pseudo_event_handlers() -> list[tuple[str, type[Handler], str]]:
    """Pseudo-event handlers paired with each REAL event their triggers bind to.

    A pseudo-event handler's decision does not get its own response.
    ``merge_pseudo_results`` promotes a DENY (or an ASK over an ALLOW) into the
    REAL chain result, which is then serialised under the real event. So its
    deliverability is decided by the trigger's event type — and triggers are
    per-project configuration, not a property of the handler.
    """
    from claude_code_hooks_daemon.config import Config
    from claude_code_hooks_daemon.core.pseudo_event import PseudoEventTrigger

    config = Config.load(_project_root() / ".claude" / "hooks-daemon.yaml")
    collected: list[tuple[str, type[Handler], str]] = []
    for pseudo_name, pseudo_config in (config.pseudo_events or {}).items():
        handlers = _concrete_handlers_in(pseudo_name)
        for trigger_notation in pseudo_config.get("triggers", []):
            trigger = PseudoEventTrigger.from_string(trigger_notation)
            event_name = _event_name_for_config_key(trigger.event_type.name.lower())
            if event_name is None or event_name not in RESPONSE_SCHEMAS:
                continue
            collected.extend((name, cls, event_name) for name, cls in handlers)
    return collected


class TestNothingIsSilentlySkipped:
    """A sweep that skips quietly loses coverage without anyone noticing.

    ``_handlers_with_event_names`` maps a handler DIRECTORY to a wire event and
    ``continue``s when it cannot. That silence hid the ``nitpick`` package: two
    shipped handlers that the sweep never examined and never mentioned. Adding
    a pseudo-event would shrink coverage the same way, invisibly.
    """

    def test_every_handler_package_is_either_swept_or_justified(self) -> None:
        swept = {
            cls.__module__.split(".")[2] for _name, cls, _event in _handlers_with_event_names()
        }
        unaccounted = sorted(_handler_package_dirs() - swept - _NON_EVENT_PACKAGES)

        assert not unaccounted, (
            f"these handler packages contain concrete handlers that no sweep "
            f"examines, and were skipped without a word: {unaccounted}. Map the "
            "directory to its wire event, or record why it is exempt."
        )

    def test_the_justified_list_names_only_real_packages(self) -> None:
        """A stale entry would silently re-open the hole it was excusing."""
        stale = sorted(_NON_EVENT_PACKAGES - _handler_package_dirs())

        assert not stale, f"exemption names a package with no concrete handlers: {stale}"


class TestPseudoEventDecisionsAreDeliverableByTheirTriggers:
    """A pseudo handler's refusal is merged into the REAL event's response.

    ``merge_pseudo_results`` promotes DENY (and ASK over an ALLOW) into the real
    chain result. So a pseudo handler bound to ``session_start`` returning DENY
    is dropped exactly as a SessionStart handler would be — except that no sweep
    looked at it, because its directory maps to no event.

    Both shipped nitpick handlers return only ALLOW, so this passes today. It is
    the binding that makes it fragile: triggers are per-project CONFIG, so the
    same handler is deliverable under one project's config and dropped under
    another's. That is precisely the kind of correctness nobody re-derives by
    hand.
    """

    def test_the_pseudo_sweep_is_not_vacuous(self) -> None:
        """Green-on-arrival, so it must prove it looked at something."""
        discovered = _pseudo_event_handlers()

        assert discovered, (
            "no pseudo-event handler/trigger pairs discovered, so the check " "below proves nothing"
        )

    def test_each_pseudo_decision_survives_its_trigger_event(self) -> None:
        failures: list[str] = []
        for handler_name, handler_class, event_name in _pseudo_event_handlers():
            for decision in sorted(decisions_referenced_by(handler_class), key=lambda d: d.value):
                problems = undeliverable_decisions(handler_class, event_name)
                if problems:
                    failures.append(f"{handler_name} on trigger {event_name}: {problems}")
                    break
                result = HookResult(
                    decision=decision,
                    reason=f"{handler_name} reason" if decision != Decision.ALLOW else None,
                )
                errors = validate_response(event_name, result.to_json(event_name))
                if errors:
                    failures.append(f"{handler_name} on trigger {event_name}: {errors}")

        assert not failures, (
            "a pseudo-event handler returns a decision its TRIGGER event cannot "
            "deliver. merge_pseudo_results promotes it into that event's "
            "response, where it is silently dropped:\n  " + "\n  ".join(failures)
        )


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
