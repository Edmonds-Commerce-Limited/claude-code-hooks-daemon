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
import json
import pkgutil
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.handler_bases import (
    PreToolUseHandlerBase,
    StopHandlerBase,
)
from claude_code_hooks_daemon.core.hook_result import Decision

_BASH_TOOL = "Bash"

# Plan 00342 Task 1.2: scope by BASE CLASS, not module path.
#
# The original scoping matched `.pre_tool_use.` in the module path — a string
# proxy for "takes a Bash tool call". With a second fixture shape that proxy
# stops working, and the replacement has to satisfy the property this guard is
# built on (Plan 00228, Decision 1): a NEW handler must be covered without
# anyone remembering to add it. Every handler already inherits from exactly one
# event base class, and that inheritance IS the declaration of which payload it
# receives — so `issubclass` is explicit, cannot drift from the directory
# layout, and needs nothing added per handler.
#
# A `fixture_shape = "bash"` class attribute was the obvious alternative and is
# worse: a second source of truth for something the base class already states,
# and it fails OPEN — a handler that forgets it silently leaves the guard.

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


# Text a Stop handler must not read as a CONTROL SIGNAL, taken from the shape
# that actually occurs: an agent writing about the cron-suppression subsystem
# while stopping for an unrelated reason. Every entry QUOTES the vocabulary
# rather than asserting it — see the scoping note on
# `test_no_stop_handler_arms_suppression_on_prose`.
_NON_DECLARING_STOP_TEXT: dict[str, str] = {
    "reporting that the token feature shipped": (
        "STOPPING BECAUSE: Phase 3 is shipped — the [awaiting-human] token now "
        "arms the marker, pinned by a test."
    ),
    "quoting a legacy phrase while documenting it": (
        "STOPPING BECAUSE: documented the four phrases; a stop saying "
        "'blocked only on human input' arms cron suppression."
    ),
    "quoting the user-input phrase while writing guidance": (
        "STOPPING BECAUSE: wrote the guidance explaining that 'need user input' "
        "is one of the recognised phrasings."
    ),
    "quoting the decision phrase in a backticked span": (
        "STOPPING BECAUSE: the handler reference now lists `waiting on the "
        "user's decision` among the frozen phrasings."
    ),
}

# The inverse fixture: text that MUST arm, so a narrowing cannot be "fixed" by
# breaking the feature. Plan 00337 froze these phrasings precisely so they keep
# working.
_DECLARING_STOP_TEXT: dict[str, str] = {
    "the explicit sentinel": (
        "STOPPING BECAUSE: [awaiting-human] the owner has to choose between A and B."
    ),
    "a frozen legacy phrasing": (
        "STOPPING BECAUSE: blocked only on human input — the schema decision is theirs."
    ),
    "a legacy phrasing in a later sentence": (
        "STOPPING BECAUSE: everything I can do is done. Waiting on the user's "
        "decision about release scope."
    ),
}


def _stop_input(tmp_path: Path, assistant_text: str) -> dict[str, Any]:
    """A Stop payload whose last assistant message carries ``assistant_text``.

    Mirrors the transcript shape built by
    `tests/unit/handlers/stop/test_auto_continue_stop.py` rather than inventing
    a second builder (Plan 00342 Task 1.1).
    """
    transcript = tmp_path / "transcript.jsonl"
    record = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": assistant_text}],
        },
    }
    transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "transcript_path": str(transcript),
        "session_id": "prose-guard-probe",
    }


