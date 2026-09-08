"""Tests for BudgetExhaustionDetectorHandler - budget-exhaustion advisory.

Covers: web-search budget refusal fixture (field-confirmed shape, Plan 00315
BUDGETS.md), generic budget/exhausted/quota/limit-reached shapes, precision
(no firing on Read/Grep/Glob tool responses, no firing on the ceiling number
alone, no firing on ordinary prose mentioning "budget"), the occurrence
ledger, and config options (excluded_tools, extra_patterns).
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
    """The pinned field-confirmed web-search budget refusal shape."""

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


# ─── Generic budget-exhaustion pattern family ────────────────────────────────


class TestGenericBudgetShapes:
    @pytest.mark.parametrize(
        "content",
        [
            "Error: budget exhausted for this operation.",
            "Request denied: quota exceeded for this resource.",
            "budget limit reached; no further calls permitted this session.",
            "This tool's budget has been used up for the session.",
        ],
    )
    def test_matches_generic_exhaustion_shapes(
        self, handler: BudgetExhaustionDetectorHandler, content: str
    ) -> None:
        hook_input = _tool_input("Bash", {"stdout": content, "stderr": ""})
        assert handler.matches(hook_input) is True

    def test_does_not_match_ordinary_prose_mentioning_budget(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """Near-miss: 'budget' appears but with no exhaustion/quota context."""
        hook_input = _tool_input(
            "Bash",
            {"stdout": "Updated the project budget planning spreadsheet.", "stderr": ""},
        )
        assert handler.matches(hook_input) is False


# ─── Precision: excluded tools ───────────────────────────────────────────────


class TestExcludedToolsByDefault:
    @pytest.mark.parametrize(
        "tool_name", ["Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit", "Task", "Agent"]
    )
    def test_default_excluded_tools_never_fire(
        self, handler: BudgetExhaustionDetectorHandler, tool_name: str
    ) -> None:
        """File-content tools are excluded by default so reading a file that
        merely discusses budget exhaustion in its prose never fires."""
        hook_input = _tool_input(
            tool_name,
            {"content": "budget exhausted: this session has used its web search budget"},
        )
        assert handler.matches(hook_input) is False

    @pytest.mark.parametrize(
        "command",
        [
            "cat untracked/budget-exhaustion-events.jsonl",
            "grep -c fragment /workspace/untracked/budget-exhaustion-events.jsonl",
            "grep -n pattern src/claude_code_hooks_daemon/handlers/post_tool_use/budget_exhaustion_detector.py",
            "sed -n 1p tests/unit/handlers/post_tool_use/test_budget_exhaustion_detector.py",
        ],
    )
    def test_self_referential_bash_reads_never_fire(
        self, handler: BudgetExhaustionDetectorHandler, command: str
    ) -> None:
        """A Bash command inspecting the ledger, the handler's own source or
        its tests is READING recorded/pattern text, not hitting a budget --
        without this guard, cat-ing the ledger re-fires the detector and
        appends a fresh entry, a self-feeding loop."""
        hook_input = _tool_input(
            "Bash",
            {"stdout": "budget exhausted: web search budget used", "stderr": ""},
        )
        hook_input["tool_input"] = {"command": command}
        assert handler.matches(hook_input) is False

    @pytest.mark.parametrize(
        "documentation_text",
        [
            # The project's own CHANGELOG entry describing this handler -- the
            # live false positive that motivated the guard (v3.60.0 release).
            "New PostToolUse handler scans for generic 'budget exhausted/used\n"
            "  up/exceeded' shapes. Ships as budget_exhaustion_detector.",
            # BUDGETS.md prose cataloguing the shapes this handler looks for.
            "The web search budget is exhausted per session; see "
            "budget-exhaustion-events.jsonl for recorded occurrences.",
        ],
    )
    def test_documentation_about_this_handler_never_fires(
        self, handler: BudgetExhaustionDetectorHandler, documentation_text: str
    ) -> None:
        """Text that NAMES this handler or its ledger is documentation ABOUT the
        feature, not a live budget signal.

        The command guard above only inspects the COMMAND, so reading a file
        whose CONTENT documents the detector (CHANGELOG.md, BUDGETS.md, the
        release notes) still fired -- observed live while reading this repo's
        own changelog. A genuine harness budget message never names the
        detector or its ledger, so keying on those markers is precise.
        """
        hook_input = _tool_input("Bash", {"stdout": documentation_text, "stderr": ""})
        hook_input["tool_input"] = {"command": "head -n 40 CHANGELOG.md"}
        assert handler.matches(hook_input) is False

    @pytest.mark.parametrize(
        "report_text",
        [
            # A generated acceptance-test report printing this handler's own
            # test definitions. The block's `command` field quotes the refusal
            # sentence verbatim, because that IS what the test simulates.
            "#190 BudgetExhaustionDetectorHandler [PostToolUse]\n"
            "  title    : Web-search budget refusal triggers a prominent advisory\n"
            "  command  : Simulate a WebSearch tool response containing the text\n"
            "    'Web search was not performed: this session has used its web\n"
            "    search budget (200 of 200 WebSearch calls).'",
            # The handler registry / documentation listing, same naming form.
            "BudgetExhaustionDetectorHandler — hidden agent budgets are surfaced\n"
            "  matches on: web search budget, quota exceeded",
        ],
    )
    def test_report_naming_the_handler_class_never_fires(
        self, handler: BudgetExhaustionDetectorHandler, report_text: str
    ) -> None:
        """Text naming this handler by its CLASS name is documentation about the
        feature, exactly like text naming its module.

        The response guard knew only the snake_case module form, so a generated
        report — which names handlers by class — slipped past it and fired the
        advisory on the handler's own test fixture. Observed live twice in one
        session while auditing the acceptance playbook.
        """
        hook_input = _tool_input("Bash", {"stdout": report_text, "stderr": ""})
        hook_input["tool_input"] = {"command": "python scripts/dump_playbook.py 190"}
        assert handler.matches(hook_input) is False

    def test_excluded_tools_configurable(self, handler: BudgetExhaustionDetectorHandler) -> None:
        handler._excluded_tools = ["Bash"]
        hook_input = _tool_input(
            "Bash", {"stdout": "budget exhausted for this session", "stderr": ""}
        )
        assert handler.matches(hook_input) is False


# ─── Ledger self-feed: structural JSON-shape recognition (Task 1.4 / F2) ─────


class TestLedgerSelfFeedStructural:
    """A ledger LINE contains neither the handler name nor the ledger
    filename, so the literal marker guards never covered it (PLAN.md F2).
    These commands were the plan's own reproduction of the self-feed: none
    of them spells `budget-exhaustion-events.jsonl`, so only a structural
    recognition of the ledger's own JSON record shape closes the gap.
    """

    _LEDGER_LINE = (
        '{"timestamp": "2026-09-02T00:00:00+00:00", "session_id": "sess-old", '
        '"tool_name": "Bash", "matched_fragment": "budget exhausted for this '
        'operation"}'
    )

    _LEDGER_PRETTY = (
        "{\n"
        '  "timestamp": "2026-09-02T00:00:00+00:00",\n'
        '  "session_id": "sess-old",\n'
        '  "tool_name": "Bash",\n'
        '  "matched_fragment": "budget exhausted for this operation"\n'
        "}"
    )

    def test_cat_glob_of_ledger_directory_never_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """`cat untracked/*.jsonl` -- no filename is spelled in the command."""
        hook_input = _tool_input("Bash", {"stdout": self._LEDGER_LINE, "stderr": ""})
        hook_input["tool_input"] = {"command": "cat untracked/*.jsonl"}
        assert handler.matches(hook_input) is False

    def test_jq_pretty_printed_ledger_never_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """`jq .` reformats the record across several lines, defeating a
        naive per-line JSON parse -- the recognizer must survive that."""
        hook_input = _tool_input("Bash", {"stdout": self._LEDGER_PRETTY, "stderr": ""})
        hook_input["tool_input"] = {"command": "jq . untracked/budget*.jsonl"}
        assert handler.matches(hook_input) is False

    def test_tail_of_ledger_env_var_never_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """`tail -n 20 "$LEDGER"` -- the path is a shell variable, never a
        literal filename the command-marker guard could key on."""
        hook_input = _tool_input("Bash", {"stdout": self._LEDGER_LINE, "stderr": ""})
        hook_input["tool_input"] = {"command": 'tail -n 20 "$LEDGER"'}
        assert handler.matches(hook_input) is False

    def test_ledger_json_shape_recognized_independent_of_command(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The JSON-shape recognition is a property of the RESPONSE text, not
        the command that produced it -- a non-passthrough command (here,
        python) dumping ledger-shaped JSON must still be excluded."""
        hook_input = _tool_input("Bash", {"stdout": self._LEDGER_LINE, "stderr": ""})
        hook_input["tool_input"] = {"command": "python3 -c \"print(open('x.jsonl').read())\""}
        assert handler.matches(hook_input) is False

    def test_ledger_shape_requires_all_four_keys(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """A JSON object missing two of the ledger's record keys (and
        carrying neither self-referential marker string) is NOT recognized
        as ledger content -- this guards against the recognizer being so
        loose it swallows a genuine structured tool response that merely
        happens to be a JSON object."""
        partial = (
            '{"tool_name": "Bash", "timestamp": "2026-01-01T00:00:00+00:00"} '
            "budget exhausted here"
        )
        hook_input = _tool_input("Bash", {"stdout": partial, "stderr": ""})
        assert handler.matches(hook_input) is True


# ─── Content-passthrough Bash commands (Task 4.5) ────────────────────────────


class TestContentPassthroughCommands:
    """A Bash command whose entire pipeline is content-passthrough verbs
    (cat/head/tail/grep/jq/awk/sed/...) reproduces or reformats bytes that
    already exist somewhere -- it never independently discovers a live
    budget signal. PLAN.md Task 4.5's `grep` reproduction is the concrete
    case: a generated playbook quoting the Test 187 fixture, with neither
    marker present.
    """

    # The Test 187 fixture, quoted the way a generated playbook would --
    # deliberately carrying NEITHER self-referential marker (no
    # "budget_exhaustion_detector", no "BudgetExhaustionDetectorHandler", no
    # ledger filename), which is exactly what made this false-fire slip past
    # the pre-existing marker guards during the v3.60.0 gate.
    _QUOTED_FIXTURE = (
        "#187 [PostToolUse]\n"
        "  command  : Simulate a WebSearch tool response containing the text\n"
        "    'Web search was not performed: this session has used its web\n"
        "    search budget (200 of 200 WebSearch calls).'"
    )

    @pytest.mark.parametrize(
        "command",
        [
            'grep -A3 "Test 187" playbook.md',
            "head -n 40 playbook.md",
            "awk '/Test 187/{print}' playbook.md",
        ],
    )
    def test_grep_of_generated_playbook_never_fires(
        self, handler: BudgetExhaustionDetectorHandler, command: str
    ) -> None:
        hook_input = _tool_input("Bash", {"stdout": self._QUOTED_FIXTURE, "stderr": ""})
        hook_input["tool_input"] = {"command": command}
        assert handler.matches(hook_input) is False

    def test_blank_command_is_not_passthrough(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """An empty/whitespace-only command has no verb at all -- it must not
        vacuously satisfy "every segment is passthrough" and grant an
        exemption nothing justified."""
        hook_input = _tool_input(
            "Bash", {"stdout": "budget exhausted for this operation", "stderr": ""}
        )
        hook_input["tool_input"] = {"command": "   "}
        assert handler.matches(hook_input) is True

    def test_curl_piped_to_jq_still_fires(self, handler: BudgetExhaustionDetectorHandler) -> None:
        """A LIVE fetch piped through a passthrough formatter must stay
        eligible -- jq alone in the pipeline must not blanket-exempt curl's
        genuinely-fetched content. Guards against over-broadening the
        passthrough classification to "any pipeline containing jq"."""
        hook_input = _tool_input(
            "Bash",
            {"stdout": "Request denied: quota exceeded for this resource.", "stderr": ""},
        )
        hook_input["tool_input"] = {"command": "curl -s https://api.example.com/status | jq ."}
        assert handler.matches(hook_input) is True

    def test_live_curl_command_alone_still_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """A bare live command (not a passthrough verb) must keep firing --
        the passthrough classification must not weaken genuine detection."""
        hook_input = _tool_input(
            "Bash",
            {"stdout": "budget exhausted for this operation", "stderr": ""},
        )
        hook_input["tool_input"] = {"command": "curl -s https://api.example.com/status"}
        assert handler.matches(hook_input) is True

    def test_python_generated_report_without_marker_still_fires(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """A generated-report command (python, not a passthrough verb)
        producing genuinely new prose with no self-referential marker must
        still fire -- only a passthrough VERB or a self-referential marker
        exempts a Bash response, not "any script that prints text"."""
        hook_input = _tool_input(
            "Bash",
            {"stdout": "quota exceeded for this resource right now.", "stderr": ""},
        )
        hook_input["tool_input"] = {"command": "python scripts/report.py"}
        assert handler.matches(hook_input) is True


# ─── Sub-agent dispatch reports (Task 4.5) ───────────────────────────────────


class TestSubagentDispatchReportNeverFires:
    """A dispatched sub-agent's final message is composed prose an LLM wrote,
    not a field the Task/Agent tool integration populates from a live budget
    check -- the same category as a file the model merely read. If the
    sub-agent's OWN work genuinely hit a budget, that already fired directly
    in the sub-agent's own session at the tool call that hit it; this
    orchestrator-side echo is a redundant, quotation-prone restatement
    (PLAN.md Task 4.5's "sub-agent dispatch prompt that cited the fixture
    string" incident)."""

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


class TestExtraPatterns:
    def test_extra_patterns_are_additive(self, handler: BudgetExhaustionDetectorHandler) -> None:
        handler._extra_patterns = [r"custom budget ceiling hit"]
        hook_input = _tool_input(
            "Bash", {"stdout": "custom budget ceiling hit today", "stderr": ""}
        )
        assert handler.matches(hook_input) is True


# ─── Never blocks ─────────────────────────────────────────────────────────────


class TestNeverBlocks:
    def test_decision_is_always_allow(self, handler: BudgetExhaustionDetectorHandler) -> None:
        hook_input = _tool_input(
            "Bash", {"stdout": "quota exceeded for this operation", "stderr": ""}
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


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
            "Bash",
            {"stdout": "quota exceeded for this operation", "stderr": ""},
            session_id="sess-ledger",
        )
        handler.handle(hook_input)

        ledger_path = tmp_path / "budget-exhaustion-events.jsonl"
        assert ledger_path.exists()
        lines = [ln for ln in ledger_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["session_id"] == "sess-ledger"
        assert record["tool_name"] == "Bash"
        assert "timestamp" in record
        assert "quota exceeded" in record["matched_fragment"]

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
            "Bash", {"stdout": "quota exceeded for this operation", "stderr": ""}
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

    def test_acceptance_tests_include_advisory_and_near_miss(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 2
