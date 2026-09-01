"""Tests for ValidateEslintOnWriteHandler."""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.workspace import ProjectRegistry
from claude_code_hooks_daemon.utils.npm import (
    has_llm_commands_in_package_json as real_has_llm_commands,
)


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation tests."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


@pytest.fixture(autouse=True)
def mock_llm_commands_detection():
    """Mock llm commands detection - default to True (enforcement mode)."""
    with patch(
        "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
        return_value=True,
    ) as mock:
        yield mock


from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write import (
    ValidateEslintOnWriteHandler,
)


class TestResidentGuidance:
    """This handler DENIES, and no other resident section covers its languages.

    Plan 00203 recorded it as exempt on the grounds that ``lint_on_edit``'s
    section already said "writes are linted and a failure denies". That reason
    was wrong in two ways, both found by asking mechanically which EXEMPT
    handlers contain a DENY path:

    * ``lint_on_edit``'s section lists nine languages and TypeScript is not
      among them, so a ``.ts`` author reads it and concludes they are unchecked.
    * the two handlers degrade in OPPOSITE directions. ``lint_on_edit`` ALLOWs
      when the linter is missing or times out; this one DENIES on a timeout and
      on any failure to run ESLint at all. The sibling section therefore does
      not merely omit TypeScript — it states a graceful-degradation guarantee
      that is false here.
    """

    @staticmethod
    def _guidance(tmp_path: Path) -> str:
        return ValidateEslintOnWriteHandler(workspace_root=tmp_path).get_claude_md() or ""

    def test_provides_guidance(self, tmp_path: Path) -> None:
        assert ValidateEslintOnWriteHandler(workspace_root=tmp_path).get_claude_md() is not None

    def test_names_the_languages_lint_on_edit_does_not_cover(self, tmp_path: Path) -> None:
        guidance = self._guidance(tmp_path)

        assert ".ts" in guidance
        assert ".tsx" in guidance

    def test_states_that_it_denies(self, tmp_path: Path) -> None:
        assert "DENIES" in self._guidance(tmp_path)

    def test_states_that_the_write_already_landed(self, tmp_path: Path) -> None:
        guidance = self._guidance(tmp_path).lower()

        assert "already" in guidance
        assert "disk" in guidance or "written" in guidance

    def test_warns_that_it_denies_where_lint_on_edit_would_allow(self, tmp_path: Path) -> None:
        """The differentiator. Without it the sibling section actively misleads."""
        guidance = self._guidance(tmp_path).lower()

        assert "timeout" in guidance or "times out" in guidance

    def test_states_the_package_json_gate_that_enables_enforcement(self, tmp_path: Path) -> None:
        """Enforcement is conditional; silence is not proof of a clean file."""
        guidance = self._guidance(tmp_path)

        assert "llm:" in guidance
        assert "package.json" in guidance


