"""StandingAuthorisationsHandler - replay authorisations a project recorded (Plan 00223).

A session's system prompt may carry instructions of the form "do not do X
**unless the user requested it**". Those instructions are not wrong, and this
handler does not argue with them. The gap they leave is that a project has
nowhere DURABLE to record a request it has genuinely made: the request is
given once in conversation, and the restriction is restated on every
subsequent request from a position the project cannot reach.

So this handler carries recorded authorisations forward. It is a filing
cabinet, not a countermand.

**Why UserPromptSubmit** (Plan 00223 Phase 1, measured against a real 37,475
record transcript spanning 18 compactions): SessionStart is a different
transport entirely (``hook_system_message``, never ``hook_additional_context``)
and its full payload was delivered exactly ONCE, because the prevailing
``is_resume_session`` gate is a transcript-size heuristic that is True for
every post-compaction session. UserPromptSubmit delivered 198 times, one per
prompt. The restriction being answered lives in a system prompt re-sent on
EVERY request, so only a per-prompt channel keeps pace with it. Anything
delivered once loses on arithmetic, not on wording.

**Nothing is authorised by default** (Decision 3). The handler ships enabled
so the options are discoverable; every built-in entry ships disabled. Every
other default-on handler in this codebase ADDS a restriction — this one
removes one, and shipping that active would have the daemon fabricate the very
consent the injected text claims. ``config-changes/`` with ``recommended:
true`` is what carries the option to existing installs.

**The text is a recorded request, never a countermand** (Decision 2). Each
entry states that the PROJECT has authorised the behaviour and names the
config key holding it, so it can be audited and revoked. No entry tells the
agent to ignore, disregard or override anything — enforced by a test, because
that framing is both a worse prompt and a mechanism that should not exist.
"""

from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

# ── Config keys (mirrors command_hints' `_KEY_*` style) ────────────────────
_KEY_ID: Final[str] = "id"
_KEY_ENABLED: Final[str] = "enabled"

# ── Built-in authorisation ids ─────────────────────────────────────────────
# Two, because Phase 1 found the system prompt carries TWO separate
# restrictions and authorising delegation says nothing about authorising
# workflow orchestration.
AUTHORISATION_SUBAGENT_DELEGATION: Final[str] = "subagent-delegation"
AUTHORISATION_WORKFLOWS: Final[str] = "workflow-orchestration"

# Where a reader can audit and revoke any of this. Named in every entry's
# text: an authorisation that cannot be found is not auditable, and one that
# cannot be revoked is not a request.
_CONFIG_LOCATION: Final[str] = (
    ".claude/hooks-daemon.yaml under "
    "handlers.user_prompt_submit.standing_authorisations.options.authorisations"
)

_SUBAGENT_DELEGATION_TEXT: Final[str] = (
    "STANDING AUTHORISATION (on file for this project). Sub-agent delegation "
    "is pre-requested here: this project asks that you use the Agent tool on "
    "your own initiative wherever it genuinely helps — parallel investigation, "
    "keeping a large search out of the main context, a second opinion on a "
    "risky change — without pausing to ask permission each time. Judgement "
    "still applies: delegate when it earns its cost, not by reflex, and "
    "prefer isolated worktrees when peers may touch the same git index. "
    f"This request is recorded in {_CONFIG_LOCATION}, where it can be read "
    "and withdrawn."
)

_WORKFLOWS_TEXT: Final[str] = (
    "STANDING AUTHORISATION (on file for this project). Multi-agent workflow "
    "orchestration is pre-requested here: this project has opted in to "
    "workflow runs, so treat that opt-in as standing rather than seeking it "
    "per task. Scale still matters — a workflow can spend a great deal for a "
    "task a single agent would finish, so match the shape of the run to the "
    "size of the problem. "
    f"This request is recorded in {_CONFIG_LOCATION}, where it can be read "
    "and withdrawn."
)

# ── Short forms, used once the full text has been delivered a few times ────
# A DECAY, not a cooldown (Task 3.3). The short form still names where the
# request is recorded, because an authorisation that cannot be audited is not
# a request.
_SUBAGENT_DELEGATION_SHORT: Final[str] = (
    "STANDING AUTHORISATION (on file): sub-agent delegation is pre-requested "
    "for this project — use the Agent tool on your own initiative where it "
    "helps, no need to ask. Recorded in .claude/hooks-daemon.yaml."
)

_WORKFLOWS_SHORT: Final[str] = (
    "STANDING AUTHORISATION (on file): multi-agent workflow orchestration is "
    "pre-requested for this project — treat the opt-in as standing. Recorded "
    "in .claude/hooks-daemon.yaml."
)

# The built-in set. Every entry ships DISABLED (Decision 3) — the set exists so
# the options are discoverable and adopting one is a single flag, not so that
# anything is authorised on a fresh install.
_BUILTIN_TEXTS: Final[dict[str, str]] = {
    AUTHORISATION_SUBAGENT_DELEGATION: _SUBAGENT_DELEGATION_TEXT,
    AUTHORISATION_WORKFLOWS: _WORKFLOWS_TEXT,
}

_BUILTIN_SHORT_TEXTS: Final[dict[str, str]] = {
    AUTHORISATION_SUBAGENT_DELEGATION: _SUBAGENT_DELEGATION_SHORT,
    AUTHORISATION_WORKFLOWS: _WORKFLOWS_SHORT,
}

