"""A handler's declared behaviour tag must not understate what its code does.

The generated `.claude/HOOKS-DAEMON.md` renders a **Behaviour** column per
handler. That column is not derived from behaviour: `docs_generator._detect_behavior`
reads a HAND-DECLARED tag off the instance (`blocking` > `advisory` > `context`,
falling back to terminal/non-terminal). Nothing compared that tag to the code,
and eight handlers had drifted -- five of them denying unconditionally while
advertising themselves as ADVISORY or NON-TERMINAL.

**Why this is a guard and not a cosmetic lint.** `scripts/qa/check_doc_truth.py`
consumes that same column as GROUND TRUTH (`_BLOCKING_BEHAVIOURS`) when deciding
whether prose claiming a handler "blocks" is a false claim. So the loop was
closed: tag -> generated doc -> checker validating prose against the doc, with
no step anywhere checking the tag against the source it describes. That file's
own docstring names this failure mode -- "circular consistency, not truth" --
which is precisely what it had become for these handlers.

The live harm is the plainer half: an agent reading the generated table is told
that `write_clobber_guard` and `plan_time_estimates` are advisory. Both deny.
Guidance that understates a blocker teaches agents to expect a warning and meet
a wall.

**Tags do not affect dispatch.** The front controller and event router never
read them, so correcting a tag changes documentation only -- verified before
these were changed, because a "documentation-only" fix that silently altered
handler ordering would be a far worse defect than the one being repaired.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core.handler import Handler


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so every handler can be CONSTRUCTED.

    A handler that raised on construction would silently drop out of discovery,
    which is precisely the escape this file exists to prevent.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


#: Source marker meaning "this handler has a code path that denies a tool call".
_DENY_MARKER = "Decision.DENY"

#: Tag values `_detect_behavior` renders as a behaviour that stops a tool call.
#: Mirrors `docs_generator`'s precedence, which checks `blocking` before
#: `advisory`, then falls back to the `terminal` flag.
_BLOCKING_TAG = "blocking"
_ADVISORY_TAG = "advisory"
_CONTEXT_TAG = "context"

#: Handlers that deny but whose rendered behaviour may legitimately understate
#: it. Every entry states why. Anything not listed must declare itself blocking.
_EXEMPT_FROM_BLOCKING_TAG: dict[str, str] = {
    "PlanQaCommitGateHandler": (
        "denies only under `commit_gate_mode: block`, and the shipped default in "
        "`.claude/hooks-daemon.yaml` is `warn` -- a deliberate warn-first rollout. "
        "Rendering it BLOCKING would overstate what a default installation does, "
        "which is the same class of untruth this guard exists to prevent, pointed "
        "the other way."
    ),
    "VerificationResultGateHandler": (
        "denies only under `mode: block`, and the shipped default is `warn` -- "
        "the same deliberate warn-first rollout as PlanQaCommitGateHandler. "
        "Rendering it BLOCKING would overstate what a default installation does."
    ),
    "NpmCommandHandler": (
        "its deny paths require `llm:` scripts in package.json; with none present "
        "the handler is advisory by design and says so in its own guidance. The "
        "rendered doc describes THIS project's active configuration, and this "
        "project defines no such scripts."
    ),
    "ValidateEslintOnWriteHandler": (
        "every one of its three deny paths sits behind the `has_llm_commands` "
        "gate; without `llm:` scripts it returns an advisory recommending "
        "`llm:lint`. Same reasoning as NpmCommandHandler -- capability is real "
        "but dormant in a project that has not opted in."
    ),
}


def _discover_handlers() -> dict[str, type[Handler]]:
    """Concrete handler classes, with whether their module contains a deny path."""
    found: dict[str, type[Handler]] = {}
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        module = importlib.import_module(module_name)
        try:
            source = inspect.getsource(module)
        except OSError:
            continue
        if _DENY_MARKER not in source:
            continue
        for attribute_name, attribute in vars(module).items():
            if (
                inspect.isclass(attribute)
                and issubclass(attribute, Handler)
                and attribute is not Handler
                and attribute.__module__ == module.__name__
                and not getattr(attribute, "__abstractmethods__", None)
            ):
                found[attribute_name] = attribute
    return found


def _declares_blocking(handler_class: type[Handler]) -> bool:
    """Whether this handler renders as BLOCKING/TERMINAL in the generated doc.

    Reproduces `docs_generator._detect_behavior`'s precedence rather than
    importing it, so that a change to the renderer surfaces here as a
    disagreement instead of being silently mirrored.
    """
    instance = handler_class()
    tags = [str(tag) for tag in getattr(instance, "tags", [])]
    if _BLOCKING_TAG in tags:
        return True
    if _ADVISORY_TAG in tags or _CONTEXT_TAG in tags:
        return False
    return bool(getattr(instance, "terminal", False))


class TestDiscoveryIsNotVacuous:
    """An empty discovery would make the assertions below pass while checking nothing."""

    def test_denying_handlers_are_found_at_all(self) -> None:
        assert _discover_handlers(), (
            f"No denying handlers discovered. Either the marker {_DENY_MARKER!r} "
            "changed or discovery broke -- either way the check below would pass "
            "without examining anything."
        )


class TestADenyingHandlerDeclaresItself:
    """The property with teeth: the doc must not advertise a blocker as advisory."""

    def test_no_denying_handler_renders_as_advisory(self) -> None:
        offenders = sorted(
            name
            for name, handler_class in _discover_handlers().items()
            if name not in _EXEMPT_FROM_BLOCKING_TAG and not _declares_blocking(handler_class)
        )

        assert not offenders, (
            "These handlers deny tool calls but render as ADVISORY/CONTEXT/"
            f"NON-TERMINAL in .claude/HOOKS-DAEMON.md: {offenders}.\n\n"
            "An agent reading that table is told a blocker will merely warn. Add "
            "HandlerTag.BLOCKING to the handler's tags, or record it in "
            "_EXEMPT_FROM_BLOCKING_TAG with a reason explaining why its deny path "
            "is genuinely not reachable in a default installation.\n\n"
            "Then regenerate the doc: bin/hooks-daemon generate-docs"
        )


class TestTheExemptionsCannotOutliveTheirReason:
    """An exemption list that is never re-checked becomes a list of stale excuses."""

    def test_every_exemption_names_a_real_denying_handler(self) -> None:
        stale = sorted(set(_EXEMPT_FROM_BLOCKING_TAG) - set(_discover_handlers()))

        assert not stale, (
            "_EXEMPT_FROM_BLOCKING_TAG names handlers that no longer deny (or no "
            f"longer exist): {stale}. Remove them -- an exemption for a handler "
            "that cannot deny hides the ones that matter."
        )

    @pytest.mark.parametrize("class_name", sorted(_EXEMPT_FROM_BLOCKING_TAG))
    def test_every_exemption_carries_a_reason(self, class_name: str) -> None:
        reason = _EXEMPT_FROM_BLOCKING_TAG[class_name]

        assert len(reason.split()) >= 12, (
            f"{class_name}: the exemption reason is too short to be an argument "
            f"({reason!r}). A bare exemption records that someone wanted the check "
            "to pass, not that the question was asked."
        )

    @pytest.mark.parametrize("class_name", sorted(_EXEMPT_FROM_BLOCKING_TAG))
    def test_an_exemption_is_dropped_once_it_becomes_untrue(self, class_name: str) -> None:
        """If an exempt handler starts declaring itself blocking, the exemption must go."""
        handler_class = _discover_handlers().get(class_name)
        if handler_class is None:
            pytest.skip("staleness is covered by test_every_exemption_names_a_real_denying_handler")

        assert not _declares_blocking(handler_class), (
            f"{class_name} now declares itself BLOCKING, so its entry in "
            "_EXEMPT_FROM_BLOCKING_TAG is obsolete. Delete the entry -- the "
            "handler no longer needs an excuse."
        )