def _arms_suppression(
    handler: Handler, hook_input: dict[str, Any], marker_dir: Path, monkeypatch: Any
) -> bool:
    """True when handling this payload leaves a blockage marker behind.

    The predicate is a SIDE EFFECT, not a decision, and that difference is the
    whole reason this axis needed its own predicate. On PreToolUse the failure
    is a wrong DENY, which `_denies` sees. On Stop the handler writes the marker
    and then returns its normal decision, so a `_denies`-shaped guard would
    report a clean pass on a handler that had just silently disarmed the
    session's recovery cron — the exact failure Plan 00342 exists to catch,
    which is worse than a wrong DENY precisely because it is SILENT.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext
    from claude_code_hooks_daemon.utils.blockage_marker import MARKER_FILENAME

    monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", staticmethod(lambda: marker_dir))
    marker = marker_dir / MARKER_FILENAME
    if marker.exists():
        marker.unlink()
    if handler.matches(hook_input):
        handler.handle(hook_input)
    return marker.exists()


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


def _handlers_deriving_from(base: type[Handler]) -> dict[str, type[Handler]]:
    """Discovered handlers for one event base class, minus deliberate matchers."""
    return {
        name: cls
        for name, cls in _discover_handler_classes().items()
        if name not in _DELIBERATE_TEXT_MATCHERS and issubclass(cls, base)
    }


def _in_scope_handlers() -> dict[str, type[Handler]]:
    """Handlers that can meaningfully answer the Bash tool-call fixture.

    Handing that payload to a Stop handler asks it a question about an event it
    never receives, and the answer is meaningless — an early draft of this
    guard did exactly that and reported every Bash fixture as a failure of
    `AutoContinueStopHandler`. The Stop axis has its OWN fixture below.
    """
    return _handlers_deriving_from(PreToolUseHandlerBase)


def _in_scope_stop_handlers() -> dict[str, type[Handler]]:
    """Handlers that can meaningfully answer the Stop transcript fixture."""
    return _handlers_deriving_from(StopHandlerBase)


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


class TestTheStopAxisIsNotVacuous:
    """Per-shape non-vacuity (Plan 00342 Task 1.3).

    `TestTheGuardIsNotVacuous` exists because an earlier version passed while
    checking nothing. A second fixture shape needs the same protection in its
    own right: without these, a marker predicate that never returned True would
    make the entire Stop axis pass silently — the same vacuity, one level down.
    """

    def test_the_stop_in_scope_set_is_not_empty(self) -> None:
        assert _in_scope_stop_handlers()

    def test_the_stop_fixture_is_not_empty(self) -> None:
        assert _NON_DECLARING_STOP_TEXT

    @pytest.mark.parametrize("description", sorted(_DECLARING_STOP_TEXT))
    def test_the_marker_predicate_fires_on_a_real_declaration(
        self, description: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The teeth test: a genuine declaration MUST still arm suppression.

        This is the inverse of the guard and it is not incidental. A narrowing
        that broke the feature would otherwise satisfy the guard perfectly —
        nothing arms on prose because nothing arms at all.
        """
        handler = _discover_handler_classes()["AutoContinueStopHandler"]()
        hook_input = _stop_input(tmp_path, _DECLARING_STOP_TEXT[description])

        assert _arms_suppression(handler, hook_input, tmp_path, monkeypatch) is True


@pytest.mark.parametrize("description", sorted(_NON_DECLARING_STOP_TEXT))
def test_no_stop_handler_arms_suppression_on_prose(
    description: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stop message ABOUT the control signal is not the control signal.

    SCOPE, recorded because it is a deliberate limit rather than an oversight:
    every fixture here QUOTES the vocabulary (quote marks or backticks). An
    UNQUOTED sentence describing the mechanism — "the daemon drops a tick when
    a session is blocked only on human input" — still arms, and cannot be
    separated lexically from "the release is blocked only on human input",
    which must arm. That difference is semantic, and it is exactly why Plan
    00337 introduced the explicit sentinel and froze these patterns instead of
    widening them again.
    """
    text = _NON_DECLARING_STOP_TEXT[description]

    offenders = []
    for name, handler_class in _in_scope_stop_handlers().items():
        hook_input = _stop_input(tmp_path, text)
        if _arms_suppression(handler_class(), hook_input, tmp_path, monkeypatch):
            offenders.append(name)

    assert not offenders, (
        f"{offenders} armed cron suppression on text that only QUOTES the "
        f"declaration vocabulary ({description}). This fails SILENTLY — the "
        f"session simply stops receiving recovery ticks."
    )
