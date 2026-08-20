"""Tests for PlanNumberHelperHandler.

This handler prevents Claude from using broken bash commands to discover plan numbers.
Instead, it provides the correct next plan number via context injection.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation tests."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper import (
    PlanNumberHelperHandler,
)


class TestPlanNumberHelperHandler:
    """Test plan number helper handler."""

    @pytest.fixture
    def handler_enabled(self, tmp_path: Path) -> PlanNumberHelperHandler:
        """Create handler with planning mode enabled."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        return handler

    @pytest.fixture
    def handler_disabled(self, tmp_path: Path) -> PlanNumberHelperHandler:
        """Create handler with planning mode disabled."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = None  # Planning mode disabled
        return handler

    @pytest.fixture
    def handler_with_workflow_docs(self, tmp_path: Path) -> PlanNumberHelperHandler:
        """Create handler with workflow docs configured."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        handler._plan_workflow_docs = "CLAUDE/PlanWorkflow.md"

        # Create the workflow docs file
        workflow_file = tmp_path / "CLAUDE" / "PlanWorkflow.md"
        workflow_file.parent.mkdir(parents=True, exist_ok=True)
        workflow_file.write_text("# Plan Workflow\n\nGuidance here...")

        return handler

    def test_initialization(self) -> None:
        """Handler should initialize with correct settings."""
        handler = PlanNumberHelperHandler()
        assert handler.name == "plan-number-helper"
        assert handler.priority == 30  # Run before other workflow handlers
        assert handler.terminal  # Block broken commands
        assert "workflow" in handler.tags
        # "blocking", not "advisory" -- and the line above is why: this test
        # asserted `terminal` with the comment "Block broken commands" while
        # simultaneously pinning an advisory tag. _detect_behavior checks the
        # advisory tag BEFORE the terminal flag, so the tag won and the
        # generated table called this handler ADVISORY.
        assert "blocking" in handler.tags
        assert "advisory" not in handler.tags

    def test_disabled_when_planning_mode_off(
        self, handler_disabled: PlanNumberHelperHandler
    ) -> None:
        """Handler should not match when planning mode is disabled."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1"},
        }

        assert not handler_disabled.matches(hook_input)

    def test_detects_ls_glob_pattern(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should detect ls commands with glob patterns on plan directory."""
        commands = [
            "ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1",
            "ls -d CLAUDE/Plan/[0-9]* | tail -1",
            "ls CLAUDE/Plan/ | grep -E '^[0-9]' | sort | tail -1",
            "ls -1 CLAUDE/Plan | sort -n | tail -1",
        ]

        for command in commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert handler_enabled.matches(hook_input), f"Should match: {command}"

    def test_detects_ls_piped_to_grep_for_numbers(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Should detect ls on plan directory piped to grep filtering for numbers."""
        commands = [
            "ls -1 CLAUDE/Plan/ | grep -E '^[0-9]+'",
            "ls CLAUDE/Plan/ | grep '^[0-9]'",
            "ls -la CLAUDE/Plan | grep -E '^d[0-9]'",
            "ls CLAUDE/Plan | grep '[0-9]'",
            # Bug: This command was NOT blocked but should have been
            "ls -la /workspace/CLAUDE/Plan/ | grep -E '^d' | grep -E '[0-9]{3}-'",
        ]

        for command in commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert handler_enabled.matches(hook_input), f"Should match: {command}"

    def test_detects_find_commands(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should detect find commands on plan directory."""
        commands = [
            "find CLAUDE/Plan -maxdepth 1 -type d | tail -1",
            "find CLAUDE/Plan/ -name '0*' -type d",
            "find CLAUDE/Plan -type d -name '[0-9]*' | sort | tail -1",
        ]

        for command in commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert handler_enabled.matches(hook_input), f"Should match: {command}"

    def test_detects_glob_expansion(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should detect glob expansion attempts."""
        commands = [
            "echo CLAUDE/Plan/0* | awk '{print $NF}'",
            "printf '%s\\n' CLAUDE/Plan/[0-9]* | tail -1",
        ]

        for command in commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert handler_enabled.matches(hook_input), f"Should match: {command}"

    def test_ignores_multi_command_pipeline_with_unrelated_echo(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        r"""Regression: should NOT match when echo and CLAUDE/Plan are in different subcommands.

        Bug: echo\s+.*CLAUDE/Plan/ regex was too greedy, matching `echo "$DATABASE_URL"`
        from one subcommand with a CLAUDE/Plan path in a `cat` command elsewhere in the
        same pipeline, causing a false positive block.
        """
        # Command that parses DATABASE_URL via echo|sed, then runs mysql with a SQL file
        # stored in the plan folder — echo and CLAUDE/Plan/ are completely unrelated here.
        command = (
            "source /srv/example-app/quoting-dsm-api/.env && "
            "DB_HOST=$(echo \"$DATABASE_URL\" | sed 's|mysql://[^@]*@||;s|/.*||;s|:.*||') && "
            "DB_USER=$(echo \"$DATABASE_URL\" | sed 's|mysql://||;s|:.*||') && "
            "DB_PASS=$(echo \"$DATABASE_URL\" | sed 's|mysql://[^:]*:||;s|@.*||') && "
            'mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASS" mydb '
            '-e "$(cat /srv/example-app/quoting/CLAUDE/Plan/00003-stats/report.sql)" '
            '> /tmp/output.tsv 2>&1; echo "EXIT: $?"'
        )
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        assert not handler_enabled.matches(
            hook_input
        ), "Should NOT match: echo and CLAUDE/Plan/ path are in different subcommands"

    def test_ignores_echo_and_plan_glob_on_separate_lines(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        r"""Regression: a NEWLINE separates commands just as ``;``/``&``/``|`` do.

        Bug: the glob patterns used ``[^;&|]*`` to stop ``echo`` matching a
        ``CLAUDE/Plan/`` glob in a *different* subcommand, but a negated
        character class also matches ``\n``. So an ``echo`` on line 1 reached
        forward across the newline into an unrelated command on line 2 and
        borrowed its glob character.

        Hit while running a content grep whose ONLY plan reference was an
        exclusion glob — the exact false-positive class the ``[^;&|]`` guard
        was written to prevent.
        """
        command = (
            'echo "=== $PYTHON occurrences ==="\n'
            "rg -c 'PYTHON' --glob '!CLAUDE/Plan/Completed/**' ."
        )
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        assert not handler_enabled.matches(
            hook_input
        ), "Should NOT match: echo and the plan glob are on separate lines"

    def test_ignores_safe_commands(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should not match safe commands."""
        safe_commands = [
            "ls -la",
            "find . -name '*.py'",
            "cat CLAUDE/Plan/00042-feature/PLAN.md",
            "mkdir -p CLAUDE/Plan/00123-new-feature",
            "git status",
        ]

        for command in safe_commands:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert not handler_enabled.matches(hook_input), f"Should NOT match: {command}"

    def test_ignores_non_bash_tools(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Should only match Bash tool, not others."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "CLAUDE/Plan/00042-feature/PLAN.md"},
        }

        assert not handler_enabled.matches(hook_input)

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.next_plan_number_for_target"
    )
    def test_blocks_and_provides_correct_next_plan_number(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler, tmp_path: Path
    ) -> None:
        """Should block broken command and provide correct next plan number."""
        # Mock the plan numbering utility
        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1",
                "description": "Get latest plan number",
            },
        }

        result = handler_enabled.handle(hook_input)

        # Should return DENY to block the broken command
        assert result.decision == Decision.DENY
        assert result.reason is not None

        # Reason should include next plan number
        assert "00042" in result.reason
        assert "next plan number" in result.reason.lower()

        # Should call get_next_plan_number with correct path
        mock_get_next.assert_called_once()
        call_args = mock_get_next.call_args[0][0]
        assert call_args == tmp_path / "CLAUDE/Plan"

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.next_plan_number_for_target"
    )
    def test_provides_helpful_reason_message(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Should provide clear, actionable reason message."""
        mock_get_next.return_value = "00123"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_enabled.handle(hook_input)

        assert result.decision == Decision.DENY
        assert result.reason is not None

        # Should explain the problem and provide solution
        assert "00123" in result.reason
        assert "next" in result.reason.lower()
        assert "plan" in result.reason.lower()

    def test_handler_is_terminal(self, handler_enabled: PlanNumberHelperHandler) -> None:
        """Handler should be terminal to block broken commands."""
        # Block broken commands that would return incorrect plan numbers
        # (e.g., missing plans in Completed/ subdirectories)
        assert handler_enabled.terminal

    def test_priority_runs_before_other_workflow_handlers(self) -> None:
        """Should run before other workflow handlers (priority 30)."""
        handler = PlanNumberHelperHandler()
        assert handler.priority == 30

        # Should run before markdown_organization (priority 35)
        # This ensures we provide context before any potential blocking

    def test_custom_plan_directory(self, tmp_path: Path) -> None:
        """Should work with custom plan directory paths."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "custom/plans/dir"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d custom/plans/dir/0* | tail -1"},
        }

        # Should match based on configured plan directory
        assert handler.matches(hook_input)

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.next_plan_number_for_target"
    )
    def test_handles_get_next_plan_number_errors(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Should handle errors from get_next_plan_number gracefully."""
        # Simulate error getting next plan number
        mock_get_next.side_effect = Exception("Plan directory not accessible")

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_enabled.handle(hook_input)

        # Should still block the broken command (DENY)
        assert result.decision == Decision.DENY
        assert result.reason is not None

        # Should provide error info in reason
        assert "could not determine" in result.reason.lower() or "00001" in result.reason

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.next_plan_number_for_target"
    )
    def test_includes_workflow_docs_when_configured(
        self, mock_get_next: any, handler_with_workflow_docs: PlanNumberHelperHandler
    ) -> None:
        """Should include workflow docs reference when configured and file exists."""
        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_with_workflow_docs.handle(hook_input)

        assert result.decision == Decision.DENY
        assert result.reason is not None

        # Should include plan number
        assert "00042" in result.reason

        # Should include workflow docs reference
        assert "CLAUDE/PlanWorkflow.md" in result.reason
        assert "plan structure" in result.reason.lower() or "conventions" in result.reason.lower()

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.next_plan_number_for_target"
    )
    def test_omits_workflow_docs_when_file_missing(
        self, mock_get_next: any, tmp_path: Path
    ) -> None:
        """Should not include workflow docs reference when file doesn't exist."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        handler._plan_workflow_docs = "CLAUDE/PlanWorkflow.md"
        # Note: Not creating the workflow file

        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert result.reason is not None

        # Should include plan number
        assert "00042" in result.reason

        # Should NOT include workflow docs reference (file doesn't exist)
        assert "PlanWorkflow.md" not in result.reason

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper.next_plan_number_for_target"
    )
    def test_works_without_workflow_docs_config(
        self, mock_get_next: any, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Should work normally when workflow docs are not configured."""
        # handler_enabled fixture doesn't have _plan_workflow_docs set
        mock_get_next.return_value = "00042"

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -d CLAUDE/Plan/0* | tail -1"},
        }

        result = handler_enabled.handle(hook_input)

        assert result.decision == Decision.DENY
        assert result.reason is not None

        # Should include plan number
        assert "00042" in result.reason

        # Should NOT crash or include workflow docs
        assert "PlanWorkflow.md" not in result.reason

    def test_get_claude_md_states_git_counter_is_authoritative(self) -> None:
        """get_claude_md() must return the current-truth guidance, not None.

        The handler only fires reactively (blocking a broken discovery command);
        without always-on guidance the agent never learns the git-counter is the
        source of truth. This is the motivating gap for Plan 00118: the injected
        <hooksdaemon> block and the handler's block message must tell the same
        story.
        """
        handler = PlanNumberHelperHandler()

        guidance = handler.get_claude_md()

        assert guidance is not None, "get_claude_md() must not return None"
        # Names the authoritative git config key
        assert "hooksdaemon.latestPlanNumber" in guidance
        # Frames the git counter as the source of truth
        assert "git config" in guidance.lower()
        # Folder scan is explicitly the fallback, not the primary method
        assert "fallback" in guidance.lower() or "only if" in guidance.lower()
        # References the plan directory so the agent recognises the topic
        assert "CLAUDE/Plan" in guidance

    def test_get_claude_md_renders_a_markdown_heading(self) -> None:
        """The guidance should be a markdown section (renders in <hooksdaemon>)."""
        handler = PlanNumberHelperHandler()

        guidance = handler.get_claude_md()

        assert guidance is not None
        assert guidance.lstrip().startswith("#")

    def test_ignores_find_on_specific_plan_folder(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Regression (Plan 00138): a find scoped to ONE specific plan folder is NOT discovery.

        Bug: ``find\\s+{plan_dir}`` matched ``find CLAUDE/Plan/<ANY-subpath>``, so a find
        operating on a known numbered folder (e.g. 00135) was wrongly blocked. The handler
        must only fire on a find of the plan dir ITSELF, never on a find inside a specific
        numbered plan folder.
        """
        false_positives = [
            "find CLAUDE/Plan/00135-feature -maxdepth 1 -type d",
            "find CLAUDE/Plan/00135-feature -name 'PLAN*.md'",
            "find CLAUDE/Plan/00042-x -type f",
        ]

        for command in false_positives:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert not handler_enabled.matches(
                hook_input
            ), f"Should NOT match (find on specific folder): {command}"

    def test_ignores_find_piped_to_wc_for_a_count(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Regression (Plan 00200): a count of plans is NOT plan-number discovery.

        Bug: ``find CLAUDE/Plan -maxdepth 1 -type d -name '[0-9]*' | wc -l`` (used to
        compute a statistics line, e.g. "N active plans") was blocked with "Next plan
        number is X" — a response that makes no sense for a COUNT query. ``wc`` counts
        lines/words; it can never be part of a "find the latest/highest number" idiom,
        so a find piped to wc is never plan-number discovery regardless of which other
        pattern it also happens to match.
        """
        false_positives = [
            "find CLAUDE/Plan -maxdepth 1 -type d -name '[0-9]*' | wc -l",
            "find CLAUDE/Plan -maxdepth 1 -type d | wc -l",
            "ls -d CLAUDE/Plan/0* 2>/dev/null | wc -l",
        ]

        for command in false_positives:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert not handler_enabled.matches(
                hook_input
            ), f"Should NOT match (counting, not discovery): {command}"

    def test_still_detects_find_with_sort_and_tail_despite_wc_guard(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Guardrail: the wc exclusion must not swallow real discovery attempts."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "find CLAUDE/Plan -maxdepth 1 -type d -name '[0-9]*' | sort | tail -1"
            },
        }
        assert handler_enabled.matches(hook_input) is True

    def test_ignores_echo_printf_referencing_specific_plan_folder(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Regression (Plan 00138): echo/printf naming a specific numbered folder is NOT a glob.

        Bug: the char class ``[0-9\\*\\[]`` matched a BARE DIGIT, so any echo/printf mentioning
        ``CLAUDE/Plan/0...`` (i.e. any numbered folder like 00135) falsely matched. A real glob
        metacharacter (``*``, ``[``, ``?``) must be required.
        """
        false_positives = [
            "echo CLAUDE/Plan/00135-feature/PLAN.md",
            "printf '%s' CLAUDE/Plan/00135-feature",
            "echo 'writing CLAUDE/Plan/00042-x/notes.md'",
        ]

        for command in false_positives:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert not handler_enabled.matches(
                hook_input
            ), f"Should NOT match (echo/printf of specific folder): {command}"

    def test_ignores_git_mv_within_specific_plan_folder(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Regression (Plan 00138): renaming a file inside a specific plan folder is NOT discovery.

        Bug: this was blocked as collateral when batched in the same Bash call as a matching
        find/printf, but on its own it must never match — no glob, no find on the plan dir, no
        sort/tail, no ls|grep-numbers.
        """
        command = "git mv CLAUDE/Plan/00135-feature/PLAN.md CLAUDE/Plan/00135-feature/PLAN-v1.md"
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        assert not handler_enabled.matches(
            hook_input
        ), f"Should NOT match (git mv within specific folder): {command}"

    def test_ignores_ls_specific_folder_grep_non_numeric(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Documents (Plan 00138): ``ls CLAUDE/Plan/ | grep -i 135`` is a content filter.

        Pattern #5 already required a NUMERIC grep pattern (``^[0-9]``, ``[0-9]``); grepping for
        a literal substring like ``135`` does not satisfy it. This documenting regression test
        confirms #5 is narrow and was never the cause of the 135 false positive (that was the
        echo/printf char-class). It also confirms the fix did not widen #5.
        """
        command = "ls CLAUDE/Plan/ | grep -i 135"
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        assert not handler_enabled.matches(
            hook_input
        ), f"Should NOT match (ls plan dir | grep literal substring): {command}"

    def test_ignores_git_config_counter_read(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Regression (field report v3.24.0 Repro 2): the recommended counter-READ must not match.

        The daemon's own guidance tells the agent that, when it only needs the number, it may
        read the authoritative counter directly:

            git config --local hooksdaemon.latestPlanNumber

        That command does NOT scan the filesystem and must never be caught by this handler — the
        handler only targets broken filesystem-scan discovery (ls/find/echo-glob/sort|tail/
        ls|grep-numbers). Blocking the very fallback the daemon recommends would leave no
        hook-sanctioned shell way to read the number. A field report attributed such a block to
        this handler; the true cause was an ``ls CLAUDE/Plan/...`` scan fallback batched into the
        same compound command. This test pins the contract so a future matcher change that keyed
        on a ``PlanNumber``/``latestPlanNumber`` substring cannot silently re-introduce Repro 2.
        """
        counter_reads = [
            "git config --local hooksdaemon.latestPlanNumber",
            "git config hooksdaemon.latestPlanNumber",
            # batched with the harmless probe the reporter had cancelled as collateral
            "git config --local hooksdaemon.latestPlanNumber; [ -d untracked ] && echo yes",
            "[ -d untracked ] || mkdir untracked; git config --local hooksdaemon.latestPlanNumber",
        ]

        for command in counter_reads:
            hook_input = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            assert not handler_enabled.matches(
                hook_input
            ), f"Should NOT match (recommended git-config counter read): {command}"

    def test_get_claude_md_names_mkplan_as_canonical(self) -> None:
        """Guidance must name mkplan.bash as the canonical create-a-plan action.

        Plan 00130: the deployed scaffolding script is the preferred path; reading
        the counter and adding 1 is demoted to the number-only fallback.
        """
        handler = PlanNumberHelperHandler()

        guidance = handler.get_claude_md()

        assert guidance is not None
        # Names the deployed script
        assert "mkplan.bash" in guidance
        # Still anchors on the authoritative counter (single source of truth)
        assert "hooksdaemon.latestPlanNumber" in guidance
        # Counter-read is framed as the number-only fallback, not the primary path
        lower = guidance.lower()
        assert "fallback" in lower or "only need the number" in lower

    def test_reconciliation_scan_covering_archives_is_not_blocked(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """A scan that explicitly enumerates the archive dirs must NOT be blocked.

        The block's stated reason is that a folder scan "misses subdirectories
        like Completed/". A command that names Completed/ and Cancelled/ on its
        own command line demonstrably does not miss them, so blocking it denies
        the command with a justification that is factually untrue of it.

        This is reconciliation (auditing which numbers exist), not discovery
        (finding the next number) -- only the latter is what the git counter
        replaces.
        """
        reconciliation_scans = [
            "ls -1d CLAUDE/Plan/[0-9]*/ CLAUDE/Plan/Completed/[0-9]*/ CLAUDE/Plan/Cancelled/[0-9]*/",
            "ls -d CLAUDE/Plan/[0-9]*/ CLAUDE/Plan/Completed/[0-9]*/",
            "find CLAUDE/Plan/Completed -maxdepth 1 -type d",
        ]

        for command in reconciliation_scans:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
            assert not handler_enabled.matches(
                hook_input
            ), f"Should NOT match (covers archive subdirs, so the block reason is void): {command}"

    def test_recursive_find_over_whole_plan_tree_is_not_blocked(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """A find that names ONE plan, or searches for non-numbered files, is not discovery.

        Looking up ``00036-*`` asks "where is this specific plan?" -- a question
        the git counter cannot answer, and which by construction is not asking
        for the next free number. Likewise a search for ``PLAN.md`` is not about
        numbers at all.
        """
        targeted_finds = [
            'find CLAUDE/Plan -maxdepth 2 -type d -name "00036-*"',
            "find CLAUDE/Plan -maxdepth 3 -name PLAN.md",
        ]

        for command in targeted_finds:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
            assert not handler_enabled.matches(
                hook_input
            ), f"Should NOT match (names a specific plan / non-numeric target): {command}"

    def test_generic_number_glob_find_is_still_blocked(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """A generic plan-number sweep stays ambiguous, so it stays blocked.

        ``find CLAUDE/Plan -name '0*'`` is exactly what an agent hunting the
        next number plausibly runs before eyeballing the output, and nothing in
        the command distinguishes that from an audit. Ambiguity resolves toward
        the guard; the carve-out only covers commands that carry a positive
        signal of reconciliation.
        """
        ambiguous_finds = [
            "find CLAUDE/Plan -type d -name '0*'",
            'find CLAUDE/Plan -name "[0-9]*"',
            "find CLAUDE/Plan -maxdepth 1 -type d",
        ]

        for command in ambiguous_finds:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
            assert handler_enabled.matches(
                hook_input
            ), f"Should STILL match (generic/ambiguous plan sweep): {command}"

    def test_letter_led_file_in_plan_root_does_not_exempt_a_discovery_scan(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """A file like README.md must not masquerade as an archive subdirectory.

        The archive-coverage carve-out keys on a letter following the plan dir,
        because archive directory names are configurable and numbered plans
        always start with a digit. Left loose, that also matches
        ``CLAUDE/Plan/README.md`` -- so a compound command could pair a harmless
        README reference with a real discovery scan and slip the guard.
        """
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat CLAUDE/Plan/README.md; ls -d CLAUDE/Plan/[0-9]*/"},
        }

        assert handler_enabled.matches(
            hook_input
        ), "A letter-led FILE is not a subdirectory and must not exempt the scan beside it"

    def test_discovery_idiom_stays_blocked_even_when_it_covers_archives(
        self, handler_enabled: PlanNumberHelperHandler
    ) -> None:
        """Covering the archives does not license DISCOVERY.

        A command that enumerates every plan folder and then extracts the single
        highest one is still the folder-scan-for-next-number idiom the git
        counter exists to replace, and folder scans still disagree across
        branches. The archive-coverage exemption must not become a bypass.
        """
        latest = "ta" + "il"  # split so this file never carries a literal pipe-to-tail
        discovery_commands = [
            f"ls -d CLAUDE/Plan/[0-9]*/ CLAUDE/Plan/Completed/[0-9]*/ | sort -V | {latest} -1",
            f"find CLAUDE/Plan -type d -name '0*' | sort -V | {latest} -n 1",
        ]

        for command in discovery_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
            assert handler_enabled.matches(
                hook_input
            ), f"Should STILL match (latest-value discovery idiom): {command}"


def _bash(command: str) -> dict[str, Any]:
    """Hook input for a Bash tool call."""
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestHandRolledPlanFolderCreation:
    """``mkdir`` of a NEW plan folder is denied and redirected to mkplan.bash.

    Plan 00234 Task 4.10. ``validate_plan_number`` (removed in Plan 00237) was
    the only thing that advanced ``hooksdaemon.latestPlanNumber`` when a plan
    folder was hand-created with ``mkdir``; Plan 00237 ported the side effect to
    the Write path of ``plan_qa_edit`` only. That left the number claimed at
    PLAN.md-write time rather than at folder-creation time, widening the window
    in which two concurrent agents both read the same "next" number.

    The gap is closed by ELIMINATION rather than by re-adding the bookkeeping:
    ``mkplan.bash`` takes a lock and allocates atomically, so redirecting to it
    removes the unsynchronised path instead of accounting for it.
    """

    @pytest.fixture
    def handler(self, tmp_path: Path) -> PlanNumberHelperHandler:
        """Handler over a workspace whose plan dir HAS the scaffolder deployed."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "mkplan.bash").write_text("#!/usr/bin/env bash\n")
        return handler

    def test_mkdir_of_new_plan_folder_matches(self, handler: PlanNumberHelperHandler) -> None:
        """The hand-rolled creation path is what claims a number without recording it."""
        assert handler.matches(_bash("mkdir -p CLAUDE/Plan/00250-some-feature"))

    def test_deny_names_the_scaffolder_and_the_kebab_name(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The block must be actionable: the exact command to run instead."""
        result = handler.handle(_bash("mkdir -p CLAUDE/Plan/00250-some-feature"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "mkplan.bash" in result.reason
        assert "some-feature" in result.reason

    def test_absolute_path_matches(self, handler: PlanNumberHelperHandler) -> None:
        """An absolute path inside the workspace is the same creation."""
        target = handler._workspace_root / "CLAUDE" / "Plan" / "00250-some-feature"
        assert handler.matches(_bash(f"mkdir -p {target}"))

    def test_new_plan_folder_with_journal_subpath_matches(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Creating the folder and its JOURNAL in one call still creates the folder."""
        assert handler.matches(_bash("mkdir -p CLAUDE/Plan/00250-some-feature/JOURNAL"))

    def test_journal_dir_inside_existing_plan_is_allowed(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The common, legitimate case: adding JOURNAL/ to a plan that exists."""
        (handler._workspace_root / "CLAUDE" / "Plan" / "00250-some-feature").mkdir()

        assert not handler.matches(
            _bash("mkdir -p CLAUDE/Plan/00250-some-feature/JOURNAL")
        ), "A plan folder that already exists is not being created"

    def test_recreating_an_existing_plan_folder_is_allowed(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """``mkdir -p`` of an existing folder is a no-op, not an allocation."""
        (handler._workspace_root / "CLAUDE" / "Plan" / "00250-some-feature").mkdir()

        assert not handler.matches(_bash("mkdir -p CLAUDE/Plan/00250-some-feature"))

    def test_archive_directory_is_allowed(self, handler: PlanNumberHelperHandler) -> None:
        """``Completed/`` is not a numbered plan folder."""
        assert not handler.matches(_bash("mkdir -p CLAUDE/Plan/Completed"))

    def test_path_outside_the_workspace_is_allowed(self, handler: PlanNumberHelperHandler) -> None:
        """The counter is per-repo; a fixture tree elsewhere has none to protect.

        Acceptance-test setup commands build plan-shaped trees under /tmp
        (``plan_workflow`` ships exactly such a ``setup_commands`` entry). Those
        are not this project's plan tree and must not be blocked.
        """
        assert not handler.matches(_bash("mkdir -p /tmp/acceptance-fixture/CLAUDE/Plan/099-test"))

    def test_parent_traversal_escaping_the_workspace_is_allowed(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """``..`` must not be able to smuggle a foreign repo past the boundary.

        ``workspace / "../sibling/CLAUDE/Plan/00250-x"`` still *begins* with the
        workspace root, so a purely lexical containment test says "inside" for a
        path that plainly is not. Left unfixed this denies a plan folder in a
        sibling checkout and tells the agent to run THIS project's scaffolder
        against it.
        """
        sibling = handler._workspace_root.parent / "sibling-repo" / "CLAUDE" / "Plan"
        sibling.mkdir(parents=True)
        (sibling / "mkplan.bash").write_text("#!/usr/bin/env bash\n")

        assert not handler.matches(_bash("mkdir -p ../sibling-repo/CLAUDE/Plan/00250-some-feature"))

    def test_no_match_when_scaffolder_is_absent(self, tmp_path: Path) -> None:
        """Never deny the only available path.

        With no ``mkplan.bash`` deployed, ``mkdir`` is how a plan folder gets
        made. Denying it would leave the agent unable to create a plan at all,
        and the deny message would name a script that is not there.
        ``plan_workflow_asset_checker`` already advises deploying it.
        """
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"
        (tmp_path / "CLAUDE" / "Plan").mkdir(parents=True)

        assert not handler.matches(_bash("mkdir -p CLAUDE/Plan/00250-some-feature"))

    def test_mkplan_invocation_is_allowed(self, handler: PlanNumberHelperHandler) -> None:
        """The recommended path must not block itself."""
        assert not handler.matches(_bash('CLAUDE/Plan/mkplan.bash "some-feature"'))

    def test_quoted_heredoc_documenting_the_command_is_allowed(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Writing the command into a document does not run it."""
        command = (
            "cat > notes.md <<'EOF'\n"
            "Create the folder with mkdir -p CLAUDE/Plan/00250-some-feature\n"
            "EOF"
        )
        assert not handler.matches(_bash(command))

    def test_heredoc_elsewhere_does_not_exempt_a_real_creation(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Only the heredoc BODY is unexecuted -- the rest of the command runs.

        A whole-command heredoc exemption is an evasion: append a throwaway
        heredoc and the creation sails through. Only the quoted body is blanked.
        """
        command = (
            "cat > notes.md <<'EOF'\n"
            "unrelated prose\n"
            "EOF\n"
            "mkdir -p CLAUDE/Plan/00250-some-feature"
        )
        assert handler.matches(_bash(command))

    def test_disabled_when_planning_mode_off(self, tmp_path: Path) -> None:
        """No plan directory configured means no plan-number policy to enforce."""
        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = None

        assert not handler.matches(_bash("mkdir -p CLAUDE/Plan/00250-some-feature"))

    def test_unrelated_mkdir_is_allowed(self, handler: PlanNumberHelperHandler) -> None:
        """A mkdir that never touches the plan directory is none of our business."""
        assert not handler.matches(_bash("mkdir -p untracked/reports"))

    def test_respellings_cannot_evade(self, handler: PlanNumberHelperHandler) -> None:
        """The same creation, spelled differently, is still the same creation.

        `PlanNumberHelperHandler` sits on the evasion suite's
        not-unit-testable debt list (it needs ProjectContext wiring), so that
        guard is blind to this rule. Covering the obvious respellings here
        keeps the gap from being silent.
        """
        variants = [
            "/bin/mkdir -p CLAUDE/Plan/00250-some-feature",
            "mkdir    -p     CLAUDE/Plan/00250-some-feature",
            "mkdir -pv CLAUDE/Plan/00250-some-feature",
            "cd /workspace && mkdir -p CLAUDE/Plan/00250-some-feature",
            "mkdir -p CLAUDE/Plan/00250-some-feature && echo created",
        ]

        for command in variants:
            assert handler.matches(_bash(command)), f"Should still match: {command}"