class TestValidateEslintOnWriteHandler:
    """Tests for ValidateEslintOnWriteHandler."""

    @pytest.fixture
    def handler(self, tmp_path: Path) -> ValidateEslintOnWriteHandler:
        """Create handler with temporary workspace."""
        return ValidateEslintOnWriteHandler(workspace_root=tmp_path)

    def test_initialization(self, tmp_path: Path) -> None:
        """Handler should initialize with correct attributes."""
        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)

        assert handler.name == "validate-eslint-on-write"
        assert handler.priority == 10
        assert "validation" in handler.tags
        assert "typescript" in handler.tags
        assert handler.workspace_root == tmp_path

    def test_initialization_auto_detect_workspace(self) -> None:
        """Handler should auto-detect workspace if not provided."""
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as mock_get_workspace:
            mock_get_workspace.return_value = Path("/mock/workspace")
            handler = ValidateEslintOnWriteHandler()

            assert handler.workspace_root == Path("/mock/workspace")
            mock_get_workspace.assert_called_once()

    def test_matches_typescript_file(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should match TypeScript files being written."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is True

    def test_matches_tsx_file(self, handler: ValidateEslintOnWriteHandler, tmp_path: Path) -> None:
        """Should match TSX files being written."""
        test_file = tmp_path / "test.tsx"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is True

    def test_matches_edit_tool(self, handler: ValidateEslintOnWriteHandler, tmp_path: Path) -> None:
        """Should match Edit tool operations on TypeScript files."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is True

    def test_does_not_match_non_write_tools(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should not match tools other than Write/Edit."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "test"},
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_non_typescript_files(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should not match non-TypeScript files."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_node_modules(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should skip files in node_modules."""
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        test_file = node_modules / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is False

    @pytest.mark.parametrize(
        "skip_path",
        [
            "dist",
            ".build",
            "coverage",
            "test-results",
            # Plan 00288 Task 3.2: newly-accepted core deltas.
            "vendor",
            "build",
            "target",
            ".venv",
            "venv",
            ".next",
            "third_party",
        ],
    )
    def test_does_not_match_build_artifacts(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path, skip_path: str
    ) -> None:
        """Should skip files in build artifact directories."""
        build_dir = tmp_path / skip_path
        build_dir.mkdir()
        test_file = build_dir / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is False

    def test_matches_first_party_dir_named_builder(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Plan 00288 Task 3.2 precondition: the old bare-substring matcher
        would skip ``src/builder/x.ts`` because it contains "build". The
        matcher must be slash-bounded so this first-party path is still
        checked."""
        src_dir = tmp_path / "src" / "builder"
        src_dir.mkdir(parents=True)
        test_file = src_dir / "x.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is True

    def test_matches_first_party_file_named_venvtool(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Plan 00288 Task 3.2 precondition: the old bare-substring matcher
        would skip ``src/venvtool.ts`` because it contains "venv". The
        matcher must be slash-bounded so this first-party file is still
        checked."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        test_file = src_dir / "venvtool.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is True

    def test_does_not_match_nonexistent_file(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should not match files that don't exist."""
        test_file = tmp_path / "nonexistent.ts"

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_file_path(self, handler: ValidateEslintOnWriteHandler) -> None:
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {},
        }

        assert handler.matches(hook_input) is False

    @patch("subprocess.run")
    def test_handle_eslint_success(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should allow when ESLint passes."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_handle_eslint_failure(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should deny when ESLint fails."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="ESLint error output",
            stderr="",
        )

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "ESLint validation FAILED" in result.reason
        assert "ESLint error output" in result.reason

    @patch("subprocess.run")
    def test_handle_eslint_with_stderr(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should include stderr in error message."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="stdout output",
            stderr="stderr output",
        )

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "stderr output" in result.reason

    @patch("subprocess.run")
    def test_handle_worktree_file(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should detect and handle worktree files."""
        # Create worktree path
        worktree_dir = tmp_path / "untracked" / "worktrees" / "test"
        worktree_dir.mkdir(parents=True)
        test_file = worktree_dir / "test.ts"
        test_file.write_text("const x = 1;")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_handle_timeout(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should deny when ESLint times out."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="eslint", timeout=Timeout.ESLINT_CHECK)

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "timed out" in result.reason

    @patch("subprocess.run")
    def test_handle_exception(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should deny when ESLint command fails with exception."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        mock_run.side_effect = RuntimeError("ESLint not found")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "Failed to run ESLint" in result.reason

    def test_handle_missing_file_path(self, handler: ValidateEslintOnWriteHandler) -> None:
        """Should allow when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert "No file path found" in result.reason

    @patch("subprocess.run")
    def test_eslint_command_structure(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """Should call ESLint with correct command structure."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        handler.handle(hook_input)

        # Verify command structure
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "tsx"
        assert call_args[0][0][1] == "scripts/eslint-wrapper.ts"
        assert call_args[0][0][2] == str(test_file)
        assert "--max-warnings" in call_args[0][0]
        assert "0" in call_args[0][0]
        assert "--human" in call_args[0][0]
        assert call_args[1]["cwd"] == str(tmp_path)
        assert call_args[1]["timeout"] == 30

    # Tests for has_llm_commands caching

    def test_has_llm_commands_cached_at_init(self, tmp_path: Path) -> None:
        """has_llm_commands is cached at __init__ time."""
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=True,
        ) as mock_detect:
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
            assert handler.has_llm_commands is True
            mock_detect.assert_called_once()

    def test_has_llm_commands_false_when_no_llm_scripts(self, tmp_path: Path) -> None:
        """has_llm_commands is False when no llm: scripts exist."""
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
            assert handler.has_llm_commands is False

    # Tests for advisory mode (no llm: commands)

    @patch("subprocess.run")
    def test_advisory_mode_skips_eslint_validation(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Advisory mode skips ESLint validation and returns ALLOW with advisory."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        # The patch spans handle() too: since Plan 00296 the mode is decided
        # per event against the authored file's own workspace.
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
            result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        # Regression test: an ALLOW decision's `reason` is silently dropped by
        # HookResult.to_json() for PostToolUse events - the advisory MUST be
        # in `context` to actually reach the user.
        assert "ADVISORY" in "\n".join(result.context)
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_advisory_mode_message_survives_posttooluse_formatting(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """The advisory message must actually reach the user via to_json()."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
            result = handler.handle(hook_input)

        response = result.to_json("PostToolUse")
        additional_context = response["hookSpecificOutput"]["additionalContext"]
        assert "ADVISORY" in additional_context
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_advisory_mode_suggests_llm_lint(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Advisory mode suggests creating llm:lint script."""
        test_file = tmp_path / "component.tsx"
        test_file.write_text("export const App = () => <div />;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
            result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        advisory = "\n".join(result.context)
        assert "llm:lint" in advisory
        assert "package.json" in advisory
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_advisory_mode_includes_guide_path(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Advisory mode includes path to LLM command wrapper guide."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
            result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        advisory = "\n".join(result.context)
        assert "Full guide:" in advisory
        assert "llm-command-wrappers.md" in advisory
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_enforcement_mode_runs_eslint(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Enforcement mode (llm commands exist) runs ESLint as before."""
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=True,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        mock_run.assert_called_once()


class TestNoStdoutPrinting:
    """Regression: the daemon's protocol is JSON-on-stdout, so a handler must
    never print() progress messages directly to stdout - it must log them
    instead (and/or surface them via the returned HookResult context).
    """

    @pytest.fixture
    def handler(self, tmp_path: Path) -> ValidateEslintOnWriteHandler:
        """Create handler with temporary workspace."""
        return ValidateEslintOnWriteHandler(workspace_root=tmp_path)

    @patch("subprocess.run")
    def test_success_path_writes_nothing_to_stdout(
        self,
        mock_run: MagicMock,
        handler: ValidateEslintOnWriteHandler,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A passing ESLint run must not print anything to stdout."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {"tool_name": "Write", "tool_input": {"file_path": str(test_file)}}
        handler.handle(hook_input)

        captured = capsys.readouterr()
        assert captured.out == ""

    @patch("subprocess.run")
    def test_worktree_detection_writes_nothing_to_stdout(
        self,
        mock_run: MagicMock,
        handler: ValidateEslintOnWriteHandler,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The worktree-detection notice must not print anything to stdout."""
        worktree_dir = tmp_path / "untracked" / "worktrees" / "test"
        worktree_dir.mkdir(parents=True)
        test_file = worktree_dir / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {"tool_name": "Write", "tool_input": {"file_path": str(test_file)}}
        handler.handle(hook_input)

        captured = capsys.readouterr()
        assert captured.out == ""

    @patch("subprocess.run")
    def test_success_path_logs_instead_of_printing(
        self,
        mock_run: MagicMock,
        handler: ValidateEslintOnWriteHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Progress messages go through the standard logging module."""
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {"tool_name": "Write", "tool_input": {"file_path": str(test_file)}}
        with caplog.at_level(logging.INFO):
            handler.handle(hook_input)

        messages = "\n".join(record.message for record in caplog.records)
        assert "Running ESLint validation" in messages
        assert "ESLint validation passed" in messages


class TestNodeModulesBinPath:
    """Tests for node_modules/.bin PATH injection (Bug 1 fix).

    **These test functions are deliberately NOT named after `node_modules`.**
    pytest derives `tmp_path` from the test function name, and `SKIP_PATHS` is a
    naive SUBSTRING test over the whole file path -- so a test called
    `test_node_modules_...` writes its fixture into a directory whose name
    contains `node_modules`, and the handler correctly declines to lint it.

    That went unnoticed while `handle()` skipped the scope filter `matches()`
    applies (Plan 00260 Task 3.5 made the two consistent, since a Bash command
    can author several files and each must be filtered on its own). The tests
    then failed for a real reason: they were asking the handler to lint a path
    it is configured to ignore.
    """

    @pytest.fixture
    def handler(self, tmp_path: Path) -> ValidateEslintOnWriteHandler:
        return ValidateEslintOnWriteHandler(workspace_root=tmp_path)

    @patch("subprocess.run")
    def test_local_bin_prepended_to_path_when_exists(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """subprocess.run env must include node_modules/.bin when directory exists."""
        bin_dir = tmp_path / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {"tool_name": "Write", "tool_input": {"file_path": str(test_file)}}
        handler.handle(hook_input)

        call_kwargs = mock_run.call_args[1]
        assert "env" in call_kwargs
        assert str(bin_dir) in call_kwargs["env"]["PATH"]

    @patch("subprocess.run")
    def test_local_bin_first_in_path(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """node_modules/.bin must appear BEFORE other PATH entries."""
        bin_dir = tmp_path / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {"tool_name": "Write", "tool_input": {"file_path": str(test_file)}}
        handler.handle(hook_input)

        env_path = mock_run.call_args[1]["env"]["PATH"]
        entries = env_path.split(":")
        assert entries[0] == str(bin_dir)

    @patch("subprocess.run")
    def test_env_passed_even_without_node_modules(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        """env kwarg must be passed even when node_modules/.bin does not exist."""
        # tmp_path has no node_modules
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        hook_input = {"tool_name": "Write", "tool_input": {"file_path": str(test_file)}}
        handler.handle(hook_input)

        call_kwargs = mock_run.call_args[1]
        assert "env" in call_kwargs


class TestValidateEslintOnWriteGetRules:
    """get_rules() (Plan 00116): 3 rules for the 3 distinct failure shapes."""

    def test_get_rules_returns_three_rules(self, tmp_path: Path) -> None:
        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert len(handler.get_rules()) == 3

    def test_get_rules_ids_are_constants(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        rule_ids = {rule.rule_id for rule in handler.get_rules()}
        assert rule_ids == {
            RuleID.ESLINT_ERRORS,
            RuleID.ESLINT_TIMEOUT,
            RuleID.ESLINT_RUN_FAILURE,
        }

    def test_get_rules_every_verbose_is_non_empty(self, tmp_path: Path) -> None:
        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        for rule in handler.get_rules():
            assert rule.verbose


class TestValidateEslintOnWriteEnforcementStatus:
    """get_enforcement_status() (Plan 00296 T4.1): degraded-mode visibility."""

    def test_nominal_when_llm_commands_present(
        self, tmp_path: Path, mock_llm_commands_detection: MagicMock
    ) -> None:
        mock_llm_commands_detection.return_value = True
        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.get_enforcement_status(tmp_path) == []

    def test_advisory_when_no_llm_commands(
        self, tmp_path: Path, mock_llm_commands_detection: MagicMock
    ) -> None:
        mock_llm_commands_detection.return_value = False
        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        statuses = handler.get_enforcement_status(tmp_path)
        assert len(statuses) == 1
        assert "validate_eslint_on_write" in statuses[0]
        assert "ESLint validation is skipped" in statuses[0]

    def test_pinned_workspace_root_wins_over_passed_root(
        self, tmp_path: Path, mock_llm_commands_detection: MagicMock
    ) -> None:
        """A pinned root (the test seam) is the one actually probed."""
        pinned = tmp_path / "pinned"
        pinned.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        mock_llm_commands_detection.return_value = False
        handler = ValidateEslintOnWriteHandler(workspace_root=pinned)
        handler.get_enforcement_status(other)
        mock_llm_commands_detection.assert_called_with(pinned)


class TestValidateEslintOnWriteDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116).

    The dynamic diagnostic (ESLint output, timeout seconds, exception text)
    is a POST-hoc failure report and must stay fully present in BOTH verbose
    and terse forms -- only the surrounding teaching prose goes terse.
    """

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    @pytest.fixture
    def handler(self, tmp_path: Path) -> ValidateEslintOnWriteHandler:
        return ValidateEslintOnWriteHandler(workspace_root=tmp_path)

    @staticmethod
    def _hook_input(test_file: Path, transcript_path: str | None) -> dict:
        hook_input: dict = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    @patch("subprocess.run")
    def test_deny_reason_starts_with_rule_id_prefix(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=1, stdout="ESLint error output", stderr="")
        result = handler.handle(self._hook_input(test_file, "/tmp/transcript-esl-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.ESLINT_ERRORS}]")

    @patch("subprocess.run")
    def test_first_fire_is_verbose(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=1, stdout="ESLint error output", stderr="")
        result = handler.handle(self._hook_input(test_file, "/tmp/transcript-esl-b.jsonl"))
        assert "ALREADY landed on disk" in result.reason
        assert "ESLint error output" in result.reason

    @patch("subprocess.run")
    def test_second_fire_same_agent_is_terse_but_keeps_diagnostic(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=1, stdout="ESLint error output", stderr="")
        transcript = "/tmp/transcript-esl-c.jsonl"
        handler.handle(self._hook_input(test_file, transcript))
        second = handler.handle(self._hook_input(test_file, transcript))
        assert "ALREADY landed on disk" not in second.reason
        assert "ESLint error output" in second.reason

    @patch("subprocess.run")
    def test_missing_transcript_path_always_verbose(
        self, mock_run: MagicMock, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        mock_run.return_value = MagicMock(returncode=1, stdout="ESLint error output", stderr="")
        first = handler.handle(self._hook_input(test_file, None))
        second = handler.handle(self._hook_input(test_file, None))
        assert "ALREADY landed on disk" in first.reason
        assert "ALREADY landed on disk" in second.reason

    def test_timeout_uses_the_timeout_rule(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        import subprocess as subprocess_module

        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        with patch(
            "subprocess.run",
            side_effect=subprocess_module.TimeoutExpired(cmd="tsx", timeout=Timeout.ESLINT_CHECK),
        ):
            result = handler.handle(self._hook_input(test_file, None))
        assert result.reason.startswith(f"BLOCKED [{RuleID.ESLINT_TIMEOUT}]")

    def test_run_failure_uses_the_run_failure_rule(
        self, handler: ValidateEslintOnWriteHandler, tmp_path: Path
    ) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            result = handler.handle(self._hook_input(test_file, None))
        assert result.reason.startswith(f"BLOCKED [{RuleID.ESLINT_RUN_FAILURE}]")


class TestPerFileWorkspace:
    """ESLint runs in the EDITED FILE's own workspace (Plan 00296 Task 2.3).

    `workspace_root` is a single scalar, so it cannot express "TS files under
    web/, and a second TS workspace elsewhere" -- and the mode probe ignored
    it entirely and read the repo root.
    """

    @staticmethod
    def _monorepo(tmp_path: Path) -> Path:
        """Two TS workspaces, NO root manifest. Only one defines llm: scripts."""
        web = tmp_path / "apps" / "web"
        (web / "src").mkdir(parents=True)
        (web / "package.json").write_text(
            json.dumps({"scripts": {"llm:lint": "eslint ."}}), encoding="utf-8"
        )
        api = tmp_path / "apps" / "api"
        (api / "src").mkdir(parents=True)
        (api / "package.json").write_text(
            json.dumps({"scripts": {"lint": "eslint ."}}), encoding="utf-8"
        )
        return tmp_path

    @staticmethod
    @contextmanager
    def _real_detection(root: Path) -> Iterator[None]:
        """Undo the module's autouse mocks.

        This class needs the REAL detector, because the whole point is that
        two workspaces get DIFFERENT answers from it.
        """
        with (
            patch(
                "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write."
                "has_llm_commands_in_package_json",
                real_has_llm_commands,
            ),
            patch(
                "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write."
                "resolve_project_root",
                return_value=str(root),
            ),
        ):
            yield

    @staticmethod
    def _hook_input(file_path: Path) -> dict[str, Any]:
        return {"tool_name": "Write", "tool_input": {"file_path": str(file_path)}}

    @staticmethod
    def _declare(handler: ValidateEslintOnWriteHandler, root: Path, declare: bool = True) -> None:
        """Inject the declared projects, as the daemon does at config load."""
        projects = (
            [{"name": "web", "root": "apps/web"}, {"name": "api", "root": "apps/api"}]
            if declare
            else []
        )
        handler._project_registry = ProjectRegistry.from_config(
            Config.model_validate({"projects": projects}), root
        )

    def test_runs_eslint_in_the_files_own_workspace(self, tmp_path: Path) -> None:
        root = self._monorepo(tmp_path)
        edited = root / "apps" / "web" / "src" / "page.ts"
        edited.write_text("const x = 1;")

        with self._real_detection(root):
            handler = ValidateEslintOnWriteHandler()
            self._declare(handler, root)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                handler.handle(self._hook_input(edited))

        assert mock_run.call_args[1]["cwd"] == str(root / "apps" / "web")

    def test_undeclared_monorepo_is_not_split_up(self, tmp_path: Path) -> None:
        """Anti-inference pin: nothing declared means the repository root.

        `apps/web` has a package.json with llm: scripts. Undeclared, the
        handler must resolve to the root — which has no manifest, so advisory
        — rather than deciding for itself that `apps/web` is a project.
        """
        root = self._monorepo(tmp_path)
        edited = root / "apps" / "web" / "src" / "page.ts"
        edited.write_text("const x = 1;")

        with self._real_detection(root):
            handler = ValidateEslintOnWriteHandler()
            self._declare(handler, root, declare=False)
            with patch("subprocess.run") as mock_run:
                result = handler.handle(self._hook_input(edited))

        assert result.decision == Decision.ALLOW
        assert mock_run.call_count == 0

    def test_sibling_workspace_without_llm_scripts_is_advisory(self, tmp_path: Path) -> None:
        """The api workspace must NOT inherit web's enforcement mode."""
        root = self._monorepo(tmp_path)
        edited = root / "apps" / "api" / "src" / "server.ts"
        edited.write_text("const x = 1;")

        with self._real_detection(root):
            handler = ValidateEslintOnWriteHandler()
            self._declare(handler, root)
            with patch("subprocess.run") as mock_run:
                result = handler.handle(self._hook_input(edited))

        assert result.decision == Decision.ALLOW
        assert mock_run.call_count == 0, "advisory mode must not run ESLint"

    def test_prepends_the_workspaces_own_node_modules_bin(self, tmp_path: Path) -> None:
        root = self._monorepo(tmp_path)
        bin_dir = root / "apps" / "web" / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        edited = root / "apps" / "web" / "src" / "page.ts"
        edited.write_text("const x = 1;")

        with self._real_detection(root):
            handler = ValidateEslintOnWriteHandler()
            self._declare(handler, root)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                handler.handle(self._hook_input(edited))

        assert mock_run.call_args[1]["env"]["PATH"].startswith(str(bin_dir))

    def test_explicit_workspace_root_still_pins_every_file(self, tmp_path: Path) -> None:
        """The documented test seam survives: an explicit root wins outright.

        The edited file lives in `api`, but the pin names `web` -- so both the
        cwd AND the mode come from `web`, overriding per-file resolution
        entirely. (Pinning to `api` would be indistinguishable from resolving
        it, which is why the file and the pin deliberately disagree here.)
        """
        root = self._monorepo(tmp_path)
        edited = root / "apps" / "api" / "src" / "server.ts"
        edited.write_text("const x = 1;")

        with self._real_detection(root):
            handler = ValidateEslintOnWriteHandler(workspace_root=root / "apps" / "web")
            # Declarations are present AND disagree with the pin (the edited
            # file is in `api`): the pin must still win, which is what makes
            # it a usable test seam.
            self._declare(handler, root)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                handler.handle(self._hook_input(edited))

        assert mock_run.call_args[1]["cwd"] == str(root / "apps" / "web")
