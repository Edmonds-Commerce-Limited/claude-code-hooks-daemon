"""Tests for ValidatePlanNumberHandler.

The handler is git-anchored (Plan 00112): it resolves the nearest enclosing
git repo of the plan being created, and derives the expected number from that
repo's ``git config --local hooksdaemon.latestPlanNumber`` counter — trusting
the counter when present, bootstrapping from a filesystem scan when absent. The
fixtures here make the workspace a real git repo so the production path is
exercised; a separate non-git fixture covers the project-root fallback.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.validate_plan_number import (
    ValidatePlanNumberHandler,
)
from claude_code_hooks_daemon.handlers.utils.plan_numbering import (
    read_plan_counter,
    write_plan_counter,
)


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation (replaced per-test)."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")  # nosec B108 — test stub, never written
        yield mock


def _git_init(repo_root: Path) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", str(repo_root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return repo_root


class TestValidatePlanNumberHandler:
    """Test suite for ValidatePlanNumberHandler."""

    @pytest.fixture
    def temp_workspace(self, tmp_path: Path) -> Path:
        """Workspace that IS a git repo (production path uses the repo counter)."""
        return _git_init(tmp_path / "workspace")

    @pytest.fixture
    def handler(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> ValidatePlanNumberHandler:
        monkeypatch.setenv("PWD", str(temp_workspace))
        handler = ValidatePlanNumberHandler()
        handler.workspace_root = temp_workspace
        return handler

    @pytest.fixture
    def plan_root(self, temp_workspace: Path) -> Path:
        plan_root = temp_workspace / "CLAUDE" / "Plan"
        plan_root.mkdir(parents=True)
        return plan_root

    @staticmethod
    def _write_input(temp_workspace: Path, rel: str) -> dict[str, Any]:
        return {"tool_name": "Write", "tool_input": {"file_path": str(temp_workspace / rel)}}

    # ----- matches() -----

    def test_matches_write_operation_with_plan_folder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test-plan/README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_operation_with_5_digit_plan(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/00072-new-feature/PLAN.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_mkdir_with_plan_folder(self, handler: ValidatePlanNumberHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/001-test-plan"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_mkdir_with_5_digit_plan(self, handler: ValidatePlanNumberHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/00072-new-feature"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_mkdir_with_multiple_flags(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p -v CLAUDE/Plan/042-feature"},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_mkdir_completed_folder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/Completed/023-old-plan"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_mkdir_any_organizational_subfolder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/Archive/023-old-plan"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_bash_mkdir_outside_plan(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p src/handlers"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_documentation_command_file(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/x/.claude/commands/CLAUDE/Plan/001-x/doc.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_heredoc_command(self, handler: ValidatePlanNumberHandler) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat > example.md << 'EOF'\nmkdir CLAUDE/Plan/001-test\nEOF"},
        }
        assert handler.matches(hook_input) is False

    def test_is_heredoc_command_negative(self, handler: ValidatePlanNumberHandler) -> None:
        assert handler._is_heredoc_command("mkdir -p CLAUDE/Plan/001-test") is False

    # ----- handle(): bootstrap path (counter absent → scan + seed) -----

    def test_handle_write_correct_plan_number_first_plan(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        result = handler.handle(
            self._write_input(temp_workspace, "CLAUDE/Plan/001-first/README.md")
        )
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_correct_plan_number_sequential(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "001-existing").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/002-new/README.md"))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_incorrect_plan_number_too_high(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "005-existing").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/010-new/README.md"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]
        # Plan 00138: the actual folder name is echoed back verbatim (zero-padding preserved).
        assert "You are creating: CLAUDE/Plan/010-new/" in result.context[0]
        assert "Expected next number: 6" in result.context[0]

    def test_handle_write_incorrect_plan_number_too_low(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "010-existing").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/005-new/README.md"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]
        assert "Expected next number: 11" in result.context[0]

    def test_handle_write_with_completed_plans(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "003-active").mkdir()
        completed = plan_root / "Completed"
        completed.mkdir()
        (completed / "020-completed").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/021-new/README.md"))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_incorrect_with_completed_plans(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "005-active").mkdir()
        completed = plan_root / "Completed"
        completed.mkdir()
        (completed / "030-completed").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/006-new/README.md"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "Expected next number: 31" in result.context[0]

    def test_handle_write_5_digit_correct_sequential(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "00071-existing").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/00072-new/PLAN.md"))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_5_digit_wrong_number(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "00071-existing").mkdir()
        result = handler.handle(
            self._write_input(temp_workspace, "CLAUDE/Plan/00099-wrong/PLAN.md")
        )
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]

    def test_handle_bash_mkdir_5_digit_correct(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        (plan_root / "00071-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/00072-new-plan"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_bash_correct_plan_number(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        (plan_root / "012-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/013-new-plan"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_bash_incorrect_plan_number(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        (plan_root / "007-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/020-new-plan"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "Expected next number: 8" in result.context[0]

    def test_handle_bash_mkdir_with_flags(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        (plan_root / "015-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p -v -m 755 CLAUDE/Plan/016-new-plan"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    # ----- handle(): counter is TRUSTED when present -----

    def test_handle_trusts_counter_accepts_counter_driven_number(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """Counter=110 but on-disk only goes to 003: 00111 (counter-driven) is
        accepted, proving the filesystem scan is bypassed when a counter exists.
        """
        (plan_root / "00001-a").mkdir()
        (plan_root / "00003-c").mkdir()
        write_plan_counter(temp_workspace, 110)

        ok = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/00111-new/PLAN.md"))
        assert ok.decision == Decision.ALLOW
        assert not ok.context

    def test_handle_trusts_counter_rejects_scan_driven_number(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """With counter=110, a scan-driven 00004 is rejected — expected is the
        counter-driven 111, not 004.
        """
        (plan_root / "00001-a").mkdir()
        (plan_root / "00003-c").mkdir()
        write_plan_counter(temp_workspace, 110)

        wrong = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/00004-scan/PLAN.md"))
        assert wrong.context
        assert "Expected next number: 111" in wrong.context[0]

    def test_handle_records_allocation_advances_counter(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """A valid creation advances the per-repo high-water mark so the NEXT
        plan reads counter + 1.
        """
        write_plan_counter(temp_workspace, 110)
        handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/00111-new/PLAN.md"))
        assert read_plan_counter(temp_workspace) == 111

    def test_handle_wrong_number_does_not_advance_counter(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """A rejected (out-of-range) number must NOT poison the counter — next
        stays counter + 1 so a typo doesn't blow a huge gap.
        """
        write_plan_counter(temp_workspace, 110)
        handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/00999-typo/PLAN.md"))
        assert read_plan_counter(temp_workspace) == 110

    def test_handle_bootstrap_seeds_counter(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """First validation against a counter-less repo seeds the high-water
        mark from the filesystem scan.
        """
        (plan_root / "00007-existing").mkdir()
        handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/00008-new/PLAN.md"))
        assert read_plan_counter(temp_workspace) == 8  # 7 seeded, then 8 recorded

    # ----- vendor / nested repo -----

    def test_handle_nested_repo_uses_own_counter(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path
    ) -> None:
        """A plan created inside a vendor lib with its OWN git repo validates
        against that repo's counter, not the outer workspace's.
        """
        write_plan_counter(temp_workspace, 110)  # outer
        inner = _git_init(temp_workspace / "vendor" / "acme-lib")
        (inner / "CLAUDE" / "Plan").mkdir(parents=True)
        write_plan_counter(inner, 6)  # inner

        # 00007 is correct for the INNER repo (6 + 1), independent of outer's 110.
        ok = handler.handle(
            self._write_input(temp_workspace, "vendor/acme-lib/CLAUDE/Plan/00007-x/PLAN.md")
        )
        assert ok.decision == Decision.ALLOW
        assert not ok.context

    def test_handle_nested_repo_rejects_outer_number(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path
    ) -> None:
        """Inside the vendor repo, the outer-correct number (111) is wrong — the
        expected number comes from the inner repo's counter (6 + 1 = 7).
        """
        write_plan_counter(temp_workspace, 110)  # outer
        inner = _git_init(temp_workspace / "vendor" / "acme-lib")
        (inner / "CLAUDE" / "Plan").mkdir(parents=True)
        write_plan_counter(inner, 6)  # inner

        wrong = handler.handle(
            self._write_input(temp_workspace, "vendor/acme-lib/CLAUDE/Plan/00111-x/PLAN.md")
        )
        assert wrong.context
        assert "Expected next number: 7" in wrong.context[0]

    # ----- non-git fallback -----

    def test_handle_non_git_falls_back_to_project_root_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the workspace is not a git repo, validation falls back to a
        filesystem scan against the project root (legacy behaviour).
        """
        plain = tmp_path / "plain"  # NOT a git repo
        plan_root = plain / "CLAUDE" / "Plan"
        plan_root.mkdir(parents=True)
        (plan_root / "00004-a").mkdir()
        monkeypatch.setenv("PWD", str(plain))
        handler = ValidatePlanNumberHandler()
        handler.workspace_root = plain

        ok = handler.handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(plan_root / "00005-new/PLAN.md")},
            }
        )
        assert ok.decision == Decision.ALLOW
        assert not ok.context

        wrong = handler.handle(
            {"tool_name": "Write", "tool_input": {"file_path": str(plan_root / "00009-x/PLAN.md")}}
        )
        assert wrong.context
        assert "Expected next number: 5" in wrong.context[0]

    # ----- edge cases -----

    def test_handle_no_plan_number_extracted(self, handler: ValidatePlanNumberHandler) -> None:
        result = handler.handle(
            {"tool_name": "Write", "tool_input": {"file_path": "/workspace/other/file.txt"}}
        )
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_empty_file_path(self, handler: ValidatePlanNumberHandler) -> None:
        result = handler.handle({"tool_name": "Write", "tool_input": {"file_path": ""}})
        assert result.decision == Decision.ALLOW

    def test_handle_missing_tool_input(self, handler: ValidatePlanNumberHandler) -> None:
        result = handler.handle({"tool_name": "Write"})
        assert result.decision == Decision.ALLOW

    def test_error_message_includes_corrected_mkdir(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "042-existing").mkdir()
        result = handler.handle(
            self._write_input(temp_workspace, "CLAUDE/Plan/050-wrong/README.md")
        )
        assert result.context
        # Plan 00138: corrected example uses the zero-padded plan-number convention.
        assert "mkdir -p CLAUDE/Plan/00043-wrong" in result.context[0]
        assert "hooksdaemon.latestPlanNumber" in result.context[0]

    # ----- TOCTOU: mkdir created the dir before Write fires (bootstrap path) -----

    def test_handle_write_allows_when_dir_already_created_by_mkdir(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "023-old-plan").mkdir()
        (plan_root / "024-dto-rules").mkdir()  # mkdir already ran
        result = handler.handle(
            self._write_input(temp_workspace, "CLAUDE/Plan/024-dto-rules/PLAN.md")
        )
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_allows_when_dir_is_highest_from_completed(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        completed = plan_root / "Completed"
        completed.mkdir()
        (completed / "023-completed-plan").mkdir()
        (plan_root / "024-new-plan").mkdir()  # mkdir already ran
        result = handler.handle(
            self._write_input(temp_workspace, "CLAUDE/Plan/024-new-plan/PLAN.md")
        )
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_still_rejects_genuinely_wrong_number(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "023-old").mkdir()
        (plan_root / "024-current").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/030-wrong/PLAN.md"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]

    def test_handle_write_still_rejects_low_number_with_existing_dir(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "024-current").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/020-old/PLAN.md"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]

    # ----- Plan 00138: do not warn when editing an EXISTING plan folder -----

    def test_does_not_match_write_to_existing_plan_folder(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """Regression (Plan 00138): editing a file in an EXISTING plan folder is not creation.

        Field bug: rewriting ``CLAUDE/Plan/00135-event-driven-send-keys-injection/PLAN.md``
        (an existing plan) triggered "PLAN NUMBER INCORRECT". A Write whose target plan folder
        already exists on disk is an edit/rewrite, never a new-plan creation — so the handler
        must NOT fire.
        """
        (plan_root / "00135-event-driven-send-keys-injection").mkdir()
        hook_input = self._write_input(
            temp_workspace,
            "CLAUDE/Plan/00135-event-driven-send-keys-injection/PLAN.md",
        )
        assert handler.matches(hook_input) is False

    def test_matches_write_to_new_plan_folder(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """True positive preserved: a genuinely NEW plan folder (not yet on disk) still matches."""
        hook_input = self._write_input(temp_workspace, "CLAUDE/Plan/00200-brand-new/PLAN.md")
        assert handler.matches(hook_input) is True

    def test_does_not_match_mkdir_to_existing_plan_folder(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """Regression (Plan 00138): mkdir targeting an already-existing plan folder is a no-op
        re-create, not a new plan — the handler must not fire."""
        (plan_root / "00135-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/00135-existing"},
        }
        assert handler.matches(hook_input) is False

    # ----- Plan 00138: zero-padding must be preserved in the message -----

    def test_warning_preserves_zero_padded_folder_name(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """Regression (Plan 00138): a mis-numbered NEW plan with a zero-padded name must be
        echoed back WITH its leading zeros, not stripped to a bare int.

        Field bug: the message rendered ``00135-...`` as ``135-...`` because ``int()`` dropped
        the zero-padding. The displayed actual-folder name must match what the user typed.
        """
        (plan_root / "00071-existing").mkdir()
        result = handler.handle(
            self._write_input(temp_workspace, "CLAUDE/Plan/00099-wrong/PLAN.md")
        )
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]
        # Preserves the zero-padded folder name the user actually typed.
        assert "00099-wrong" in result.context[0]
        # Must NOT show the zero-stripped form.
        assert "/99-wrong" not in result.context[0]

    def test_warning_expected_number_is_zero_padded(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        """Regression (Plan 00138): the expected next number is shown zero-padded to the plan
        convention (5 digits), matching the folder naming users must adopt."""
        (plan_root / "00071-existing").mkdir()
        result = handler.handle(
            self._write_input(temp_workspace, "CLAUDE/Plan/00099-wrong/PLAN.md")
        )
        assert result.context
        # Expected next number 72 → displayed as 00072 (zero-padded), in the corrected example.
        assert "00072-wrong" in result.context[0]

    # ----- config-aware plan directory -----

    def test_handler_receives_plan_workflow_via_planning_tag(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        assert handler.shares_options_with is None
        assert "planning" in handler.tags

    def test_handler_has_track_plans_in_project_attribute(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        assert hasattr(handler, "_track_plans_in_project")
        assert handler._track_plans_in_project is None

    def test_error_message_uses_configured_plan_dir(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path
    ) -> None:
        custom = temp_workspace / "CLAUDE" / "Plans"
        custom.mkdir(parents=True)
        (custom / "005-existing").mkdir()
        handler._track_plans_in_project = "CLAUDE/Plans"

        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plans/020-wrong/PLAN.md"))
        assert result.context
        assert "CLAUDE/Plans/" in result.context[0]
        assert "CLAUDE/Plan/" not in result.context[0]

    # ----- date-directory regression (bootstrap scan must ignore dates) -----

    def test_handle_not_poisoned_by_date_directories(
        self, handler: ValidatePlanNumberHandler, temp_workspace: Path, plan_root: Path
    ) -> None:
        (plan_root / "032-existing").mkdir()
        legacy = plan_root / "legacy"
        legacy.mkdir()
        (legacy / "2026-01-12").mkdir()
        result = handler.handle(self._write_input(temp_workspace, "CLAUDE/Plan/033-new/PLAN.md"))
        assert result.decision == Decision.ALLOW
        assert not result.context  # 033 correct; date dir not counted as 2026

    # ----- handler metadata -----

    def test_handler_has_correct_name(self, handler: ValidatePlanNumberHandler) -> None:
        assert handler.name == "validate-plan-number"

    def test_handler_has_correct_priority(self, handler: ValidatePlanNumberHandler) -> None:
        assert handler.priority == 30

    def test_handler_is_non_terminal(self, handler: ValidatePlanNumberHandler) -> None:
        assert handler.terminal is False

    def test_handler_has_correct_tags(self, handler: ValidatePlanNumberHandler) -> None:
        assert "workflow" in handler.tags
        assert "planning" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags

    def test_get_claude_md_returns_none(self, handler: ValidatePlanNumberHandler) -> None:
        assert handler.get_claude_md() is None

    def test_get_acceptance_tests_present(self, handler: ValidatePlanNumberHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1
        assert tests[0].expected_decision == Decision.ALLOW
