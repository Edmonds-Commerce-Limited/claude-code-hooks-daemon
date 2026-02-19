"""Tests for ValidateEslintOnWriteHandler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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
        ["dist", ".build", "coverage", "test-results"],
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
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert "ADVISORY" in result.reason
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_advisory_mode_suggests_llm_lint(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Advisory mode suggests creating llm:lint script."""
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)

        test_file = tmp_path / "component.tsx"
        test_file.write_text("export const App = () => <div />;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert "llm:lint" in result.reason
        assert "package.json" in result.reason
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_advisory_mode_includes_guide_path(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Advisory mode includes path to LLM command wrapper guide."""
        with patch(
            "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)

        test_file = tmp_path / "test.ts"
        test_file.write_text("const x = 1;")

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(test_file)},
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert "Full guide:" in result.reason
        assert "llm-command-wrappers.md" in result.reason
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


class TestNodeModulesBinPath:
    """Tests for node_modules/.bin PATH injection (Bug 1 fix)."""

    @pytest.fixture
    def handler(self, tmp_path: Path) -> ValidateEslintOnWriteHandler:
        return ValidateEslintOnWriteHandler(workspace_root=tmp_path)

    @patch("subprocess.run")
    def test_node_modules_bin_prepended_to_path_when_exists(
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
    def test_node_modules_bin_first_in_path(
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
