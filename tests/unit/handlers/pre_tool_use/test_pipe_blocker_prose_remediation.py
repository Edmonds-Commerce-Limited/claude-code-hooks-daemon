"""Regression tests for the pipe_blocker remediation-output defect (Plan 00209 §1).

Field report: appending a journal entry via a heredoc whose PROSE described
two earlier pipe blocks tripped pipe_blocker (the literal characters of a
pipe-to-pager appeared inside the heredoc body). The block itself is
defensible — erring toward caution is correct for a safety handler. The
defect is what happened NEXT: the matched "command" was run through the
verbose remediation template, which extracted the first word of a SENTENCE
("the") as a binary name and offered `extra_whitelist: - "^the\\b"`, plus a
full echd-capture/temp-file recommendation block — a correct safety decision
presented in a way that reads as broken, burning a large amount of context
re-quoting text the agent had just written.

These tests are Task 1.1 (RED first): a heredoc body of prose must produce a
SHORT block reason with NO remediation template and NO echoed prose.
"""

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestProseFalseTriggerGetsNoRemediationTemplate:
    """Task 1.1/1.2: prose containing a literal pipe-to-pager pattern must
    not be run through the extra_whitelist/echd-capture remediation
    template, and must not have its full text echoed back."""

    def _heredoc_journal_command(self) -> str:
        """Reproduces the field report almost verbatim: a `cat >>` heredoc
        whose body prose describes an earlier pipe block, with "the" as the
        first word of the line containing the literal "| tail" text."""
        return (
            "cat >> JOURNAL.md <<'EOF'\n"
            "We fixed two earlier issues today.\n"
            "the guardrail blocks piping straight to a pager e.g. echo x | tail -5\n"
            "EOF\n"
        )

    def test_matches_the_prose_heredoc(self) -> None:
        """Sanity: this really is the scenario the field report hit — the
        handler's pipe-detection regex does match literal heredoc prose
        (the detection itself is correct and out of scope per Non-Goals)."""
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": self._heredoc_journal_command()},
        }
        assert handler.matches(hook_input)

    def test_denies_without_extra_whitelist_template(self) -> None:
        """The old bug: emitted `extra_whitelist: - "^the\\b"` — extracting
        "the" as a binary name. That fabricated scaffolding must be gone."""
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": self._heredoc_journal_command()},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "extra_whitelist" not in result.reason
        assert '"^the' not in result.reason

    def test_denies_without_echd_capture_recommendation(self) -> None:
        """No `set -o pipefail` / echd-capture / temp-file scaffolding either
        — none of that helps when the matched text was never a real pipe."""
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": self._heredoc_journal_command()},
        }
        result = handler.handle(hook_input)
        assert "echd-capture" not in result.reason
        assert "set -o pipefail" not in result.reason
        assert "TEMP_FILE" not in result.reason

    def test_denies_without_echoing_the_prose_back(self) -> None:
        """The specific embarrassment: several hundred lines of the agent's
        own English, wrapped in shell scaffolding. The reason must not
        contain the journal prose."""
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": self._heredoc_journal_command()},
        }
        result = handler.handle(hook_input)
        assert "We fixed two earlier issues today" not in result.reason
        assert "guardrail blocks piping straight to a pager" not in result.reason

    def test_reason_is_short(self) -> None:
        """The whole point: a short, accurate block reason (Success Criteria)."""
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": self._heredoc_journal_command()},
        }
        result = handler.handle(hook_input)
        assert len(result.reason) < 800

    def test_reason_still_explains_why_it_was_blocked(self) -> None:
        """A short reason must still be an ACCURATE one, not just terse."""
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": self._heredoc_journal_command()},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason
        assert "handlers.pre_tool_use.pipe_blocker" in result.reason


class TestSaneLengthTriggerAlsoSkipsTemplating:
    """Task 1.2's second, independent trigger: even when the first word
    happens to look plausible, a very long matched segment is still not a
    real shell command and must skip templating."""

    def test_long_segment_with_plausible_first_word_skips_template(self) -> None:
        handler = PipeBlockerHandler()
        long_prose = (
            "grep is a tool but this whole sentence is way too long to plausibly "
            "be a real shell command sitting right before a pipe to tail so it "
            "should be treated as prose even though it starts with a real command "
            "name | tail -5"
        )
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": f"cat >> f.md <<'EOF'\n{long_prose}\nEOF\n"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "extra_whitelist" not in result.reason
        assert "echd-capture" not in result.reason


class TestRealPipeBlocksAreUnaffected:
    """Non-regression: genuine short commands piped to tail/head still get
    the full, helpful remediation template — this fix must not degrade the
    handler's core value (Non-Goals: detection is unchanged)."""

    def test_pytest_pipe_tail_still_gets_blacklisted_template(self) -> None:
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/ | tail -20"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "expensive" in result.reason

    def test_docker_ps_pipe_tail_still_gets_unknown_template(self) -> None:
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker ps -a | tail -20"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "extra_whitelist" in result.reason
