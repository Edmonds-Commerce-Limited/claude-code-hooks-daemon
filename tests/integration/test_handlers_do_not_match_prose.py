"""No handler may deny text that merely NAMES what it guards (Plan 00228).

One defect has recurred four times in this repository: a handler matches text
containing its trigger vocabulary instead of a command that does the thing.

- Plan 00222 — `pipe_blocker` read journal prose containing a truncating pipe
- Plan 00225 — the language detectors read a MENTIONED phrase as a USED one
- Plan 00227 — `plan_number_helper` fired on a plain `echo` of an English
  sentence
- Plan 00228 — `pipe_blocker` again, on a Python string literal inside a
  heredoc whose delimiter is quoted

Each was found by an agent hitting it mid-task, and each was fixed only where
it surfaced. Nothing asked the general question, so the class kept escaping —
and Plan 00138 was even written to fix one of these handlers and CLEARED the
rule that later produced instance three, by reasoning about which command
shapes satisfy it and never asking whether non-command text could.

SCOPE (Plan 00228, Decision 1). Every handler is in scope by DEFAULT, and the
handlers that match text deliberately are named below with a reason each. The
first draft of this plan proposed scoping by priority band instead; that was
measured and rejected, because `pipe_blocker` sits at 15 and the nitpick
detectors at 10 and 20 — a band-scoped guard would have exempted three of the
four instances it exists to catch. Priority encodes DISPATCH ORDER, not
consequence.

Default-in-scope is the point: a newly added handler is covered without anyone
remembering to add it.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision

_BASH_TOOL = "Bash"

# The fixture is a Bash tool call, so only PreToolUse handlers can meaningfully
# answer it. Matched against the module path, which mirrors the event type.
_PRE_TOOL_USE_PACKAGE = "pre_tool_use"

# Text that a shell will NOT execute, but which names guardrail vocabulary.
# Seeded from text that ACTUALLY provoked a denial in this repository, so the
# fixture cannot drift into unrealistic strings that pass while real prose fails.
_NON_EXECUTING_TEXT: dict[str, str] = {
    "prose naming the plan dir and the discovery idiom": (
        'echo "harmless text mentioning CLAUDE/Plan and the words ' 'sort and tail -1 together"'
    ),
    "prose describing a truncating pipe": (
        'echo "the pipe blocker denies a command piped to tail -20 because it truncates"'
    ),
    "a literal inside a quoted heredoc": (
        "cat > notes.py <<'PYEOF'\n"
        'CASES = [("alternation", "ls CLAUDE/Plan | sort | tail -1")]\n'
        "PYEOF"
    ),
    "prose naming a specific plan folder": (
        'echo "see CLAUDE/Plan/00163-plan-journalling for the journalling design"'
    ),
    "prose describing a stash policy": (
        'echo "this project blocks git stash because stashes get forgotten"'
    ),
}

# Handlers that match text DELIBERATELY. Each entry states why, because an
# exemption without a reason is indistinguishable from an unnoticed bug.
_DELIBERATE_TEXT_MATCHERS: dict[str, str] = {
    "DestructiveGitHandler": (
        "CLAUDE.md mandates full-command-string matching and forbids 'fixing' it: "
        "the acceptance suite verifies blocking handlers by embedding a dangerous "
        "command inside a string. Over-blocking costs one retry; under-blocking "
        "costs unrecoverable data."
    ),
    "SedBlockerHandler": (
        "Same rationale as destructive_git — a sed invocation quoted inside a "
        "shell script is still a sed invocation once that script runs."
    ),
    "SecurityAntipatternHandler": (
        "Plan 00225 Decision 2: a dangerous construct inside a quoted string can "
        "still execute, so a quoted-span exemption would be a one-character bypass."
    ),
    "SensitiveContentHandler": (
        "Plan 00225 Decision 2: a secret inside quotation marks is still a secret "
        "being written to disk."
    ),
    "GitStashHandler": (
        "Surfaced by this guard and investigated, NOT assumed: "
        "tests/unit/handlers/test_git_stash.py::test_matches_git_stash_in_echo_quotes "
        'asserts `echo "git stash"` must be blocked, and test_blocks_all_creation_'
        "variants repeats it. That is the CLAUDE.md-prescribed way the acceptance "
        "suite verifies a blocking handler — embed the command in a string. The "
        "existing tests are the specification, so exempting quoted spans here would "
        "have broken acceptance testing rather than fixed a false positive."
    ),
}


def _project_root() -> Path:
    """Return the repository root (this file is tests/integration/<name>.py)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so handlers reading it can be constructed."""
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


def _discover_handler_classes() -> dict[str, type[Handler]]:
    """Every concrete Handler subclass under the handlers package.

    Discovered rather than hardcoded — a hardcoded list is blind to exactly the
    new handler this guard exists to cover.
    """
    found: dict[str, type[Handler]] = {}
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        module = importlib.import_module(module_name)
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


def _bash_input(command: str) -> dict[str, Any]:
    return {"tool_name": _BASH_TOOL, "tool_input": {"command": command}}


def _denies(handler: Handler, hook_input: dict[str, Any]) -> bool:
    """True when the handler both matches and returns a DENY decision.

    `matches()` alone is not the question: several handlers match broadly and
    then decide to allow. What matters to a caller is whether the tool call is
    refused.
    """
    if not handler.matches(hook_input):
        return False
    result = handler.handle(hook_input)
    return getattr(result, "decision", None) == Decision.DENY


def _in_scope_handlers() -> dict[str, type[Handler]]:
    """Discovered PreToolUse handlers, minus the deliberate text matchers.

    Restricted to the PreToolUse package because the fixture is a Bash tool
    call. Handing that payload to a Stop handler asks it a question about an
    event it never receives, and the answer is meaningless — an early draft of
    this guard did exactly that and reported every Bash fixture as a failure of
    `AutoContinueStopHandler`.
    """
    return {
        name: cls
        for name, cls in _discover_handler_classes().items()
        if name not in _DELIBERATE_TEXT_MATCHERS and f".{_PRE_TOOL_USE_PACKAGE}." in cls.__module__
    }


class TestTheGuardIsNotVacuous:
    """A guard that cannot fail proves nothing — the mistake this plan replaces."""

    def test_the_fixture_is_not_empty(self) -> None:
        assert _NON_EXECUTING_TEXT

    def test_handlers_are_actually_discovered(self) -> None:
        assert len(_discover_handler_classes()) > 1

    def test_the_in_scope_set_is_not_empty(self) -> None:
        """If every handler were exempt the guard would pass while checking nothing."""
        assert _in_scope_handlers()

    def test_every_exemption_names_a_real_handler(self) -> None:
        """A stale exemption silently removes a handler from the guard."""
        discovered = set(_discover_handler_classes())
        stale = set(_DELIBERATE_TEXT_MATCHERS) - discovered

        assert not stale, f"exemptions name handlers that no longer exist: {sorted(stale)}"

    def test_every_exemption_states_a_reason(self) -> None:
        unexplained = [
            name for name, reason in _DELIBERATE_TEXT_MATCHERS.items() if not reason.strip()
        ]

        assert not unexplained, f"exemptions without a stated reason: {unexplained}"


class TestTheGuardHasTeeth:
    """Prove the guard would actually fail on an over-matching handler."""

    def test_a_deliberate_text_matcher_really_does_fire_on_text(self) -> None:
        """`destructive_git` must still match a dangerous command inside a string.

        This is the inverse of the guard and it is NOT incidental: Plan 00228
        must not quietly weaken the safety layer, and the acceptance suite
        depends on exactly this behaviour.
        """
        handlers = _discover_handler_classes()
        destructive_git = handlers["DestructiveGitHandler"]()
        embedded = _bash_input('echo "git reset --hard HEAD~1"')

        assert _denies(destructive_git, embedded) is True


@pytest.mark.parametrize("description", sorted(_NON_EXECUTING_TEXT))
def test_no_in_scope_handler_denies_non_executing_text(description: str) -> None:
    """Text naming a guardrail must not be mistaken for a command doing the thing."""
    command = _NON_EXECUTING_TEXT[description]
    hook_input = _bash_input(command)

    offenders = []
    for name, handler_class in _in_scope_handlers().items():
        handler = handler_class()
        if _denies(handler, hook_input):
            offenders.append(name)

    assert not offenders, (
        f"{offenders} denied text that only NAMES what they guard ({description}). "
        f"Either fix the matcher to require an executable construct, or add the "
        f"handler to _DELIBERATE_TEXT_MATCHERS with a reason."
    )
