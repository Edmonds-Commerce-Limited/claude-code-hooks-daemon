"""Comprehensive tests for LockFileEditBlockerHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.lock_file_edit_blocker import (
    LockFileEditBlockerHandler,
)


class TestLockFileEditBlockerHandler:
    """Test suite for LockFileEditBlockerHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return LockFileEditBlockerHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'lock-file-edit-blocker'."""
        assert handler.name == "lock-file-edit-blocker"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (blocks execution)."""
        assert handler.terminal is True

    # matches() - PHP/Composer lock files
    def test_matches_write_composer_lock(self, handler):
        """Should match Write tool targeting composer.lock."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/path/to/composer.lock",
                "content": "modified content",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_composer_lock(self, handler):
        """Should match Edit tool targeting composer.lock."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/path/to/composer.lock",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - JavaScript lock files
    def test_matches_write_package_lock_json(self, handler):
        """Should match Write tool targeting package-lock.json."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/package-lock.json",
                "content": "{}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_yarn_lock(self, handler):
        """Should match Edit tool targeting yarn.lock."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/yarn.lock",
                "old_string": "version 1",
                "new_string": "version 2",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_pnpm_lock_yaml(self, handler):
        """Should match Write tool targeting pnpm-lock.yaml."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/app/pnpm-lock.yaml",
                "content": "lockfileVersion: 6.0",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_bun_lockb(self, handler):
        """Should match Edit tool targeting bun.lockb."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/project/bun.lockb",
                "old_string": "binary",
                "new_string": "data",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Python lock files
    def test_matches_write_poetry_lock(self, handler):
        """Should match Write tool targeting poetry.lock."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/poetry.lock",
                "content": "[[package]]",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_pipfile_lock(self, handler):
        """Should match Edit tool targeting Pipfile.lock."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/Pipfile.lock",
                "old_string": "old_hash",
                "new_string": "new_hash",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_pdm_lock(self, handler):
        """Should match Write tool targeting pdm.lock."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/app/pdm.lock",
                "content": "# pdm.lock",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Ruby lock files
    def test_matches_edit_gemfile_lock(self, handler):
        """Should match Edit tool targeting Gemfile.lock."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/rails/Gemfile.lock",
                "old_string": "GEM",
                "new_string": "GEM2",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Rust lock files
    def test_matches_write_cargo_lock(self, handler):
        """Should match Write tool targeting Cargo.lock."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/rust-project/Cargo.lock",
                "content": "# Cargo.lock",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Go lock files
    def test_matches_edit_go_sum(self, handler):
        """Should match Edit tool targeting go.sum."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/go-project/go.sum",
                "old_string": "v1.0.0",
                "new_string": "v2.0.0",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - .NET lock files
    def test_matches_write_packages_lock_json(self, handler):
        """Should match Write tool targeting packages.lock.json."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/dotnet/packages.lock.json",
                "content": '{"version": 1}',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_project_assets_json(self, handler):
        """Should match Edit tool targeting project.assets.json."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/dotnet/obj/project.assets.json",
                "old_string": "target",
                "new_string": "framework",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Swift lock files
    def test_matches_write_package_resolved(self, handler):
        """Should match Write tool targeting Package.resolved."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/swift-project/Package.resolved",
                "content": '{"version": 1}',
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Case-insensitive matching
    def test_matches_case_insensitive_cargo_lock_uppercase(self, handler):
        """Should match Cargo.LOCK (uppercase)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/Cargo.LOCK",
                "content": "content",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_package_lock_mixed(self, handler):
        """Should match Package-Lock.JSON (mixed case)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/Package-Lock.JSON",
                "content": "content",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_gemfile_lock_lowercase(self, handler):
        """Should match gemfile.lock (lowercase)."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/project/gemfile.lock",
                "old_string": "a",
                "new_string": "b",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Relative paths
    def test_matches_relative_path_composer_lock(self, handler):
        """Should match relative path to composer.lock."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "./composer.lock",
                "content": "content",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_relative_path_yarn_lock(self, handler):
        """Should match relative path to yarn.lock."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "yarn.lock",
                "old_string": "x",
                "new_string": "y",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative cases: Safe operations
    def test_matches_read_tool_returns_false(self, handler):
        """Should NOT match Read tool (reading is safe)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/path/to/package-lock.json",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should NOT match Bash tool (package manager commands are safe)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "npm install",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_non_lock_file_write_returns_false(self, handler):
        """Should NOT match Write tool on non-lock files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/package.json",
                "content": "{}",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_non_lock_file_edit_returns_false(self, handler):
        """Should NOT match Edit tool on non-lock files."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/project/README.md",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_lock_in_filename_but_not_lock_file_returns_false(self, handler):
        """Should NOT match files with 'lock' in name but not actual lock files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/my-lock-file.txt",
                "content": "content",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Edge cases
    def test_matches_empty_file_path_returns_false(self, handler):
        """Should not match empty file path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "",
                "content": "content",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_none_file_path_returns_false(self, handler):
        """Should not match when file_path is None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": None,
                "content": "content",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_key_returns_false(self, handler):
        """Should not match when file_path key is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "content": "content",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {
            "tool_name": "Write",
        }
        assert handler.matches(hook_input) is False

    # handle() - Return value and message structure
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/package-lock.json",
                "content": "{}",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/project/composer.lock",
                "old_string": "a",
                "new_string": "b",
            },
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_contains_file_name(self, handler):
        """handle() reason should include the lock file name."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/yarn.lock",
                "content": "content",
            },
        }
        result = handler.handle(hook_input)
        assert "yarn.lock" in result.reason

    def test_handle_reason_explains_danger(self, handler):
        """handle() reason should explain why editing lock files is dangerous."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/Cargo.lock",
                "content": "content",
            },
        }
        result = handler.handle(hook_input)
        assert "package manager" in result.reason.lower()

    def test_handle_reason_provides_proper_commands_composer(self, handler):
        """handle() reason should provide proper commands for composer.lock."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/project/composer.lock",
                "old_string": "x",
                "new_string": "y",
            },
        }
        result = handler.handle(hook_input)
        assert "composer install" in result.reason or "composer update" in result.reason

    def test_handle_reason_provides_proper_commands_npm(self, handler):
        """handle() reason should provide proper commands for package-lock.json."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/package-lock.json",
                "content": "{}",
            },
        }
        result = handler.handle(hook_input)
        assert "npm install" in result.reason or "npm update" in result.reason

    def test_handle_reason_provides_proper_commands_poetry(self, handler):
        """handle() reason should provide proper commands for poetry.lock."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/poetry.lock",
                "content": "content",
            },
        }
        result = handler.handle(hook_input)
        assert "poetry install" in result.reason or "poetry update" in result.reason

    def test_handle_reason_provides_proper_commands_cargo(self, handler):
        """handle() reason should provide proper commands for Cargo.lock."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/project/Cargo.lock",
                "old_string": "a",
                "new_string": "b",
            },
        }
        result = handler.handle(hook_input)
        assert "cargo update" in result.reason

    def test_handle_reason_warns_about_corruption(self, handler):
        """handle() reason should warn about corruption risks."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/go.sum",
                "content": "content",
            },
        }
        result = handler.handle(hook_input)
        assert (
            "corrupt" in result.reason.lower()
            or "break" in result.reason.lower()
            or "damage" in result.reason.lower()
        )

    # handle() - Return values
    def test_handle_context_is_empty_list(self, handler):
        """handle() context should be empty list (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/package-lock.json",
                "content": "{}",
            },
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/project/yarn.lock",
                "content": "content",
            },
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration tests
    def test_blocks_all_lock_file_types(self, handler):
        """Should block all 14 lock file types."""
        lock_files = [
            "composer.lock",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "bun.lockb",
            "poetry.lock",
            "Pipfile.lock",
            "pdm.lock",
            "Gemfile.lock",
            "Cargo.lock",
            "go.sum",
            "packages.lock.json",
            "project.assets.json",
            "Package.resolved",
        ]
        for lock_file in lock_files:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/project/{lock_file}",
                    "content": "content",
                },
            }
            assert handler.matches(hook_input) is True, f"Should block: {lock_file}"

    def test_allows_all_safe_operations(self, handler):
        """Should allow all safe operations."""
        safe_operations = [
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/project/package-lock.json"},
            },
            {
                "tool_name": "Bash",
                "tool_input": {"command": "npm install"},
            },
            {
                "tool_name": "Bash",
                "tool_input": {"command": "composer update"},
            },
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "/project/package.json", "content": "{}"},
            },
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "/project/README.md",
                    "old_string": "a",
                    "new_string": "b",
                },
            },
        ]
        for operation in safe_operations:
            assert handler.matches(operation) is False, f"Should allow: {operation}"