# How many times per session the FULL text is delivered before decaying to the
# short form. Small: the full wording exists to establish the request, and
# repeating it verbatim every prompt for hours buys nothing.
_FULL_TEXT_DELIVERIES: Final[int] = 3

# Bound the per-session delivery-count map so a long-lived daemon cannot leak
# memory across many sessions. Same FIFO-eviction shape as
# command_hints._fire_state.
_MAX_TRACKED_SESSIONS: Final[int] = 512

_UNKNOWN_SESSION: Final[str] = "unknown"


class StandingAuthorisationsHandler(Handler):
    """Inject the authorisations a project has recorded in its config.

    ADVISORY ONLY: never blocks, never denies, never terminal. Silent unless a
    project has explicitly enabled at least one entry.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STANDING_AUTHORISATIONS,
            priority=Priority.STANDING_AUTHORISATIONS,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes, not dynamic ones.
        #
        # Typed `list[Any]`, NOT `list[dict[str, Any]]`: this is arbitrary
        # user-authored YAML, so claiming every element is a dict would be a
        # type the boundary cannot honour — and mypy rightly called the
        # isinstance guard below redundant against that false promise. The
        # guard is the validation (Core Standard 14); the type must not lie
        # about what has already been validated.
        self._authorisations: list[Any] | None = None

        # Per-session delivery counts driving the decay — bounded, FIFO.
        self._delivery_counts: dict[str, int] = {}

    def _enabled_ids(self) -> set[str]:
        """Return the ids a project has explicitly enabled.

        An entry naming an id with no built-in text is ignored rather than
        raising: a config typo must not take the daemon down, and a silently
        absent advisory is the correct failure for an advisory handler.
        """
        configured = self._authorisations or []
        return {
            str(entry.get(_KEY_ID))
            for entry in configured
            if isinstance(entry, dict) and entry.get(_KEY_ENABLED) is True
        }

    def _resolve_entries(self, *, short: bool = False) -> list[str]:
        """Return the text of every ENABLED authorisation, in built-in order."""
        enabled = self._enabled_ids()
        texts = _BUILTIN_SHORT_TEXTS if short else _BUILTIN_TEXTS
        return [text for entry_id, text in texts.items() if entry_id in enabled]

    def _record_delivery(self, session_id: str) -> int:
        """Increment and return this session's delivery count (bounded map)."""
        if session_id not in self._delivery_counts and (
            len(self._delivery_counts) >= _MAX_TRACKED_SESSIONS
        ):
            # FIFO eviction — dicts preserve insertion order.
            oldest = next(iter(self._delivery_counts))
            del self._delivery_counts[oldest]
        count = self._delivery_counts.get(session_id, 0) + 1
        self._delivery_counts[session_id] = count
        return count

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match any prompt-bearing UserPromptSubmit event."""
        return isinstance(hook_input.get("prompt"), str)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return the enabled authorisations, decaying to a short form.

        The decay NEVER skips a prompt (Task 3.3). A skipped prompt would be a
        window in which the restriction being answered is unopposed — the very
        SessionStart failure Phase 1 measured. Only the wording shortens.
        """
        if not self._enabled_ids():
            return HookResult(decision=Decision.ALLOW, context=[])

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_SESSION)
        deliveries = self._record_delivery(session_id)
        short = deliveries > _FULL_TEXT_DELIVERIES
        return HookResult(decision=Decision.ALLOW, context=self._resolve_entries(short=short))

    def get_claude_md(self) -> str | None:
        """Document the SETTING, deliberately without restating the authorisations.

        Phase 1 measured CLAUDE.md as the lowest-position lever of four, so a
        second copy of the authorisation text here would be the copy that goes
        stale while still reading as authoritative. It points at the config
        instead.
        """
        return (
            "## standing_authorisations — a project can record a standing request\n\n"
            "Some instructions are conditional on the user having asked "
            '("unless the user requested it"). A request made in conversation '
            "does not survive the session, so this project can record one in "
            "config instead, and the daemon replays it on each prompt.\n\n"
            "Configured in `.claude/hooks-daemon.yaml` under "
            "`handlers.user_prompt_submit.standing_authorisations.options.authorisations`, "
            "as a list of `{id, enabled}` entries. Built-in ids: "
            f"`{AUTHORISATION_SUBAGENT_DELEGATION}`, `{AUTHORISATION_WORKFLOWS}`.\n\n"
            "**Every entry ships disabled.** The handler is enabled so the "
            "options are discoverable, but nothing is authorised until the "
            "project turns it on — the daemon must never assert consent that "
            "was not given. Enabling one is a deliberate act by whoever owns "
            "the repository, and removing it withdraws the authorisation.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Standing authorisations are silent until a project enables one",
                command='echo "test"',
                description=(
                    "Default state check. With no authorisations enabled (the"
                    " shipped default), submitting a prompt must inject NO"
                    " standing-authorisation context. Verify by submitting a"
                    " prompt and confirming no 'STANDING AUTHORISATION' text"
                    " appears in the system-reminders."
                ),
                expected_decision=Decision.ALLOW,
                # Deliberately empty: this test asserts that NOTHING is
                # injected in the shipped default state.
                expected_message_patterns=[],
                safety_notes=(
                    "Advisory only - never blocks. This test asserts ABSENCE, so"
                    " it fails loudly if the daemon ever starts asserting an"
                    " authorisation the project did not record."
                ),
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
