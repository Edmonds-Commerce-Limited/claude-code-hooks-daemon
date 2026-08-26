"""Every handler that can DENY must prove it denies, in the release playbook.

Plan 00260. `get_acceptance_tests()` feeds `generate-playbook`, which is
executed as a BLOCKING gate before every release (CLAUDE/development/
RELEASING.md Step 12). A handler contributing no DENY-expecting test is never
verified to actually BLOCK anything by that gate — only to stay out of the way.

**"Every handler has at least one acceptance test" is NOT the property worth
enforcing.** It is already true: all 84 concrete handlers return at least one.
A guard asserting it would have passed on the day it was written and caught
nothing thereafter, which is the failure mode this project names explicitly
about the magic-value checker — a rule that cannot fail is a rule nobody keeps.

The property that CAN fail is negative-case coverage: a handler whose whole
purpose is to deny, whose playbook entries only ever exercise the allow path.
That is a real hole, it is invisible in a green suite, and it is exactly what a
release gate is supposed to close.

**Why an exemption list rather than a blanket rule.** Some deny paths genuinely
cannot be exercised from a Claude Code session, and pretending otherwise would
produce a guard that fails for correct code until someone switches it off. Each
exemption below names the specific reason. The list is checked for staleness in
both directions, so an exemption cannot outlive the condition that justified it.

Modelled on `test_claude_md_guidance_coverage.py`, which does the same job for
`get_claude_md()` and replaced a per-release sub-agent sweep that re-derived the
same verdicts by hand every time (Plan 00203).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core.handler import Handler

#: Source marker meaning "this handler has a code path that denies a tool call".
_DENY_MARKER = "Decision.DENY"

#: Substring identifying a deny expectation on an AcceptanceTest, compared
#: case-insensitively against `str(expected_decision)` so it works whether the
#: field holds the enum or its value.
_DENY_EXPECTATION = "deny"

#: Handlers that CAN deny but cannot carry a deny-expecting acceptance test.
#: Every entry states why. Anything not listed here must prove it denies.
_EXEMPT_FROM_DENY_TEST: dict[str, str] = {
    "AutoApproveReadsHandler": (
        "its DENY is an explicitly defensive branch that `matches()` makes "
        "unreachable -- the handler only matches read-only tools, so `handle()` "
        "cannot receive anything else. A playbook cannot trigger a branch that "
        "exists to fail fast if the impossible happens."
    ),
    "PlanQaCommitGateHandler": (
        "denies only under `commit_gate_mode: block`; the shipped default is "
        "`warn`, so a playbook running the default configuration cannot reach "
        "the deny path. The warn path IS covered."
    ),
    "VerificationResultGateHandler": (
        "denies only under `mode: block`; the shipped default is `warn` -- a "
        "deliberate warn-first rollout mirroring PlanQaCommitGateHandler, so a "
        "playbook running the default configuration cannot reach the deny path. "
        "The warn path IS covered by its advisory acceptance tests."
    ),
    "AutoContinueStopHandler": (
        "the Stop hook's block is a session-lifecycle event, not a tool call, so "
        "it cannot be driven from a playbook step. It is covered instead by "
        "tests/acceptance/test_stop_hook_hard_block.py, which invokes the "
        "production `.claude/hooks/stop` wrapper as a subprocess and asserts the "
        "exit-2 + stderr contract directly."
    ),
    "NpmCommandHandler": (
        "its acceptance test's expectation is config-conditional -- "
        "`Decision.DENY if self.has_llm_commands else Decision.ALLOW` -- so it "
        "DOES assert a deny in a project that defines `llm:` scripts in "
        "package.json. This repository defines none, so the expectation "
        "evaluates to ALLOW here. The test is correct; the verdict is simply "
        "not observable from this project's configuration."
    ),
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so every handler can be CONSTRUCTED.

    A handler that raises on construction would silently drop out of discovery,
    which is precisely the escape this file exists to prevent.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


def _discover_denying_handlers() -> dict[str, type[Handler]]:
    """Concrete handlers whose module contains a deny path."""
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


def _has_deny_expecting_test(handler_class: type[Handler]) -> bool:
    """Whether this handler contributes at least one deny-expecting test."""
    tests = handler_class().get_acceptance_tests()
    return any(
        _DENY_EXPECTATION in str(getattr(test, "expected_decision", "")).lower() for test in tests
    )


class TestDiscoveryIsNotVacuous:
    """An empty discovery would make every assertion below pass while checking nothing."""

    def test_denying_handlers_are_found_at_all(self) -> None:
        assert _discover_denying_handlers(), (
            f"No denying handlers discovered. Either the marker {_DENY_MARKER!r} "
            "changed or discovery is broken -- either way the coverage checks "
            "below would pass without examining anything."
        )


class TestEveryDenyingHandlerProvesItDenies:
    """The property with teeth: a blocker must demonstrate blocking."""

    def test_no_denying_handler_lacks_a_deny_test(self) -> None:
        offenders = sorted(
            name
            for name, handler_class in _discover_denying_handlers().items()
            if name not in _EXEMPT_FROM_DENY_TEST and not _has_deny_expecting_test(handler_class)
        )

        assert not offenders, (
            "These handlers can DENY a tool call but contribute no "
            f"deny-expecting acceptance test: {offenders}.\n\n"
            "The release playbook therefore never verifies that they block "
            "anything -- only that they stay out of the way. Add an "
            "AcceptanceTest with expected_decision=Decision.DENY, or record the "
            "handler in _EXEMPT_FROM_DENY_TEST with a reason explaining why its "
            "deny path cannot be exercised from a session."
        )


class TestTheExemptionsCannotOutliveTheirReason:
    """An exemption list that is never re-checked becomes a list of stale excuses."""

    def test_every_exemption_names_a_real_denying_handler(self) -> None:
        stale = sorted(set(_EXEMPT_FROM_DENY_TEST) - set(_discover_denying_handlers()))

        assert not stale, (
            f"_EXEMPT_FROM_DENY_TEST names handlers that no longer deny (or no "
            f"longer exist): {stale}. Remove them -- an exemption for a handler "
            "that cannot deny is noise that hides the ones that matter."
        )

    @pytest.mark.parametrize("class_name", sorted(_EXEMPT_FROM_DENY_TEST))
    def test_every_exemption_carries_a_reason(self, class_name: str) -> None:
        reason = _EXEMPT_FROM_DENY_TEST[class_name]

        assert len(reason.split()) >= 12, (
            f"{class_name}: the exemption reason is too short to be an argument "
            f"({reason!r}). A bare exemption records that someone wanted the test "
            "to pass, not that the question was asked."
        )

    @pytest.mark.parametrize("class_name", sorted(_EXEMPT_FROM_DENY_TEST))
    def test_an_exemption_is_dropped_once_it_becomes_untrue(self, class_name: str) -> None:
        """If an exempt handler gains a deny test, the exemption must go.

        Without this the list only ever grows: a handler exempted years ago for
        a reason that has since been fixed keeps its excuse forever, and the
        next reader cannot tell which entries are still load-bearing.
        """
        handler_class = _discover_denying_handlers().get(class_name)
        if handler_class is None:
            pytest.skip("staleness is covered by test_every_exemption_names_a_real_denying_handler")

        assert not _has_deny_expecting_test(handler_class), (
            f"{class_name} now HAS a deny-expecting acceptance test, so its entry "
            "in _EXEMPT_FROM_DENY_TEST is obsolete. Delete the entry -- the "
            "handler no longer needs an excuse."
        )
