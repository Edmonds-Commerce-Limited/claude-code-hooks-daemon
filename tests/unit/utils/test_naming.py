"""Tests for naming conversion utilities."""

from claude_code_hooks_daemon.utils.naming import (
    class_name_to_config_key,
    config_key_to_display_name,
    display_name_to_config_key,
)


class TestClassNameToConfigKey:
    """Tests for class_name_to_config_key function."""

    def test_simple_handler_name(self) -> None:
        """Test simple PascalCase handler name conversion."""
        assert class_name_to_config_key("DestructiveGitHandler") == "destructive_git"
        assert class_name_to_config_key("SedBlockerHandler") == "sed_blocker"

    def test_multiword_handler_name(self) -> None:
        """Test multi-word handler name conversion."""
        assert class_name_to_config_key("HelloWorldPreToolUseHandler") == "hello_world_pre_tool_use"
        assert class_name_to_config_key("AutoApproveReadsHandler") == "auto_approve_reads"

    def test_acronym_in_name(self) -> None:
        """Test handler names with acronyms."""
        assert class_name_to_config_key("TDDEnforcementHandler") == "tdd_enforcement"
        assert class_name_to_config_key("QaSuppressionHandler") == "qa_suppression"
        # If someone used all caps prefix, it would split oddly
        assert class_name_to_config_key("ESLintDisableHandler") == "es_lint_disable"

    def test_handler_suffix_removal(self) -> None:
        """Test that Handler suffix is properly removed."""
        assert class_name_to_config_key("CleanupHandler") == "cleanup"
        assert class_name_to_config_key("MyCustomHandler") == "my_custom"

    def test_without_handler_suffix(self) -> None:
        """Test conversion when Handler suffix is missing."""
        assert class_name_to_config_key("DestructiveGit") == "destructive_git"
        assert class_name_to_config_key("SedBlocker") == "sed_blocker"

    def test_single_word(self) -> None:
        """Test single-word class names."""
        assert class_name_to_config_key("CleanupHandler") == "cleanup"
        assert class_name_to_config_key("Cleanup") == "cleanup"

    def test_with_numbers(self) -> None:
        """Test class names containing numbers."""
        assert class_name_to_config_key("Http2Handler") == "http2"
        assert class_name_to_config_key("Git2HttpHandler") == "git2_http"

    def test_consecutive_capitals(self) -> None:
        """Test handling of consecutive capital letters."""
        assert class_name_to_config_key("HTTPSHandler") == "https"
        assert class_name_to_config_key("XMLParser") == "xml_parser"

    def test_real_handler_names(self) -> None:
        """Test conversion of actual handler class names from the codebase."""
        # Safety handlers
        assert class_name_to_config_key("AbsolutePathHandler") == "absolute_path"
        assert class_name_to_config_key("WorktreeFileCopyHandler") == "worktree_file_copy"

        # QA handlers
        assert class_name_to_config_key("QaSuppressionHandler") == "qa_suppression"
        assert class_name_to_config_key("MarkdownOrganizationHandler") == "markdown_organization"

        # Workflow handlers
        assert class_name_to_config_key("GhIssueCommentsHandler") == "gh_issue_comments"
        assert (
            class_name_to_config_key("YoloContainerDetectionHandler") == "yolo_container_detection"
        )

        # Status line handlers
        assert class_name_to_config_key("AccountDisplayHandler") == "account_display"
        assert class_name_to_config_key("UsageTrackingHandler") == "usage_tracking"


class TestConfigKeyToDisplayName:
    """Tests for config_key_to_display_name function."""

    def test_simple_conversion(self) -> None:
        """Test simple snake_case to kebab-case conversion."""
        assert config_key_to_display_name("destructive_git") == "destructive-git"
        assert config_key_to_display_name("sed_blocker") == "sed-blocker"

    def test_multiword_conversion(self) -> None:
        """Test multi-word config key conversion."""
        assert config_key_to_display_name("hello_world_pre_tool_use") == "hello-world-pre-tool-use"
        assert config_key_to_display_name("auto_approve_reads") == "auto-approve-reads"

    def test_single_word(self) -> None:
        """Test single-word config keys (no underscores)."""
        assert config_key_to_display_name("cleanup") == "cleanup"
        assert config_key_to_display_name("validation") == "validation"

    def test_real_config_keys(self) -> None:
        """Test conversion of actual config keys from the codebase."""
        assert config_key_to_display_name("absolute_path") == "absolute-path"
        assert config_key_to_display_name("worktree_file_copy") == "worktree-file-copy"
        assert config_key_to_display_name("qa_suppression") == "qa-suppression"
        assert config_key_to_display_name("markdown_organization") == "markdown-organization"


class TestDisplayNameToConfigKey:
    """Tests for display_name_to_config_key function."""

    def test_simple_conversion(self) -> None:
        """Test simple kebab-case to snake_case conversion."""
        assert display_name_to_config_key("destructive-git") == "destructive_git"
        assert display_name_to_config_key("sed-blocker") == "sed_blocker"

    def test_multiword_conversion(self) -> None:
        """Test multi-word display name conversion."""
        assert display_name_to_config_key("hello-world-pre-tool-use") == "hello_world_pre_tool_use"
        assert display_name_to_config_key("auto-approve-reads") == "auto_approve_reads"

    def test_single_word(self) -> None:
        """Test single-word display names (no hyphens)."""
        assert display_name_to_config_key("cleanup") == "cleanup"
        assert display_name_to_config_key("validation") == "validation"

    def test_real_display_names(self) -> None:
        """Test conversion of actual display names from the codebase."""
        # Note: Real display names often have prefixes like "prevent-", "enforce-", etc.
        assert display_name_to_config_key("prevent-destructive-git") == "prevent_destructive_git"
        assert display_name_to_config_key("block-sed-command") == "block_sed_command"
        assert display_name_to_config_key("require-absolute-paths") == "require_absolute_paths"


class TestRoundTripConversions:
    """Tests for round-trip conversions between formats."""

    def test_config_to_display_to_config(self) -> None:
        """Test config_key -> display_name -> config_key."""
        original = "destructive_git"
        display = config_key_to_display_name(original)
        result = display_name_to_config_key(display)
        assert result == original

        original = "hello_world_pre_tool_use"
        display = config_key_to_display_name(original)
        result = display_name_to_config_key(display)
        assert result == original

    def test_display_to_config_to_display(self) -> None:
        """Test display_name -> config_key -> display_name."""
        original = "destructive-git"
        config = display_name_to_config_key(original)
        result = config_key_to_display_name(config)
        assert result == original

        original = "hello-world-pre-tool-use"
        config = display_name_to_config_key(original)
        result = config_key_to_display_name(config)
        assert result == original


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_string(self) -> None:
        """Test conversion of empty strings."""
        assert class_name_to_config_key("") == ""
        assert config_key_to_display_name("") == ""
        assert display_name_to_config_key("") == ""

    def test_already_lowercase(self) -> None:
        """Test class names that are already lowercase (unusual but valid)."""
        assert class_name_to_config_key("myhandler") == "myhandler"
        assert class_name_to_config_key("handlerHandler") == "handler"

    def test_all_caps(self) -> None:
        """Test all-caps class names."""
        assert class_name_to_config_key("HANDLER") == "handler"
        assert class_name_to_config_key("TDD") == "tdd"

    def test_mixed_underscores_and_case(self) -> None:
        """Test that underscores in class names are preserved."""
        # This is unusual in Python class names but should handle gracefully
        assert class_name_to_config_key("My_Custom_Handler") == "my__custom_"
