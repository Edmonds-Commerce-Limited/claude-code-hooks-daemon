"""Block an oversized subagent final message until it is routed through a file.

Plan 00307 Task 3.1. Task 1.1's live reproduction dispatched a subagent
instructed to return a ~24k-token final message inline: the harness silently
elided the MIDDLE of the payload (an explicit truncation marker appeared,
mid-section, with both start/end sentinels surviving) — so the coordinator
can receive a report that LOOKS complete while content is missing. Prevention
at dispatch (``dispatch_declaration``) cannot catch an agent that ignores the
contract; this handler is the backstop at return time: it reads
``last_assistant_message`` directly off the SubagentStop hook input (no
transcript parse needed — the vendored contract delivers it verbatim) and
blocks the stop when it exceeds a configured character threshold.

Design constraints pinned:

- **Fail open** on any missing/malformed input — a handler that cannot judge
  size must never block.
- **Re-entry guard** — ``stop_hook_active: true`` must never be blocked
  again, or the subagent loops forever.
- **Reads the CURRENT field name** — ``last_assistant_message``, not the
  stale ``subagent_id``/``subagent_type`` the input schema used to declare
  exclusively.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_report_size_blocker import (
    SubagentReportSizeBlockerHandler,
)


def _subagent_stop_input(message: str, **extra: Any) -> dict[str, Any]:
    # Plan 00460: default agent_type is a documented WRITABLE built-in
    # (general-purpose), not "Explore" -- Explore is genuinely read-only, so
    # tests exercising the pre-00460 write-to-file behaviour need a type that
    # still resolves that way. TestReadOnlyAgent below covers Explore itself.
    payload: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "agent_id": "agent-1",
        "agent_type": "general-purpose",
        "last_assistant_message": message,
        "stop_hook_active": False,
    }
    payload.update(extra)
    return payload


@pytest.fixture
def handler(tmp_path: Path) -> SubagentReportSizeBlockerHandler:
    """Review m10: without an explicit test seam, `_agent_can_write` falls
    back to `Path.cwd()` for the project-agent lookup and `Path.home()` for
    the user-agent one -- both real, live filesystem locations that can
    hold a `.claude/agents/*.md` this dogfooding checkout genuinely ships
    (a real risk since review M4 now consults project/user agents BEFORE
    the built-in table). Rooting both at fresh, empty tmp_path
    subdirectories by default makes every test hermetic; a test that wants
    a real project/user agent file still creates one under these same
    directories."""
    instance = SubagentReportSizeBlockerHandler()
    instance._project_root = tmp_path / "project"
    instance._home_dir = tmp_path / "home"
    return instance


class TestIdentity:
    def test_exposes_claude_md_guidance(self, handler: SubagentReportSizeBlockerHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "subagent-reports" in guidance


class TestMatching:
    def test_matches_normal_subagent_stop(self, handler: SubagentReportSizeBlockerHandler) -> None:
        assert handler.matches(_subagent_stop_input("short report")) is True

    def test_does_not_match_re_entry(self, handler: SubagentReportSizeBlockerHandler) -> None:
        hook_input = _subagent_stop_input("x" * 10_000, stop_hook_active=True)
        assert handler.matches(hook_input) is False


class TestSizeThreshold:
    def test_allows_short_message(self, handler: SubagentReportSizeBlockerHandler) -> None:
        result = handler.handle(_subagent_stop_input("done, wrote report to disk"))

        assert result.decision == Decision.ALLOW

    def test_blocks_oversized_message(self, handler: SubagentReportSizeBlockerHandler) -> None:
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" in result.reason

    def test_allows_message_exactly_at_threshold(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        at_threshold = "x" * handler._threshold_chars

        result = handler.handle(_subagent_stop_input(at_threshold))

        assert result.decision == Decision.ALLOW

    def test_threshold_is_configurable(self, handler: SubagentReportSizeBlockerHandler) -> None:
        handler._threshold_chars = 10

        result = handler.handle(_subagent_stop_input("this message is longer than ten chars"))

        assert result.decision == Decision.DENY

    def test_string_threshold_option_is_coerced(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        """N3 code-review fix: a YAML author writing ``threshold_chars: "10"``
        (a string) must not raise ``TypeError`` from ``len(message) <= "10"``
        inside a TERMINAL SubagentStop handler -- it must be parsed as an int."""
        handler._threshold_chars = "10"

        result = handler.handle(_subagent_stop_input("this message is longer than ten chars"))

        assert result.decision == Decision.DENY

    def test_malformed_threshold_option_falls_back_to_default(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        handler._threshold_chars = "not-a-number"

        short_message = "short"
        result = handler.handle(_subagent_stop_input(short_message))

        assert result.decision == Decision.ALLOW


class TestPrescriptiveFallbackPath:
    """Task 4.2: the deny reason must PRESCRIBE an exact, writable path."""

    def test_deny_reason_prescribes_a_concrete_fallback_path(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        oversized = "x" * (handler._threshold_chars + 1)

        # A WRITABLE agent_type: Explore is genuinely read-only as of Plan
        # 00460 and takes the condense path instead (see TestReadOnlyAgent).
        result = handler.handle(_subagent_stop_input(oversized, agent_type="general-purpose"))

        assert result.reason is not None
        # yymmdd (today's date, 6 digits) + the real agent_type + the
        # documented model placeholder, under the fallback dir.
        yymmdd = datetime.now(tz=UTC).strftime("%y%m%d")
        assert f"untracked/agent-reports/{yymmdd}-general-purpose-{{model}}.md" in result.reason

    def test_deny_reason_uses_placeholder_when_agent_type_missing(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        oversized = "x" * (handler._threshold_chars + 1)
        hook_input = _subagent_stop_input(oversized)
        del hook_input["agent_type"]

        result = handler.handle(hook_input)

        assert result.reason is not None
        assert "{agent-name}" in result.reason

    def test_fallback_report_dir_is_configurable(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        handler._fallback_report_dir = "untracked/custom-reports/"
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized))

        assert result.reason is not None
        assert "untracked/custom-reports/" in result.reason

    def test_prescribed_fallback_path_is_allowed_by_markdown_organization(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        """Pin Task 4.2 finding 2: the two handlers must never argue."""
        from pathlib import Path
        from unittest.mock import patch

        from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
            MarkdownOrganizationHandler,
        )

        path = handler._prescribed_fallback_path(_subagent_stop_input("x", agent_type="Explore"))
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as mock_root:
            mock_root.return_value = Path("/tmp/test")
            location_handler = MarkdownOrganizationHandler()
            write_input = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": path, "content": "report"},
            }

            # matches() False means the write is NOT intercepted as a wrong
            # location -- i.e. the path is allowed.
            assert location_handler.matches(write_input) is False


class TestReadOnlyAgent:
    """Plan 00460: an agent type with no `Write` tool must never be told to
    write the report to a file -- it gets a condense-and-reply way out
    instead, with an explicit Bash-workaround warning. A writable or
    unresolvable type keeps today's behaviour byte-identical."""

    def test_builtin_read_only_agent_gets_condense_message(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized, agent_type="Explore"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" not in result.reason
        assert "Explore" in result.reason
        assert "no `Write` tool" in result.reason
        assert "Condense" in result.reason

    def test_read_only_message_forbids_bash_workaround(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized, agent_type="Plan"))

        assert result.reason is not None
        assert "heredoc" in result.reason
        assert "content guards" in result.reason

    def test_builtin_writable_agent_behaviour_unchanged(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized, agent_type="general-purpose"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" in result.reason

    def test_unresolvable_agent_type_behaviour_unchanged(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        """An agent type this resolver cannot classify (no built-in match, no
        `.claude/agents/*.md` file) keeps today's write-to-file instruction --
        the fail-safe default for `None` (Plan 00460 Task 1.1)."""
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized, agent_type="totally-custom-type"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" in result.reason

    def test_project_agent_without_write_tool_gets_condense_message(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Any
    ) -> None:
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "code-reviewer.md").write_text(
            "---\nname: code-reviewer\ndescription: reviews code\n"
            "tools: Read, Glob, Grep, Bash\n---\n\nBody.\n"
        )
        handler._project_root = tmp_path
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized, agent_type="code-reviewer"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" not in result.reason
        assert "code-reviewer" in result.reason


class TestPersistedReportLookup:
    """Plan 00460 Task 1.6: when `subagent_report_persistence` already saved
    the reply, point the agent at that path instead of asking it to write
    (or condense into) one -- for EVERY agent type, read-only or writable.
    The old messages survive only as the fallback when nothing was found.

    Review m6: the persisted-report directory now matches the persister's
    real default (`.../auto/`), not the shared `untracked/agent-reports/`.
    Review m2: a cited match's content must equal the CURRENT
    `last_assistant_message` -- so every "already saved" test below writes
    the persisted file with that exact content, not an arbitrary stand-in.
    """

    def test_points_writable_agent_at_the_saved_path(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Path
    ) -> None:
        handler._project_root = tmp_path
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        report_dir.mkdir(parents=True)
        oversized = "x" * (handler._threshold_chars + 1)
        saved = report_dir / "260924-134530-general-purpose-agent-1.md"
        saved.write_text(oversized)

        result = handler.handle(_subagent_stop_input(oversized, agent_id="agent-1"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert str(saved) in result.reason
        assert "already saved" in result.reason

    def test_points_read_only_agent_at_the_saved_path(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Path
    ) -> None:
        handler._project_root = tmp_path
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        report_dir.mkdir(parents=True)
        oversized = "x" * (handler._threshold_chars + 1)
        saved = report_dir / "260924-134530-Explore-agent-9.md"
        saved.write_text(oversized)

        result = handler.handle(
            _subagent_stop_input(oversized, agent_type="Explore", agent_id="agent-9")
        )

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert str(saved) in result.reason
        assert "Bash" in result.reason

    def test_saved_path_message_never_instructs_a_fresh_write(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Path
    ) -> None:
        handler._project_root = tmp_path
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        report_dir.mkdir(parents=True)
        oversized = "x" * (handler._threshold_chars + 1)
        (report_dir / "260924-134530-general-purpose-agent-1.md").write_text(oversized)

        result = handler.handle(_subagent_stop_input(oversized, agent_id="agent-1"))

        assert result.reason is not None
        assert "Write the full report to a file now" not in result.reason

    def test_saved_path_message_does_not_overclaim_content_safety(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Path
    ) -> None:
        """Review M3: the persister runs NO content checks (its own
        docstring says so) -- the deny message must not tell an LLM that
        relays it to the coordinator otherwise."""
        handler._project_root = tmp_path
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        report_dir.mkdir(parents=True)
        oversized = "x" * (handler._threshold_chars + 1)
        (report_dir / "260924-134530-Explore-agent-1.md").write_text(oversized)

        result = handler.handle(
            _subagent_stop_input(oversized, agent_type="Explore", agent_id="agent-1")
        )

        assert result.reason is not None
        assert "content-safe" not in result.reason
        assert "content checks" not in result.reason

    def test_a_match_with_different_content_is_not_cited(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Path
    ) -> None:
        """Review m2 (probe P8): a resumed agent keeps its `agent_id`. If
        THIS stop's write failed, the glob would otherwise still find an
        EARLIER stop's file for the same agent_id and cite it as though it
        held the current reply -- only a content match may be cited."""
        handler._project_root = tmp_path
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        report_dir.mkdir(parents=True)
        (report_dir / "260920-100000-general-purpose-agent-1.md").write_text(
            "an EARLIER stop's reply, not this one"
        )
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized, agent_id="agent-1"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "already saved" not in result.reason
        assert "subagent-reports" in result.reason

    def test_falls_back_to_the_old_writable_message_when_nothing_was_persisted(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Path
    ) -> None:
        handler._project_root = tmp_path
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(_subagent_stop_input(oversized, agent_id="no-such-agent"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "subagent-reports" in result.reason

    def test_falls_back_to_the_old_read_only_message_when_nothing_was_persisted(
        self, handler: SubagentReportSizeBlockerHandler, tmp_path: Path
    ) -> None:
        handler._project_root = tmp_path
        oversized = "x" * (handler._threshold_chars + 1)

        result = handler.handle(
            _subagent_stop_input(oversized, agent_type="Explore", agent_id="no-such-agent")
        )

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "Condense" in result.reason


class TestFailOpen:
    def test_allows_when_last_assistant_message_missing(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        hook_input = {"hook_event_name": "SubagentStop", "stop_hook_active": False}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW

    def test_allows_when_last_assistant_message_is_not_a_string(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        hook_input = _subagent_stop_input("placeholder")
        hook_input["last_assistant_message"] = {"not": "a string"}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW

    def test_matches_returns_true_on_malformed_hook_input(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        # matches() must not raise on a hook_input missing expected keys; the
        # fail-open decision is made in handle(), not by silently skipping.
        assert handler.matches({}) is True


class TestDeclaredAcceptanceTestsAreProducible:
    """Plan 00319 Task 4.6: every declared `hook_input` really drives the

    handler to its declared decision, and every declared pattern really
    appears in the reason produced. `SubagentStop` has no tool call for a
    `ToolPayload` to describe, which is exactly why these two tests declare
    `hook_input` directly rather than `tool_payload`.
    """

    def test_every_blocking_test_hook_input_produces_its_declared_decision_and_patterns(
        self, handler: SubagentReportSizeBlockerHandler
    ) -> None:
        import re

        from claude_code_hooks_daemon.core import TestType

        tests = [t for t in handler.get_acceptance_tests() if t.test_type == TestType.BLOCKING]
        assert tests, "fixture handler declared no BLOCKING tests"

        for test in tests:
            assert (
                test.hook_input is not None
            ), f"{test.title!r} declares no hook_input to drive it with"
            result = handler.handle(test.hook_input)
            assert (
                result.decision == test.expected_decision
            ), f"{test.title!r}: expected {test.expected_decision}, got {result.decision}"
            for pattern in test.expected_message_patterns:
                assert re.search(
                    pattern, result.reason or ""
                ), f"{test.title!r}: pattern {pattern!r} not found in: {result.reason}"
