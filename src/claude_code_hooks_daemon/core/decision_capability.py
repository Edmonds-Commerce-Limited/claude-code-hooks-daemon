"""Can this event actually deliver this decision?

``to_json`` enforces the response contract at runtime and logs a refusal an
event cannot carry, and
``tests/integration/test_every_handler_response_validates.py`` sweeps every
built-in handler. Neither reaches a **project handler**: it lives in a client's
own repository, is a supported extension point, and no test in this repository
can see it. For a client the defect is not unreachable — it is undetectable
until it silently misfires in production.

This module is the shared pre-flight primitive that closes that gap, used by the
in-repo sweep and by ``validate-project-handlers`` so the two cannot drift.

**Why this asks about DELIVERY rather than schema conformance.** Only 13 events
have a bespoke response schema; the other 18 wired events fall back to
``_permissive_response_schema()``, which accepts any object. A DENY on
``TaskCreated`` therefore VALIDATES and is still dropped on the wire, so a
schema check alone would wave it through. ``REFUSAL_CAPABLE_EVENTS`` is the
stricter question, and its coverage is a superset: every schema-invalid
combination is a refusal the event cannot carry.
"""

import ast
import inspect
import textwrap

from claude_code_hooks_daemon.core.hook_result import REFUSAL_CAPABLE_EVENTS, Decision
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS

#: Decision references here describe what a test EXPECTS, not what the handler
#: returns. Scanning it would attribute ALLOW to handlers that never return it —
#: both worktree handlers name ``Decision.ALLOW`` only there.
_NON_RETURNING_METHOD = "get_acceptance_tests"

#: The name the Decision enum is referenced by in handler source.
_DECISION_ENUM = "Decision"

#: Result-class factories, and the wire decision each one produces. Most
#: handlers refuse through these rather than by naming the enum, so a scan that
#: looked only for ``Decision.DENY`` was blind to the commonest shape there is.
#: ``error``/``configuration_error`` are deliberately absent: both are fail-open
#: ALLOW, which every event can deliver, so naming them would add noise and
#: never a finding.
_FACTORY_DECISIONS: dict[str, Decision] = {
    "allow": Decision.ALLOW,
    "deny": Decision.DENY,
    "ask": Decision.ASK,
    "defer": Decision.DEFER,
}

#: A factory call counts only when the receiver NAMES a result class. Matched by
#: suffix rather than a fixed list, so the narrowed tiers, a future tier, and a
#: CLIENT's own ``HookResult`` subclass are all covered — and clients are the
#: population this module exists for. A same-named method reached through an
#: attribute (``self.policy.deny(...)``) is not a Name and never matches.
_RESULT_CLASS_SUFFIX = "Result"


def decisions_referenced_by(handler_class: type) -> set[Decision]:
    """Decisions the class's own methods reference.

    Read from the class's AST rather than from a declaration, so a handler
    cannot pass by describing itself accurately while doing something else.

    **Known limit, stated rather than hidden.** A decision reached through a
    helper defined OUTSIDE the class body is not seen. The scan covers every
    method of the class, which is where handlers build their results; a
    module-level factory would evade it.

    Args:
        handler_class: The handler class to scan.

    Returns:
        The set of Decision members referenced outside acceptance-test
        expectations. Empty if the source cannot be read.
    """
    try:
        source = inspect.getsource(handler_class)
    except (OSError, TypeError):
        # A dynamically-built class has no source file. That is not an error
        # worth failing a diagnostic command over — report nothing found.
        return set()

    # dedent, NOT cleandoc: cleandoc normalises DOCSTRING indentation and
    # corrupts the surrounding code, so the parse fails outright.
    tree = ast.parse(textwrap.dedent(source))
    found: set[Decision] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name == _NON_RETURNING_METHOD:
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Attribute)
                and isinstance(inner.value, ast.Name)
                and inner.value.id == _DECISION_ENUM
            ):
                member = getattr(Decision, inner.attr, None)
                if isinstance(member, Decision):
                    found.add(member)
                continue

            factory = _factory_decision(inner)
            if factory is not None:
                found.add(factory)
    return found


def _factory_decision(node: ast.AST) -> Decision | None:
    """The decision a ``SomeResult.deny(...)``-style call produces, if any.

    Args:
        node: Any node from the walk.

    Returns:
        The decision the factory produces, or None if this is not one.
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if not isinstance(node.func.value, ast.Name):
        return None
    if not node.func.value.id.endswith(_RESULT_CLASS_SUFFIX):
        return None
    return _FACTORY_DECISIONS.get(node.func.attr)


def undeliverable_decisions(handler_class: type, event_name: str) -> list[str]:
    """Decisions this handler can return that its event cannot deliver.

    Args:
        handler_class: The handler class to scan.
        event_name: The wire event name the handler answers.

    Returns:
        One human-readable line per undeliverable decision, naming the decision,
        the event and the consequence. Empty when every decision is deliverable,
        and empty for an unrecognised event — a diagnostic must not fail a
        handler because it does not recognise the event it answers.
    """
    if event_name not in RESPONSE_SCHEMAS:
        return []

    problems: list[str] = []
    for decision in sorted(decisions_referenced_by(handler_class), key=lambda d: d.value):
        capable = REFUSAL_CAPABLE_EVENTS.get(decision)
        if capable is None or event_name in capable:
            continue
        problems.append(
            f"returns '{decision.value}' but {event_name} cannot carry it on the wire, "
            f"so the decision is silently DROPPED and nothing is enforced"
        )
    return problems
