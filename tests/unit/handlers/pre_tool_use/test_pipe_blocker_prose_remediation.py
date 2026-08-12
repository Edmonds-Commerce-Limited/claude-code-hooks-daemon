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


class TestProseIsDetectedEvenWhenItStartsWithACommandName:
    """The second trigger: prose whose FIRST word happens to be a real
    command name is still prose, caught by function-word density.

    This class previously asserted the same behaviour for the wrong reason —
    that the segment was "very long", and that a long segment "is still not a
    real shell command". The example below is indeed prose, so the assertion
    was right, but the premise was false and shipped a defect: an 82-character
    `git merge-tree` invocation was classified as prose purely on length (see
    TestLongRealCommandsAreNotProse). The example is retained unchanged; only
    the claimed reason is corrected, because it is the reason a future reader
    would generalise from.
    """

    def test_prose_starting_with_a_command_name_skips_template(self) -> None:
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


class TestLongRealCommandsAreNotProse:
    """Phase 4 (RED first): the inverse question Phase 1 never asked.

    Phase 1 verified only that long PROSE is classified as prose. It never
    asked whether a long string might be a real COMMAND — and in this
    repository that is the ordinary case, not an exotic one: worktree branch
    names are 32 characters and absolute paths under ``/workspace`` are long
    by construction, so an 80-character command is unremarkable.

    Caught by dogfooding, not by a test. This exact invocation was denied
    with the prose reason during the Plan 00218 merge::

        git merge-tree --write-tree --name-only main agent-<32-char-name> 2>&1

    The DENY was correct (``git merge-tree`` is not whitelisted), but the
    prose reason withholds the matched text and the ``extra_whitelist``
    remediation, and closes with "no action needed beyond retrying" — which
    is FALSE for a real command, since retrying re-blocks identically.

    Length is therefore not evidence of prose. English is.
    """

    # The literal 82-character segment that triggered the defect. Kept
    # verbatim rather than parameterised: the point is that a REAL command
    # from this repo's ordinary workflow crossed the old 80-char trigger.
    FIELD_CASE = (
        "git merge-tree --write-tree --name-only main " "agent-ad3d35fcc36d13959-4c36fb42 2>&1"
    )

    def test_the_field_case_is_long_enough_to_have_tripped_the_old_trigger(self) -> None:
        """Positive control for this test class.

        Without this, a future change that shortened the fixture would make
        every assertion below pass vacuously against a segment that never
        exercised the length path at all.
        """
        assert len(self.FIELD_CASE) > 80

    def test_field_case_gets_the_real_remediation_not_the_prose_reason(self) -> None:
        handler = PipeBlockerHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": f"{self.FIELD_CASE} | head -20"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "extra_whitelist" in result.reason
        assert "does not look like a real shell command" not in result.reason

    def test_long_real_commands_are_never_classified_as_prose(self) -> None:
        """A corpus of long commands drawn from this repo's actual workflow.

        Every one exceeds the old 80-character trigger and every one is a
        genuine command, so each must receive actionable remediation.
        """
        long_real_commands = (
            "git log --oneline --graph --decorate --all --since=2026-01-01 "
            "-- src/claude_code_hooks_daemon/handlers/pre_tool_use",
            "/workspace/untracked/venv-workspace-py311-81c29529/bin/python3 "
            "-m pytest tests/unit/handlers/pre_tool_use --tb=short -q",
            "git diff --stat main...agent-ad3d35fcc36d13959-4c36fb42 "
            "-- src/claude_code_hooks_daemon/plan_qa/checks/index_row_length.py",
            "docker run --rm -v /workspace:/workspace -w /workspace "
            "--entrypoint /bin/bash ghcr.io/example/builder:latest -lc make",
        )
        handler = PipeBlockerHandler()
        for command in long_real_commands:
            assert len(command) > 80, f"fixture too short to exercise the bug: {command}"
            result = handler.handle(
                {"tool_name": "Bash", "tool_input": {"command": f"{command} | head -20"}}
            )
            assert result.decision == Decision.DENY
            assert (
                "does not look like a real shell command" not in result.reason
            ), f"real command misclassified as prose: {command}"

    def test_commands_carrying_quoted_english_are_not_prose(self) -> None:
        """Shell quoting is where English legitimately lives inside a command.

        Both producers are NON-whitelisted, so they genuinely reach
        ``handle()`` — a whitelisted producer like ``echo`` never does, and
        would exercise nothing.

        The second case is the one that matters: matching only tokens that
        BEGIN with a quote missed ``note="this``, so a real command scored
        36% function words and was classified as prose. That was a narrower
        instance of the very defect this class exists to prevent, found by
        probing the fix rather than by assuming it worked.
        """
        handler = PipeBlockerHandler()
        quoted_english_commands = (
            'docker run --name "the box that is in the room" ubuntu',
            'kubectl annotate pod x note="this is the thing that was broken"',
        )
        for command in quoted_english_commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": f"{command} | head -5"},
            }
            assert handler.matches(hook_input), f"fixture is whitelisted, proves nothing: {command}"
            result = handler.handle(hook_input)
            assert (
                "does not look like a real shell command" not in result.reason
            ), f"quoted English misread as prose: {command}"

    def test_prose_is_still_detected(self) -> None:
        """Negative control: fixing the false positive must not blind the
        heuristic to the field-report case it was built for."""
        handler = PipeBlockerHandler()
        prose = (
            "the guardrail blocks piping straight to a pager and that is why "
            "the earlier command was refused"
        )
        result = handler.handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"cat >> f.md <<'EOF'\n{prose} | tail -5\nEOF\n"},
            }
        )
        assert result.decision == Decision.DENY
        assert "extra_whitelist" not in result.reason


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
