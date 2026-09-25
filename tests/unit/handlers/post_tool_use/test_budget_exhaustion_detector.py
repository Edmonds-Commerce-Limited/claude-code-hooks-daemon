"""Tests for BudgetExhaustionDetectorHandler - budget-exhaustion advisory.

Covers: the one field-confirmed web-search budget refusal shape (Plan 00315
BUDGETS.md), channel scoping (a signal only matches its own declared tool --
N46, Plan 00466 ledger 16), precision (no firing on Read/Grep/Glob/Bash/Task/
Agent tool responses, no firing on the ceiling number alone, no arbitrary
Bash stdout scanned regardless of the producing command), the ledger
self-feed guard, extra_patterns configurability, the occurrence ledger, and
config options (excluded_tools, extra_patterns).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.budget_exhaustion_detector import (
    BudgetExhaustionDetectorHandler,
)


@pytest.fixture
def handler() -> BudgetExhaustionDetectorHandler:
    """Create a fresh handler instance for each test."""
    return BudgetExhaustionDetectorHandler()


def _tool_input(tool_name: str, tool_response: Any, session_id: str = "sess-1") -> dict[str, Any]:
    """Build a PostToolUse hook input with the given tool name/response."""
    return {
        "tool_name": tool_name,
        "tool_input": {},
        "tool_response": tool_response,
        "session_id": session_id,
    }


# ─── Web-search budget fixture (Plan 00315 BUDGETS.md, field-confirmed) ──────


class TestWebSearchBudgetFixture:
    """The pinned field-confirmed web-search budget refusal shape, channel-
    scoped to ``tool_name == "WebSearch"`` (N46, Plan 00466 ledger 16)."""

    _FIXTURE = (
        "Web search was not performed: this session has used its web search "
        "budget (200 of 200 WebSearch calls). Continue with the information "
        "already gathered instead of issuing more searches. If more searches "
        "are genuinely needed, raise CLAUDE_CODE_MAX_WEB_SEARCHES"
    )

    def test_matches_web_search_budget_fixture(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input("WebSearch", {"content": self._FIXTURE})
        assert handler.matches(hook_input) is True

    def test_never_keys_on_the_ceiling_number_alone(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The bare number '200' with no budget/exhaustion wording must not fire."""
        hook_input = _tool_input("WebSearch", {"content": "Found 200 results across 200 pages."})
        assert handler.matches(hook_input) is False

    def test_generic_wording_alone_no_longer_fires_even_through_websearch(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """N46 follow-up: a prior "generic" family matched broad 'budget
        exhausted'/'quota exceeded' wording against ANY non-excluded tool's
        response, including WebSearch's. It was removed (no confirmed
        channel of its own, and the repeat false-positive source) -- only
        the pinned, verbatim fragment matches now."""
        hook_input = _tool_input(
            "WebSearch", {"content": "This tool's budget has been exhausted for the session."}
        )
        assert handler.matches(hook_input) is False

    def test_pinned_fragment_does_not_fire_through_an_unrecognised_channel(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The pinned fragment is channel-gated to WebSearch specifically --
        the identical text through a DIFFERENT, non-excluded tool must not
        fire either, since that tool is not this signal's confirmed
        channel."""
        hook_input = _tool_input(
            "WebFetch",
            {"content": "Web search was not performed: web search budget exhausted."},
        )
        assert handler.matches(hook_input) is False

    def test_advisory_names_matched_fragment_and_demands_prominent_reporting(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input("WebSearch", {"content": self._FIXTURE})
        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context
        combined = "\n".join(result.context)
        assert "BUDGET EXHAUSTED" in combined
        assert "🚨" in combined
        assert "Web search was not performed" in combined
        assert "not" in combined.lower() and "retry" in combined.lower()


# ─── No arbitrary Bash stdout is ever scanned (N46 follow-up) ────────────────


class TestNoArbitraryBashStdoutScanned:
    """Coordinator review of N46: a verb-by-verb passthrough allowlist
    (cat/grep/jq/git/...) still lets any UNLISTED command through
    unfiltered -- it is the allowlist pattern this project rejects, and it
    keeps needing a new entry per false positive rather than closing the
    class. Bash now joins the default excluded tools
    (``_DEFAULT_EXCLUDED_TOOLS``), so no command's stdout is ever scanned,
    regardless of which verb produced it. One reproduction case is kept
    (N46 review 1, NIT-9): every command variant takes the SAME early
    return at the tool-exclusion check (``tool_input``/the command is never
    even read), so parametrising verbs the way an allowlist test would
    (``rg``, ``awk``, ``python -c``, a live ``curl`` fetch) duplicated
    ``TestExcludedToolsByDefault::test_default_excluded_tools_never_fire``
    without exercising anything distinct.
    """

    _WEB_SEARCH_FIXTURE = (
        "Web search was not performed: this session has used its web search "
        "budget (200 of 200 WebSearch calls)."
    )

    def test_bash_never_fires_regardless_of_producing_command(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The N46 reproduction itself: `git diff` showing the ledger's own
        real false-positive phrase ("exceeded its byte budget")."""
        diff_text = (
            "diff --git a/foo.py b/foo.py\n"
            "+        raise BudgetError('this call exceeded its byte budget')\n"
        )
        hook_input = _tool_input("Bash", {"stdout": diff_text, "stderr": ""})
        hook_input["tool_input"] = {"command": "git diff HEAD~1"}
        assert handler.matches(hook_input) is False

    def test_the_real_signal_still_fires_through_its_own_channel(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The load-bearing half: excluding Bash entirely must cost no true
        positive on the one confirmed channel."""
        hook_input = _tool_input("WebSearch", {"content": self._WEB_SEARCH_FIXTURE})
        assert handler.matches(hook_input) is True


# ─── Unrendered source is not a delivered signal (Plan 00400 N4) ────────────


class TestUnrenderedTemplateIsNotASignal:
    """Plan 00400 N4: SOURCE CODE carrying an unexpanded format placeholder is
    not a budget hit, even through the one surviving channel (WebSearch).

    The discriminator is the fragment's own text rather than the command: a
    RENDERED runtime message always has its placeholders substituted, so an
    unexpanded ``{...}`` placeholder proves the text is source.
    """

    def test_unexpanded_placeholder_does_not_fire(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input(
            "WebSearch",
            {"content": "Web search was not performed for {reason} in this session."},
        )
        assert handler.matches(hook_input) is False

    def test_the_same_message_rendered_still_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The load-bearing half: suppressing source must cost no true positive."""
        hook_input = _tool_input(
            "WebSearch",
            {"content": "Web search was not performed for rate limiting in this session."},
        )
        assert handler.matches(hook_input) is True

    def test_json_braces_are_not_mistaken_for_a_placeholder(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """A real signal delivered as JSON must not be suppressed by the guard."""
        hook_input = _tool_input(
            "WebSearch", {"content": '{"error": "Web search was not performed"}'}
        )
        assert handler.matches(hook_input) is True


# ─── Precision: excluded tools ───────────────────────────────────────────────


class TestExcludedToolsByDefault:
    @pytest.mark.parametrize(
        "tool_name",
        ["Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit", "Bash"],
    )
    def test_default_excluded_tools_never_fire(
        self, handler: BudgetExhaustionDetectorHandler, tool_name: str
    ) -> None:
        """File-content tools and Bash are excluded by default so reading a
        file or running a shell command that merely discusses budget
        exhaustion in its prose never fires. Task/Agent are NOT in this list
        (N46 review 1, MINOR-5): they carry a real harness-written signal of
        their own (a dispatched sub-agent cut off by a usage limit -- see
        TestAgentTerminatedEarlySignal), so precision comes from channel
        scoping (an anchored pattern) rather than a blanket exclusion."""
        hook_input = _tool_input(
            tool_name,
            {"content": "Web search was not performed: web search budget exhausted"},
        )
        assert handler.matches(hook_input) is False

    def test_excluded_tools_configurable(self, handler: BudgetExhaustionDetectorHandler) -> None:
        """N46 review 1, MINOR-6: a Bash payload is a vacuous check post-fix --
        Bash can never fire from a builtin signal regardless of this option,
        because of the channel gate (not the exclusion list). Assert the
        option takes effect on a tool that WOULD otherwise fire: excluding
        WebSearch itself suppresses its own pinned fragment, and the default
        configuration (no override) still catches it."""
        fixture = "Web search was not performed: web search budget"

        handler._excluded_tools = ["WebSearch"]
        assert handler.matches(_tool_input("WebSearch", {"content": fixture})) is False

        default_handler = BudgetExhaustionDetectorHandler()
        assert default_handler.matches(_tool_input("WebSearch", {"content": fixture})) is True

    def test_bash_can_be_re_included_for_a_confirmed_second_channel(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """A project that has confirmed its OWN CLI reports a genuine quota
        signal through Bash re-includes "Bash" via an ``excluded_tools``
        override and pairs it with a specific ``extra_patterns`` regex --
        the module docstring's documented opt-in path."""
        handler._excluded_tools = [
            "Read",
            "Grep",
            "Glob",
            "Edit",
            "Write",
            "NotebookEdit",
            "Task",
            "Agent",
        ]
        handler._extra_patterns = [r"MyCLI: quota exceeded \(code 429\)"]
        hook_input = _tool_input(
            "Bash", {"stdout": "MyCLI: quota exceeded (code 429)", "stderr": ""}
        )
        assert handler.matches(hook_input) is True


# ─── Self-referential response markers ───────────────────────────────────────


class TestSelfReferentialResponseMarkers:
    """A payload that names this handler or its ledger is documentation ABOUT
    the feature (a CHANGELOG entry, a generated playbook), not a live
    signal -- even when it also quotes the pinned fragment verbatim, which
    is exactly what a generated report does. Observed live while reading
    this repo's own changelog during the v3.60.0 release, and again from a
    generated acceptance-test playbook.
    """

    @pytest.mark.parametrize(
        "documentation_text",
        [
            "New PostToolUse handler scans for the field-confirmed 'Web search "
            "was not performed' shape. Ships as budget_exhaustion_detector.",
            "The web search budget is exhausted per session; see "
            "budget-exhaustion-events.jsonl for recorded occurrences. Matches: "
            "'Web search was not performed'.",
        ],
    )
    def test_documentation_about_this_handler_never_fires(
        self, handler: BudgetExhaustionDetectorHandler, documentation_text: str
    ) -> None:
        hook_input = _tool_input("WebSearch", {"content": documentation_text})
        assert handler.matches(hook_input) is False

    def test_report_naming_the_handler_class_never_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """Text naming this handler by its CLASS name is documentation about
        the feature, exactly like text naming its module. A generated report
        (e.g. an acceptance-test playbook dump) quotes the refusal sentence
        verbatim because that IS what the block simulates."""
        report_text = (
            "#190 BudgetExhaustionDetectorHandler [PostToolUse]\n"
            "  command  : Simulate a WebSearch tool response containing the text\n"
            "    'Web search was not performed: this session has used its web\n"
            "    search budget (200 of 200 WebSearch calls).'"
        )
        hook_input = _tool_input("WebSearch", {"content": report_text})
        assert handler.matches(hook_input) is False


# ─── Ledger self-feed: structural JSON-shape recognition (Task 1.4 / F2) ─────


class TestLedgerSelfFeedStructural:
    """A structurally recognised ledger record (all four record keys) is
    documentation of a PAST detection, not a live one, and is stripped
    before matching runs -- tested against the surviving WebSearch channel
    since Bash is excluded entirely (N46).
    """

    _LEDGER_LINE = (
        '{"timestamp": "2026-09-02T00:00:00+00:00", "session_id": "sess-old", '
        '"tool_name": "WebSearch", "matched_fragment": "web search budget"}'
    )

    _LEDGER_PRETTY = (
        "{\n"
        '  "timestamp": "2026-09-02T00:00:00+00:00",\n'
        '  "session_id": "sess-old",\n'
        '  "tool_name": "WebSearch",\n'
        '  "matched_fragment": "web search budget"\n'
        "}"
    )

    def test_full_ledger_record_alone_never_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input("WebSearch", {"content": self._LEDGER_LINE})
        assert handler.matches(hook_input) is False

    def test_jq_pretty_printed_ledger_record_never_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """``jq .`` reformats the record across several lines, defeating a
        naive per-line JSON parse -- the recognizer must survive that."""
        hook_input = _tool_input("WebSearch", {"content": self._LEDGER_PRETTY})
        assert handler.matches(hook_input) is False

    def test_ledger_shape_requires_all_four_keys(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """A JSON object missing two of the ledger's record keys (and
        carrying neither self-referential marker string) is NOT recognised
        as ledger content -- this guards against the recognizer being so
        loose it swallows a genuine structured tool response that merely
        happens to be a JSON object, or blocks a genuine signal sitting
        right next to unrelated structured data."""
        partial = (
            '{"tool_name": "WebSearch", "timestamp": "2026-01-01T00:00:00+00:00"} '
            "Web search was not performed: web search budget exhausted"
        )
        hook_input = _tool_input("WebSearch", {"content": partial})
        assert handler.matches(hook_input) is True


# ─── Sub-agent dispatch reports (Task 4.5) ───────────────────────────────────


class TestSubagentDispatchReportNeverFires:
    """A dispatched sub-agent's own COMPOSED PROSE quoting another signal's
    fixture text is not that signal firing -- the same category as a file
    the model merely read (N46 review 1, MINOR-5 rationale correction: this
    is NOT because the harness never writes to a Task/Agent tool_response --
    it does, for a usage-limit termination; see
    TestAgentTerminatedEarlySignal -- it is that the WebSearch fragment
    specifically is channel-gated to the WebSearch tool, and free prose
    composed by an LLM does not open with a DIFFERENT signal's exact anchor
    either). If the sub-agent's OWN work genuinely hit a budget mid-task,
    that fires directly on its own tool_result, which the channel-scoped
    Agent-terminated-early signal below now catches."""

    _SUBAGENT_REPORT = (
        "Verified Test 187: the response contains 'Web search was not "
        "performed: this session has used its web search budget (200 of "
        "200 WebSearch calls).' as expected. All acceptance checks pass."
    )

    @pytest.mark.parametrize("tool_name", ["Task", "Agent"])
    def test_subagent_report_quoting_fixture_never_fires(
        self, handler: BudgetExhaustionDetectorHandler, tool_name: str
    ) -> None:
        hook_input = _tool_input(tool_name, {"content": self._SUBAGENT_REPORT})
        assert handler.matches(hook_input) is False


# ─── Agent-terminated-early: a real harness signal on Task/Agent (MINOR-5) ───


def _real_dispatch_result(text: str) -> dict[str, Any]:
    """A REDACTED copy of the documented/observed ``completed`` PostToolUse:
    Agent ``tool_response`` shape (hooks.md:1775-1787; N46 review 2,
    BLOCKER-1): ``content`` is an ARRAY of ``{"type": "text", "text": ...}``
    blocks, alongside run telemetry. Every value here is a placeholder --
    no real agent id, request id or session id."""
    return {
        "status": "completed",
        "agentId": "a0000000000000000",
        "agentType": "general-purpose",
        "content": [{"type": "text", "text": text}],
        "resolvedModel": "claude-sonnet-5",
        "totalDurationMs": 1000,
        "totalTokens": 1000,
        "totalToolUseCount": 1,
        "usage": {"input_tokens": 100, "output_tokens": 100},
    }


class TestAgentTerminatedEarlySignal:
    """N46 review 1, MINOR-5 (real shape fixed by N46 review 2, BLOCKER-1):
    this session's own transcripts caught a SECOND real, confirmed channel --
    a dispatched sub-agent cut off mid-task by a harness usage-limit
    rejection writes the harness's OWN sentence as the first TEXT BLOCK of
    its ``PostToolUse:Task``/``PostToolUse:Agent`` ``tool_response`` (three
    live ``completed`` occurrences: two weekly-limit, one session-limit). A
    fourth, ``is_error: true`` occurrence reaches ``PostToolUseFailure``, a
    different event this PostToolUse handler does not receive -- see
    ``TestIsErrorVariantIsOutOfPostToolUseScope`` below and NIGGLES.md N46
    for the follow-up. Anchored at the start of the joined text (``\\A``) so
    a sub-agent's own prose QUOTING the phrase mid-response -- exactly the
    shape ``TestSubagentDispatchReportNeverFires`` covers for the WebSearch
    fragment -- cannot match here either, and additionally requires the
    stable ``(error type rate_limit, HTTP 429`` tail nearby (N46 review 2,
    NIT-6), so a report that merely opens with the bare sentence and nothing
    else does not match. Task/Agent are NOT in ``_DEFAULT_EXCLUDED_TOOLS``
    specifically so this channel-scoped signal is reachable; precision comes
    from the anchor, the tail requirement and the channel gate, not from a
    blanket tool exclusion.
    """

    _WEEKLY_LIMIT = (
        "Agent terminated early due to an API error: You've hit your weekly "
        "limit · resets Sep 27, 8am (UTC) (error type rate_limit, HTTP "
        "429, request id req_example, model claude-sonnet-5).\n\n"
        "Everything below is PARTIAL output recovered from the agent before "
        "it was cut off.\n\n"
        "Investigated the failure mode and found..."
    )

    _SESSION_LIMIT = (
        "Agent terminated early due to an API error: You've hit your "
        "session limit · resets 12:50am (UTC) (error type rate_limit, "
        "HTTP 429, request id req_example, model claude-sonnet-5)."
    )

    @pytest.mark.parametrize("tool_name", ["Task", "Agent"])
    @pytest.mark.parametrize(
        "fixture",
        [_WEEKLY_LIMIT, _SESSION_LIMIT],
        ids=["weekly-limit", "session-limit"],
    )
    def test_the_real_transcript_shape_fires(
        self, handler: BudgetExhaustionDetectorHandler, tool_name: str, fixture: str
    ) -> None:
        hook_input = _tool_input(tool_name, _real_dispatch_result(fixture))
        assert handler.matches(hook_input) is True

    def test_a_subagents_own_prose_quoting_the_phrase_mid_response_does_not_fire(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        report = (
            "I checked the failure mode and found the transcript contains: "
            "'Agent terminated early due to an API error: You've hit your "
            "weekly limit' verbatim, confirming the hypothesis."
        )
        hook_input = _tool_input("Task", _real_dispatch_result(report))
        assert handler.matches(hook_input) is False

    def test_a_report_opening_with_the_bare_phrase_but_no_stable_tail_does_not_fire(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """N46 review 2, NIT-6: the anchor alone is not enough -- a report
        whose first line happens to be the bare sentence with no
        ``(error type rate_limit, HTTP 429`` tail nearby must not fire."""
        bare = (
            "Agent terminated early due to an API error: You've hit your "
            "weekly limit is the exact phrase I found in the transcript "
            "while investigating N46; the agent itself completed normally."
        )
        hook_input = _tool_input("Agent", _real_dispatch_result(bare))
        assert handler.matches(hook_input) is False

    def test_advisory_names_the_agent_and_demands_a_re_brief(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input("Task", _real_dispatch_result(self._WEEKLY_LIMIT))
        hook_input["tool_input"] = {
            "description": "review the diff for N23",
            "subagent_type": "fork",
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        combined = "\n".join(result.context)
        assert "review the diff for N23" in combined
        assert "re-brief" in combined.lower() or "rebrief" in combined.lower()


class TestIsErrorVariantIsOutOfPostToolUseScope:
    """N46 review 2, BLOCKER-1: the real ``is_error: true`` occurrence's
    ``toolUseResult`` is a bare string beginning ``"Error: Agent terminated
    early..."``, and it is delivered to ``PostToolUseFailure`` (hooks.md:
    2108-2151), not ``PostToolUse``. This PostToolUse handler intentionally
    does not receive that event, so this asserts the negative: even if a
    string of that shape somehow reached this handler's ``matches()``, the
    anchor (which requires the response to OPEN with "Agent terminated
    early", not "Error: ...") would not match it either -- the string
    prefix alone already rules it out."""

    def test_the_error_prefixed_string_does_not_match_the_agent_anchor(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        error_text = (
            "Error: Agent terminated early due to an API error: You've hit "
            "your weekly limit (error type rate_limit, HTTP 429)."
        )
        hook_input = _tool_input("Agent", {"content": error_text})
        assert handler.matches(hook_input) is False


class TestDispatchIdentity:
    """N46 review 2, MINOR-4: the advisory must use ``name`` -- the handle
    SendMessage needs for a re-brief, and the field 243 of 351 real Agent/
    Task calls set -- ahead of ``description``/``subagent_type``, and fall
    back to the ``tool_response``'s own ``agentId`` before giving up."""

    def _fired(
        self, handler: BudgetExhaustionDetectorHandler, tool_input: Any, tool_response: Any = None
    ) -> str:
        payload = _tool_input(
            "Agent",
            (
                tool_response
                if tool_response is not None
                else _real_dispatch_result(TestAgentTerminatedEarlySignal._WEEKLY_LIMIT)
            ),
        )
        payload["tool_input"] = tool_input
        result = handler.handle(payload)
        assert result.context
        return result.context[0]

    def test_name_wins_over_description(self, handler: BudgetExhaustionDetectorHandler) -> None:
        advisory = self._fired(
            handler, {"name": "n46-fix", "description": "review N23", "subagent_type": "fork"}
        )
        assert "n46-fix" in advisory
        assert "review N23" not in advisory

    def test_description_is_used_when_name_is_absent(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        advisory = self._fired(handler, {"subagent_type": "fork", "description": "review N23"})
        assert "review N23" in advisory

    def test_subagent_type_is_used_when_name_and_description_are_absent(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        advisory = self._fired(handler, {"subagent_type": "Explore"})
        assert "Explore" in advisory

    def test_falls_back_to_the_tool_responses_own_agent_id(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        response = _real_dispatch_result(TestAgentTerminatedEarlySignal._WEEKLY_LIMIT)
        response["agentId"] = "a1234567890abcdef"
        advisory = self._fired(handler, {}, tool_response=response)
        assert "a1234567890abcdef" in advisory

    def test_unnamed_dispatch_when_nothing_identifies_it(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        response = _real_dispatch_result(TestAgentTerminatedEarlySignal._WEEKLY_LIMIT)
        response.pop("agentId")
        advisory = self._fired(handler, None, tool_response=response)
        assert "an unnamed dispatch" in advisory


# ─── extra_patterns: admin-declared, tool-agnostic among non-excluded tools ──


class TestExtraPatterns:
    def test_extra_patterns_are_additive_on_a_non_excluded_tool(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """An admin-declared regex applies to any tool NOT in
        ``excluded_tools`` -- here a hypothetical non-Bash, non-builtin-
        channel tool (WebFetch), which is neither excluded by default nor a
        declared builtin signal's channel."""
        handler._extra_patterns = [r"custom quota ceiling hit"]
        hook_input = _tool_input("WebFetch", {"content": "custom quota ceiling hit today"})
        assert handler.matches(hook_input) is True

    def test_extra_patterns_never_scan_a_dispatchs_own_prompt_or_telemetry(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """N46 review 2, MINOR-3: un-excluding Task/Agent must not route
        ``extra_patterns`` over the orchestrator's own dispatch brief
        (``prompt``) or run telemetry -- only the sub-agent's OWN reported
        text. A dispatch whose PROMPT mentions the admin's term, but whose
        reply text does not, must not fire."""
        handler._extra_patterns = [r"budget"]
        response = _real_dispatch_result("done")
        response["prompt"] = "Review the budget detector"
        hook_input = _tool_input("Agent", response)
        assert handler.matches(hook_input) is False

    def test_extra_patterns_still_fire_on_the_dispatchs_own_reported_text(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The companion positive case: the SAME admin term, reached through
        the sub-agent's own reply text rather than the prompt, still fires."""
        handler._extra_patterns = [r"budget"]
        response = _real_dispatch_result("Reviewed the budget detector; all tests pass.")
        hook_input = _tool_input("Agent", response)
        assert handler.matches(hook_input) is True

    def test_async_launched_dispatch_has_nothing_to_scan(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """N46 review 2, MINOR-4 (foreground-only): an ``async_launched``
        background dispatch carries no ``content`` at all -- only ``prompt``
        and launch metadata -- so it must never fall back to scanning those
        fields either."""
        handler._extra_patterns = [r"budget"]
        response = {
            "agentId": "a0",
            "canReadOutputFile": True,
            "description": "review the budget detector",
            "isAsync": True,
            "outputFile": "/tmp/out",
            "prompt": "Review the budget detector",
            "resolvedModel": "claude-sonnet-5",
            "status": "async_launched",
        }
        hook_input = _tool_input("Agent", response)
        assert handler.matches(hook_input) is False


# ─── Never blocks ─────────────────────────────────────────────────────────────


class TestNeverBlocks:
    def test_decision_is_always_allow_on_a_match(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input(
            "WebSearch", {"content": "Web search was not performed: web search budget"}
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_decision_is_always_allow_on_no_match(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input("WebSearch", {"content": "Found 3 results."})
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


# ─── Cross-event isolation (Plan 00319 F10) ──────────────────────────────────
#
# Handler instances are shared across events on the daemon's executor pool
# (daemon/server.py dispatches `controller.dispatch` via
# `loop.run_in_executor`), so instance state set by one event's matches() and
# read by ANOTHER event's handle() before the first's own handle() runs is a
# genuine cross-session leak, not a hypothetical one.


class TestConcurrentEventIsolation:
    def test_a_second_events_matches_call_does_not_corrupt_the_first(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The interleaving a shared instance under concurrent dispatch permits.

        Two events both match; B's matches() runs BEFORE A's handle() -- the
        exact ordering a thread pool can produce. A's handle() must still
        report A's OWN fragment, never B's. Uses ``extra_patterns`` (shared
        config, but not per-event state) against a non-excluded, non-builtin
        tool so each event's matched text is distinguishable.
        """
        handler._extra_patterns = [r"custom quota ceiling hit for \w+"]
        hook_input_a = _tool_input(
            "WebFetch", {"content": "custom quota ceiling hit for toolA"}, session_id="sess-a"
        )
        hook_input_b = _tool_input(
            "WebFetch", {"content": "custom quota ceiling hit for toolB"}, session_id="sess-b"
        )

        assert handler.matches(hook_input_a) is True
        assert handler.matches(hook_input_b) is True  # interleaved on another thread
        result_a = handler.handle(hook_input_a)

        combined = "\n".join(result_a.context)
        assert "toolA" in combined
        assert "toolB" not in combined

    def test_a_non_matching_second_event_does_not_blank_the_first(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """A's fragment must survive even a B whose matches() call clears state."""
        hook_input_a = _tool_input(
            "WebSearch", {"content": "Web search was not performed for tool A"}, session_id="sess-a"
        )
        hook_input_b = _tool_input(
            "WebSearch", {"content": "ordinary output, nothing budget-related"}, session_id="sess-b"
        )

        assert handler.matches(hook_input_a) is True
        assert handler.matches(hook_input_b) is False
        result_a = handler.handle(hook_input_a)

        assert result_a.context
        assert "Web search was not performed" in "\n".join(result_a.context)


# ─── Occurrence ledger (Task 2.2) ────────────────────────────────────────────


class TestOccurrenceLedger:
    def test_detection_appends_one_json_line(
        self,
        handler: BudgetExhaustionDetectorHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", staticmethod(lambda: tmp_path))

        hook_input = _tool_input(
            "WebSearch",
            {"content": "Web search was not performed: web search budget"},
            session_id="sess-ledger",
        )
        handler.handle(hook_input)

        ledger_path = tmp_path / "budget-exhaustion-events.jsonl"
        assert ledger_path.exists()
        lines = [ln for ln in ledger_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["session_id"] == "sess-ledger"
        assert record["tool_name"] == "WebSearch"
        assert "timestamp" in record
        assert "Web search was not performed" in record["matched_fragment"]

    def test_ledger_write_failure_is_fail_open(
        self,
        handler: BudgetExhaustionDetectorHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A ledger write error must never raise -- the advisory still returns."""
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        def _raise() -> Path:
            raise RuntimeError("no project context")

        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", staticmethod(_raise))

        hook_input = _tool_input(
            "WebSearch", {"content": "Web search was not performed: web search budget"}
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


# ─── Handler metadata ────────────────────────────────────────────────────────


class TestHandlerMetadata:
    def test_default_enabled_true(self, handler: BudgetExhaustionDetectorHandler) -> None:
        assert handler.get_default_enabled() is True

    def test_claude_md_mentions_budgets(self, handler: BudgetExhaustionDetectorHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "budget" in guidance.lower()

    def test_acceptance_tests_include_advisory_and_bash_exclusion(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 2
